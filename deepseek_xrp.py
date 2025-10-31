import os
import time
from openai import OpenAI
import ccxt
from datetime import datetime
from dotenv import load_dotenv

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
    """Thin wrapper that delegates analysis to common.analyze_with_deepseek and returns signal_data.

    common.analyze_with_deepseek returns (signal_data, raw_response).
    """
    try:
        signal_data, raw = common.analyze_with_deepseek(
            deepseek_client,
            settings.DEEPSEEK_MODEL,
            price_data,
            TRADE_CONFIG,
            signal_history,
            get_current_position,
            safe_json_parse,
            create_fallback_signal,
            save_trade_log,
            max_kline=5,
            temperature=0.1
        )

        global deepseek_last_raw
        if raw:
            deepseek_last_raw = raw

        return signal_data
    except Exception as e:
        print(f"调用通用 DeepSeek 分析失败: {e}")
        return create_fallback_signal(price_data)


def get_signal_history():
    """获取信号历史记录"""
    return signal_history


def execute_trade(signal_data, price_data):
    """Wrapper that delegates to common.execute_trade to centralize trading logic."""
    global position, deepseek_last_raw
    updated = common.execute_trade(
        exchange=exchange,
        trade_config=TRADE_CONFIG,
        signal_data=signal_data,
        price_data=price_data,
        get_current_position_fn=get_current_position,
        save_trade_log_fn=save_trade_log,
        deepseek_raw=deepseek_last_raw,
        settings_module=settings
    )
    if updated is not None:
        position = updated
    return updated


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

def wait_for_next_period():
    """Thin wrapper that delegates to common.wait_for_next_period(period_minutes=15)."""
    return common.wait_for_next_period(15)

def trading_bot():
    """主交易机器人函数"""
    # 等待到整点再执行
    wait_seconds = wait_for_next_period()
    if wait_seconds > 0:
        time.sleep(wait_seconds)

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


    # 循环执行
    while True:
        trading_bot()  # 函数内部会自己等待整点
        # 执行完后等待一段时间再检查（避免频繁循环）
        time.sleep(60)  # 每分钟检查一次


if __name__ == "__main__":
    main()
