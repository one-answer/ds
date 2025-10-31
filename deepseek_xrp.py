import os
import time
import schedule
from openai import OpenAI
import ccxt
import pandas as pd
from datetime import datetime
import json
import re
from dotenv import load_dotenv
import sqlite3

load_dotenv()

# 初始化DeepSeek客户端
deepseek_client = OpenAI(
    api_key=os.getenv('DEEPSEEK_API_KEY'),
    base_url="https://api.deepseek.com"
)

# Local imports (when running the script directly from the ds/ directory)
import common
import settings

# 交易参数配置 - 结合两个版本的优点
TRADE_CONFIG = {
    'symbol': 'XRP/USDT:USDT',  # OKX的合约符号格式
    'amount': 4,  # 交易数量 (XRP)
    'leverage': 5,  # 杠杆倍数
    'timeframe': '15m',  # 使用15分钟K线
    'test_mode': False,  # 测试模式
    'data_points': 96,  # 24小时数据（96根15分钟K线）
    'analysis_periods': {
        'short_term': 20,  # 短期均线
        'medium_term': 50,  # 中期均线
        'long_term': 96  # 长期趋势
    }
}

# 初始化OKX交易所
exchange = ccxt.okx({
    'options': {
        'defaultType': settings.DEFAULT_TYPE,  # OKX使用swap表示永续合约
    },
    'apiKey': os.getenv('OKX_API_KEY'),
    'secret': os.getenv('OKX_SECRET'),
    'password': os.getenv('OKX_PASSWORD'),  # OKX需要交易密码
})

# 全局变量存储历史数据
price_history = []
signal_history = []
position = None

# SQLite database path
DB_PATH = os.path.join(os.path.dirname(__file__), 'trading_logs.db')


def init_db():
    return common.init_db(DB_PATH)


def save_trade_log(price_data=None, deepseek_raw=None, signal_data=None, current_position=None,
                   operation_type=None, required_margin=None, order_status=None, updated_position=None, extra=None):
    return common.save_trade_log(DB_PATH, TRADE_CONFIG, price_data, deepseek_raw, signal_data, current_position,
                                 operation_type, required_margin, order_status, updated_position, extra)


# Global to store DeepSeek raw reply for logging
deepseek_last_raw = None


def setup_exchange():
    """设置交易所参数"""
    try:
        # OKX设置杠杆
        exchange.set_leverage(
            TRADE_CONFIG['leverage'],
            TRADE_CONFIG['symbol'],
            {'mgnMode': settings.MARGIN_MODE}  # 全仓模式
        )
        print(f"设置杠杆倍数: {TRADE_CONFIG['leverage']}x, mgnMode={settings.MARGIN_MODE}")

        # 获取余额
        balance = exchange.fetch_balance()
        usdt_balance = balance['USDT']['free']
        print(f"当前USDT余额: {usdt_balance:.5f}")

        return True
    except Exception as e:
        print(f"交易所设置失败: {e}")
        return False


def calculate_technical_indicators(df):
    return common.calculate_technical_indicators(df)


def get_support_resistance_levels(df, lookback=20):
    return common.get_support_resistance_levels(df, lookback)


def get_market_trend(df):
    return common.get_market_trend(df)


def get_btc_ohlcv_enhanced():
    return common.get_ohlcv_enhanced(exchange, TRADE_CONFIG)


def generate_technical_analysis_text(price_data):
    return common.generate_technical_analysis_text(price_data)


def get_current_position():
    return common.get_current_position(exchange, TRADE_CONFIG['symbol'], TRADE_CONFIG['leverage'])


def safe_json_parse(json_str):
    return common.safe_json_parse(json_str)


def create_fallback_signal(price_data):
    return common.create_fallback_signal(price_data)


def analyze_with_deepseek(price_data):
    """使用DeepSeek分析市场并生成交易信号（增强版）"""

    # 生成技术分析文本
    technical_analysis = generate_technical_analysis_text(price_data)

    # 构建K线数据文本
    kline_text = f"【最近5根{TRADE_CONFIG['timeframe']}K线数据】\n"
    for i, kline in enumerate(price_data['kline_data'][-5:]):
        trend = "阳线" if kline['close'] > kline['open'] else "阴线"
        change = ((kline['close'] - kline['open']) / kline['open']) * 100
        kline_text += f"K线{i + 1}: {trend} 开盘:{kline['open']:.5f} 收盘:{kline['close']:.5f} 涨跌:{change:+.5f}%\n"

    # 添加上次交易信号
    signal_text = ""
    if signal_history:
        last_signal = signal_history[-1]
        signal_text = f"\n【上次交易信号】\n信号: {last_signal.get('signal', 'N/A')}\n信心: {last_signal.get('confidence', 'N/A')}"

    # 添加当前持仓信息
    current_pos = get_current_position()
    position_text = "无持仓" if not current_pos else f"{current_pos['side']}仓, 数量: {current_pos['size']}, 盈亏: {current_pos['unrealized_pnl']:.5f}USDT"

    prompt = f"""
    你是一个专业的加密货币交易分析师。请基于以下XRP/USDT {TRADE_CONFIG['timeframe']}周期数据进行分析：

    {kline_text}

    {technical_analysis}

    {signal_text}

    【当前行情】
    - 当前价格: ${price_data['price']:,.5f}
    - 时间: {price_data['timestamp']}
    - 本K线最高: ${price_data['high']:,.5f}
    - 本K线最低: ${price_data['low']:,.5f}
    - 本K线成交量: {price_data['volume']:.5f} XRP
    - 价格变化: {price_data['price_change']:+.5f}%
    - 当前持仓: {position_text}

    【分析要求】
    1. 基于{TRADE_CONFIG['timeframe']}K线趋势和技术指标给出交易信号: BUY(买入) / SELL(卖出) / HOLD(观望)
    2. 简要分析理由（考虑趋势连续性、支撑阻力、成交量等因素）
    3. 基于技术分析建议合理的止损价位
    4. 基于技术分析建议合理的止盈价位
    5. 评估信号信心程度

    【重要格式要求】
    - 必须返回纯JSON格式，不要有任何额外文本
    - 所有属性名必须使用双引号
    - 不要使用单引号
    - 不要添加注释
    - 确保JSON格式完全正确

    请用以下JSON格式回复：
    {{
        "signal": "BUY|SELL|HOLD",
        "reason": "分析理由",
        "stop_loss": 具体价格,
        "take_profit": 具体价格,
        "confidence": "HIGH|MEDIUM|LOW"
    }}
    """

    try:
        response = deepseek_client.chat.completions.create(
            model=settings.DEEPSEEK_MODEL,
            messages=[
                {"role": "system",
                 "content": f"您是一位专业的交易员，专注于{TRADE_CONFIG['timeframe']}周期趋势分析。请结合K线形态和技术指标做出判断，并严格遵循JSON格式要求。"},
                {"role": "user", "content": prompt}
            ],
            stream=False,
            temperature=0.1
        )

        # 安全解析JSON
        result = response.choices[0].message.content
        print(f"DeepSeek原始回复: {result}")

        # 提取JSON部分
        start_idx = result.find('{')
        end_idx = result.rfind('}') + 1

        if start_idx != -1 and end_idx != 0:
            json_str = result[start_idx:end_idx]
            signal_data = safe_json_parse(json_str)

            if signal_data is None:
                signal_data = create_fallback_signal(price_data)
        else:
            signal_data = create_fallback_signal(price_data)

        # 验证必需字段
        required_fields = ['signal', 'reason', 'stop_loss', 'take_profit', 'confidence']
        if not all(field in signal_data for field in required_fields):
            signal_data = create_fallback_signal(price_data)

        # 保存信号到历史记录
        signal_data['timestamp'] = price_data['timestamp']
        signal_history.append(signal_data)
        if len(signal_history) > 30:
            signal_history.pop(0)

        # 信号统计
        signal_count = len([s for s in signal_history if s.get('signal') == signal_data['signal']])
        total_signals = len(signal_history)
        print(f"信号统计: {signal_data['signal']} (最近{total_signals}次中出现{signal_count}次)")

        # 信号连续性检查
        if len(signal_history) >= 3:
            last_three = [s['signal'] for s in signal_history[-3:]]
            if len(set(last_three)) == 1:
                print(f"⚠️ 注意：连续3次{signal_data['signal']}信号")

        # 保存DeepSeek原始回复到日志
        global deepseek_last_raw
        deepseek_last_raw = result
        save_trade_log(price_data, deepseek_raw=deepseek_last_raw, signal_data=signal_data,
                       current_position=get_current_position())

        return signal_data

    except Exception as e:
        print(f"DeepSeek分析失败: {e}")
        return create_fallback_signal(price_data)


def execute_trade(signal_data, price_data):
    """执行交易 - OKX版本（修复保证金检查）"""
    global position

    current_position = get_current_position()

    print(f"交易信号: {signal_data['signal']}")
    print(f"信心程度: {signal_data['confidence']}")
    print(f"理由: {signal_data['reason']}")
    print(f"止损: ${signal_data['stop_loss']:,.5f}")
    print(f"止盈: ${signal_data['take_profit']:,.5f}")
    print(f"当前持仓: {current_position}")

    # 风险管理：低信心信号不执行
    if signal_data['confidence'] == 'LOW' and not TRADE_CONFIG['test_mode']:
        print("⚠️ 低信心信号，跳过执行")
        return

    if TRADE_CONFIG['test_mode']:
        print("测试模式 - 仅模拟交易")
        return

    try:
        # 获取账户余额
        balance = exchange.fetch_balance()
        usdt_balance = balance['USDT']['free']

        # 智能保证金检查
        required_margin = 0
        operation_type = None

        if signal_data['signal'] == 'BUY':
            if current_position and current_position['side'] == 'short':
                # 平空仓 + 开多仓：需要额外保证金
                required_margin = price_data['price'] * TRADE_CONFIG['amount'] / TRADE_CONFIG['leverage']
                operation_type = "平空开多"
            elif not current_position:
                # 开多仓：需要保证金
                required_margin = price_data['price'] * TRADE_CONFIG['amount'] / TRADE_CONFIG['leverage']
                operation_type = "开多仓"
            else:
                # 已持有多仓：不需要额外保证金
                required_margin = 0
                operation_type = "保持多仓"

        elif signal_data['signal'] == 'SELL':
            if current_position and current_position['side'] == 'long':
                # 平多仓 + 开空仓：需要额外保证金
                required_margin = price_data['price'] * TRADE_CONFIG['amount'] / TRADE_CONFIG['leverage']
                operation_type = "平多开空"
            elif not current_position:
                # 开空仓：需要保证金
                required_margin = price_data['price'] * TRADE_CONFIG['amount'] / TRADE_CONFIG['leverage']
                operation_type = "开空仓"
            else:
                # 已持有空仓：不需要额外保证金
                required_margin = 0
                operation_type = "保持空仓"

        elif signal_data['signal'] == 'HOLD':
            print("建议观望，不执行交易")
            return

        print(f"操作类型: {operation_type}, 需要保证金: {required_margin:.5f} USDT")

        # 只有在需要额外保证金时才检查
        if required_margin > 0:
            if required_margin > usdt_balance * 0.8:
                print(f"⚠️ 保证金不足，跳过交易。需要: {required_margin:.5f} USDT, 可用: {usdt_balance:.5f} USDT")
                return
        else:
            print("✅ 无需额外保证金，继续执行")

        # 执行交易逻辑   tag 是我的经纪商api（不拿白不拿），不会影响大家返佣，介意可以删除
        if signal_data['signal'] == 'BUY':
            if current_position and current_position['side'] == 'short':
                print("平空仓并开多仓...")
                # 平空仓
                exchange.create_market_order(
                    TRADE_CONFIG['symbol'],
                    'buy',
                    current_position['size'],
                    params={'reduceOnly': True, 'tag': settings.BROKER_TAG}
                )
                time.sleep(1)
                # 开多仓
                exchange.create_market_order(
                    TRADE_CONFIG['symbol'],
                    'buy',
                    TRADE_CONFIG['amount'],
                    params={'tag': settings.BROKER_TAG}
                )
            elif current_position and current_position['side'] == 'long':
                print("已有多头持仓，保持现状")
            else:
                # 无持仓时开多仓
                print("开多仓...")
                exchange.create_market_order(
                    TRADE_CONFIG['symbol'],
                    'buy',
                    TRADE_CONFIG['amount'],
                    params={'tag': settings.BROKER_TAG, 'takeProfit': {
                        'triggerPrice': signal_data['take_profit'],
                        'price': signal_data['take_profit'],
                        'reduceOnly': True
                    },
                            'stopLoss': {
                                'triggerPrice': signal_data['stop_loss'],
                                'price': signal_data['stop_loss'],
                                'reduceOnly': True
                            }}
                )

        elif signal_data['signal'] == 'SELL':
            if current_position and current_position['side'] == 'long':
                print("平多仓并开空仓...")
                # 平多仓
                exchange.create_market_order(
                    TRADE_CONFIG['symbol'],
                    'sell',
                    current_position['size'],
                    params={'reduceOnly': True, 'tag': settings.BROKER_TAG}
                )
                time.sleep(1)
                # 开空仓
                exchange.create_market_order(
                    TRADE_CONFIG['symbol'],
                    'sell',
                    TRADE_CONFIG['amount'],
                    params={'tag': settings.BROKER_TAG}
                )
            elif current_position and current_position['side'] == 'short':
                # 平空仓
                exchange.create_market_order(
                    TRADE_CONFIG['symbol'],
                    'buy',
                    current_position['size'],
                    params={'reduceOnly': True, 'tag': settings.BROKER_TAG}
                )
                print("空头持仓已平仓")
            else:
                # 无持仓时开空仓
                print("开空仓...")
                exchange.create_market_order(
                    TRADE_CONFIG['symbol'],
                    'sell',
                    TRADE_CONFIG['amount'],
                    params={'tag': settings.BROKER_TAG, 'takeProfit': {  # 止盈设置（价格下跌时触发）
                        'triggerPrice': signal_data['take_profit'],  # 触发价（低于开仓价）
                        'price': signal_data['take_profit'],
                        'reduceOnly': True  # 仅平仓
                    },
                            'stopLoss': {  # 止损设置（价格上涨时触发）
                                'triggerPrice': signal_data['stop_loss'],  # 触发价（高于开仓价）
                                'price': signal_data['stop_loss'],
                                'reduceOnly': True
                            }}
                )

        print("订单执行成功")
        time.sleep(2)
        position = get_current_position()
        print(f"更新后持仓: {position}")

        # 保存交易日志
        save_trade_log(price_data=price_data, deepseek_raw=deepseek_last_raw, signal_data=signal_data,
                       current_position=position, operation_type=operation_type, required_margin=required_margin,
                       order_status="成功", updated_position=position)

    except Exception as e:
        print(f"订单执行失败: {e}")
        import traceback
        traceback.print_exc()


def analyze_with_deepseek_with_retry(price_data, max_retries=2):
    """带重试的DeepSeek分析"""
    for attempt in range(max_retries):
        try:
            signal_data = analyze_with_deepseek(price_data)
            if signal_data and not signal_data.get('is_fallback', False):
                return signal_data

            print(f"第{attempt + 1}次尝试失败，进行重试...")
            time.sleep(1)

        except Exception as e:
            print(f"第{attempt + 1}次尝试异常: {e}")
            if attempt == max_retries - 1:
                return create_fallback_signal(price_data)
            time.sleep(1)

    return create_fallback_signal(price_data)


def trading_bot():
    """主交易机器人函数"""
    print("\n" + "=" * 60)
    print(f"执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # 1. 获取增强版K线数据
    price_data = get_btc_ohlcv_enhanced()
    if not price_data:
        return

    print(f"XRP当前价格: ${price_data['price']:,.5f}")
    print(f"数据周期: {TRADE_CONFIG['timeframe']}")
    print(f"价格变化: {price_data['price_change']:+.5f}%")

    # 2. 使用DeepSeek分析（带重试）
    signal_data = analyze_with_deepseek_with_retry(price_data)

    if signal_data.get('is_fallback', False):
        print("⚠️ 使用备用交易信号")

    # 3. 执行交易
    execute_trade(signal_data, price_data)


def main():
    """主函数"""
    print("XRP/USDT OKX自动交易机器人启动成功！")
    print("融合技术指标策略 + OKX实盘接口")

    if TRADE_CONFIG['test_mode']:
        print("当前为模拟模式，不会真实下单")
    else:
        print("实盘交易模式，请谨慎操作！")

    print(f"交易周期: {TRADE_CONFIG['timeframe']}")
    print("已启用完整技术指标分析和持仓跟踪功能")

    # 设置交易所
    if not setup_exchange():
        print("交易所初始化失败，程序退出")
        return

    # 初始化数据库
    init_db()

    # 根据时间周期设置执行频率
    if TRADE_CONFIG['timeframe'] == '1h':
        schedule.every().hour.at(":01").do(trading_bot)
        print("执行频率: 每小时一次")
    elif TRADE_CONFIG['timeframe'] == '15m':
        schedule.every(15).minutes.do(trading_bot)
        print("执行频率: 每15分钟一次")
    elif TRADE_CONFIG['timeframe'] == '1m':
        schedule.every(1).minutes.do(trading_bot)
        print("执行频率: 每1分钟一次")
    else:
        schedule.every().hour.at(":01").do(trading_bot)
        print("执行频率: 每小时一次")

    # 立即执行一次
    trading_bot()

    # 循环执行
    while True:
        schedule.run_pending()
        time.sleep(1)


if __name__ == "__main__":
    main()
