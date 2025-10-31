import json
import re
from datetime import datetime
import sqlite3
import pandas as pd
import time


def init_db(db_path):
    """Initialize the SQLite database and create table if not exists."""
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute('''
                    CREATE TABLE IF NOT EXISTS trade_logs
                    (
                        id
                        INTEGER
                        PRIMARY
                        KEY
                        AUTOINCREMENT,
                        created_at
                        TEXT,
                        symbol
                        TEXT,
                        timeframe
                        TEXT,
                        price
                        REAL,
                        price_change
                        REAL,
                        deepseek_raw
                        TEXT,
                        signal
                        TEXT,
                        reason
                        TEXT,
                        stop_loss
                        REAL,
                        take_profit
                        REAL,
                        confidence
                        TEXT,
                        current_position
                        TEXT,
                        operation_type
                        TEXT,
                        required_margin
                        REAL,
                        order_status
                        TEXT,
                        updated_position
                        TEXT,
                        extra
                        TEXT
                    )
                    ''')
        conn.commit()
    except Exception as e:
        print(f"初始化数据库失败: {e}")
    finally:
        try:
            if conn:
                conn.close()
        except Exception:
            pass


def save_trade_log(db_path, trade_config, price_data=None, deepseek_raw=None, signal_data=None, current_position=None,
                   operation_type=None, required_margin=None, order_status=None, updated_position=None, extra=None):
    """Save a structured log row into SQLite."""
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        symbol = trade_config.get('symbol')
        timeframe = trade_config.get('timeframe')
        price = float(price_data['price']) if price_data and 'price' in price_data else None
        price_change = float(price_data['price_change']) if price_data and 'price_change' in price_data else None
        deepseek_raw_txt = deepseek_raw if deepseek_raw else None

        signal = signal_data.get('signal') if signal_data else None
        reason = signal_data.get('reason') if signal_data else None
        stop_loss = float(signal_data.get('stop_loss')) if signal_data and signal_data.get(
            'stop_loss') is not None else None
        take_profit = float(signal_data.get('take_profit')) if signal_data and signal_data.get(
            'take_profit') is not None else None
        confidence = signal_data.get('confidence') if signal_data else None

        cur.execute('''
                    INSERT INTO trade_logs (created_at, symbol, timeframe, price, price_change, deepseek_raw, signal,
                                            reason, stop_loss, take_profit, confidence,
                                            current_position, operation_type, required_margin, order_status,
                                            updated_position, extra)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        created_at,
                        symbol,
                        timeframe,
                        price,
                        price_change,
                        deepseek_raw_txt,
                        signal,
                        reason,
                        stop_loss,
                        take_profit,
                        confidence,
                        json.dumps(current_position) if current_position is not None else None,
                        operation_type,
                        required_margin,
                        order_status,
                        json.dumps(updated_position) if updated_position is not None else None,
                        json.dumps(extra) if extra is not None else None
                    ))
        conn.commit()
    except Exception as e:
        print(f"保存日志失败: {e}")
    finally:
        try:
            if conn:
                conn.close()
        except Exception:
            pass


def calculate_technical_indicators(df):
    """计算技术指标"""
    try:
        df['sma_5'] = df['close'].rolling(window=5, min_periods=1).mean()
        df['sma_20'] = df['close'].rolling(window=20, min_periods=1).mean()
        df['sma_50'] = df['close'].rolling(window=50, min_periods=1).mean()

        df['ema_12'] = df['close'].ewm(span=12).mean()
        df['ema_26'] = df['close'].ewm(span=26).mean()
        df['macd'] = df['ema_12'] - df['ema_26']
        df['macd_signal'] = df['macd'].ewm(span=9).mean()
        df['macd_histogram'] = df['macd'] - df['macd_signal']

        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))

        df['bb_middle'] = df['close'].rolling(20).mean()
        bb_std = df['close'].rolling(20).std()
        df['bb_upper'] = df['bb_middle'] + (bb_std * 2)
        df['bb_lower'] = df['bb_middle'] - (bb_std * 2)
        df['bb_position'] = (df['close'] - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'])

        df['volume_ma'] = df['volume'].rolling(20).mean()
        df['volume_ratio'] = df['volume'] / df['volume_ma']

        df['resistance'] = df['high'].rolling(20).max()
        df['support'] = df['low'].rolling(20).min()

        df = df.bfill().ffill()

        return df
    except Exception as e:
        print(f"技术指标计算失败: {e}")
        return df


def get_support_resistance_levels(df, lookback=20):
    try:
        recent_high = df['high'].tail(lookback).max()
        recent_low = df['low'].tail(lookback).min()
        current_price = df['close'].iloc[-1]

        resistance_level = recent_high
        support_level = recent_low

        bb_upper = df['bb_upper'].iloc[-1]
        bb_lower = df['bb_lower'].iloc[-1]

        return {
            'static_resistance': resistance_level,
            'static_support': support_level,
            'dynamic_resistance': bb_upper,
            'dynamic_support': bb_lower,
            'price_vs_resistance': ((resistance_level - current_price) / current_price) * 100,
            'price_vs_support': ((current_price - support_level) / support_level) * 100
        }
    except Exception as e:
        print(f"支撑阻力计算失败: {e}")
        return {}


def get_market_trend(df):
    try:
        current_price = df['close'].iloc[-1]
        trend_short = "上涨" if current_price > df['sma_20'].iloc[-1] else "下跌"
        trend_medium = "上涨" if current_price > df['sma_50'].iloc[-1] else "下跌"
        macd_trend = "bullish" if df['macd'].iloc[-1] > df['macd_signal'].iloc[-1] else "bearish"

        if trend_short == "上涨" and trend_medium == "上涨":
            overall_trend = "强势上涨"
        elif trend_short == "下跌" and trend_medium == "下跌":
            overall_trend = "强势下跌"
        else:
            overall_trend = "震荡整理"

        return {
            'short_term': trend_short,
            'medium_term': trend_medium,
            'macd': macd_trend,
            'overall': overall_trend,
            'rsi_level': df['rsi'].iloc[-1]
        }
    except Exception as e:
        print(f"趋势分析失败: {e}")
        return {}


def get_ohlcv_enhanced(exchange, trade_config):
    """Generic function to fetch OHLCV and compute technical indicators."""
    try:
        ohlcv = exchange.fetch_ohlcv(trade_config['symbol'], trade_config['timeframe'],
                                     limit=trade_config['data_points'])
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df = calculate_technical_indicators(df)

        current_data = df.iloc[-1]
        previous_data = df.iloc[-2]

        trend_analysis = get_market_trend(df)
        levels_analysis = get_support_resistance_levels(df)

        return {
            'price': current_data['close'],
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'high': current_data['high'],
            'low': current_data['low'],
            'volume': current_data['volume'],
            'timeframe': trade_config['timeframe'],
            'price_change': ((current_data['close'] - previous_data['close']) / previous_data['close']) * 100,
            'kline_data': df[['timestamp', 'open', 'high', 'low', 'close', 'volume']].tail(10).to_dict('records'),
            'technical_data': {
                'sma_5': current_data.get('sma_5', 0),
                'sma_20': current_data.get('sma_20', 0),
                'sma_50': current_data.get('sma_50', 0),
                'rsi': current_data.get('rsi', 0),
                'macd': current_data.get('macd', 0),
                'macd_signal': current_data.get('macd_signal', 0),
                'macd_histogram': current_data.get('macd_histogram', 0),
                'bb_upper': current_data.get('bb_upper', 0),
                'bb_lower': current_data.get('bb_lower', 0),
                'bb_position': current_data.get('bb_position', 0),
                'volume_ratio': current_data.get('volume_ratio', 0)
            },
            'trend_analysis': trend_analysis,
            'levels_analysis': levels_analysis,
            'full_data': df
        }
    except Exception as e:
        print(f"获取增强K线数据失败: {e}")
        return None


def generate_technical_analysis_text(price_data):
    """生成技术分析文本"""
    if 'technical_data' not in price_data:
        return "技术指标数据不可用"

    tech = price_data['technical_data']
    trend = price_data.get('trend_analysis', {})
    levels = price_data.get('levels_analysis', {})

    def safe_float(value, default=0):
        return float(value) if value and pd.notna(value) else default

    analysis_text = f"""
    【技术指标分析】
    📈 移动平均线:
    - 5周期: {safe_float(tech['sma_5']):.5f} | 价格相对: {(price_data['price'] - safe_float(tech['sma_5'])) / safe_float(tech['sma_5']) * 100:+.5f}%
    - 20周期: {safe_float(tech['sma_20']):.5f} | 价格相对: {(price_data['price'] - safe_float(tech['sma_20'])) / safe_float(tech['sma_20']) * 100:+.5f}%
    - 50周期: {safe_float(tech['sma_50']):.5f} | 价格相对: {(price_data['price'] - safe_float(tech['sma_50'])) / safe_float(tech['sma_50']) * 100:+.5f}%

    🎯 趋势分析:
    - 短期趋势: {trend.get('short_term', 'N/A')}
    - 中期趋势: {trend.get('medium_term', 'N/A')}
    - 整体趋势: {trend.get('overall', 'N/A')}
    - MACD方向: {trend.get('macd', 'N/A')}

    📊 动量指标:
    - RSI: {safe_float(tech['rsi']):.5f} ({'超买' if safe_float(tech['rsi']) > 70 else '超卖' if safe_float(tech['rsi']) < 30 else '中性'})
    - MACD: {safe_float(tech['macd']):.5f}
    - 信号线: {safe_float(tech['macd_signal']):.5f}

    🎚️ 布林带位置: {safe_float(tech['bb_position']):.2%} ({'上部' if safe_float(tech['bb_position']) > 0.7 else '下部' if safe_float(tech['bb_position']) < 0.3 else '中部'})

    💰 关键水平:
    - 静态阻力: {safe_float(levels.get('static_resistance', 0)):.5f}
    - 静态支撑: {safe_float(levels.get('static_support', 0)):.5f}
    """
    return analysis_text


def get_current_position(exchange, symbol, default_leverage):
    """获取当前持仓情况 - 通用实现"""
    try:
        positions = exchange.fetch_positions([symbol])

        for pos in positions:
            if pos.get('symbol') == symbol:
                contracts = float(pos.get('contracts')) if pos.get('contracts') else 0

                if contracts > 0:
                    return {
                        'side': pos.get('side'),
                        'size': contracts,
                        'entry_price': float(pos.get('entryPrice')) if pos.get('entryPrice') else 0,
                        'unrealized_pnl': float(pos.get('unrealizedPnl')) if pos.get('unrealizedPnl') else 0,
                        'leverage': float(pos.get('leverage')) if pos.get('leverage') else default_leverage,
                        'symbol': pos.get('symbol')
                    }

        return None

    except Exception as e:
        print(f"获取持仓失败: {e}")
        import traceback
        traceback.print_exc()
        return None


def safe_json_parse(json_str):
    """安全解析JSON，处理格式不规范的情况"""
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        try:
            json_str = json_str.replace("'", '"')
            json_str = re.sub(r'(\w+):', r'"\1":', json_str)
            json_str = re.sub(r',\s*}', '}', json_str)
            json_str = re.sub(r',\s*]', ']', json_str)
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            print(f"JSON解析失败，原始内容: {json_str}")
            print(f"错误详情: {e}")
            return None


# 新增公共函数：等待到下一个周期整点（默认15分钟）
def wait_for_next_period(period_minutes=15):
    """等待到下一个15分钟整点"""
    now = datetime.now()
    current_minute = now.minute
    current_second = now.second

    # 计算下一个整点时间（00, 15, 30, 45分钟）
    next_period_minute = ((current_minute // 15) + 1) * 15
    if next_period_minute == 60:
        next_period_minute = 0

    # 计算需要等待的总秒数
    if next_period_minute > current_minute:
        minutes_to_wait = next_period_minute - current_minute
    else:
        minutes_to_wait = 60 - current_minute + next_period_minute

    seconds_to_wait = minutes_to_wait * 60 - current_second

    # 显示友好的等待时间
    display_minutes = minutes_to_wait - 1 if current_second > 0 else minutes_to_wait
    display_seconds = 60 - current_second if current_second > 0 else 0

    if display_minutes > 0:
        print(f"🕒 等待 {display_minutes} 分 {display_seconds} 秒到整点...")
    else:
        print(f"🕒 等待 {display_seconds} 秒到整点...")

    return seconds_to_wait


def create_fallback_signal(price_data):
    return {
        "signal": "HOLD",
        "reason": "因技术分析暂时不可用，采取保守策略",
        "stop_loss": price_data['price'] * 0.98,
        "take_profit": price_data['price'] * 1.02,
        "confidence": "LOW",
        "is_fallback": True
    }


def analyze_with_deepseek(
    client,
    model,
    price_data,
    trade_config,
    signal_history,
    get_current_position_fn,
    safe_json_parse_fn,
    create_fallback_signal_fn,
    save_trade_log_fn,
    max_kline=5,
    temperature=0.1
):
    """通用 DeepSeek 分析器。

    参数:
    - client: DeepSeek/OpenAI 客户端
    - model: 模型名称字符串
    - price_data: 来自 get_ohlcv_enhanced 的 price_data dict
    - trade_config: TRADE_CONFIG dict
    - signal_history: 全局 signal_history 列表（会被追加）
    - get_current_position_fn: 无参数函数，返回当前持仓
    - safe_json_parse_fn: 函数，用于安全解析 JSON
    - create_fallback_signal_fn: 函数，用于生成回退信号
    - save_trade_log_fn: 函数，用于保存日志（脚本层的 wrapper）

    返回 (signal_data, raw_response)
    """
    # 生成技术分析文本（复用 common.generate_technical_analysis_text）
    technical_analysis = generate_technical_analysis_text(price_data)

    # 构建K线数据文本
    kline_text = f"【最近{max_kline}根{trade_config['timeframe']}K线数据】\n"
    for i, kline in enumerate(price_data.get('kline_data', [])[-max_kline:]):
        trend = "阳线" if kline['close'] > kline['open'] else "阴线"
        try:
            change = ((kline['close'] - kline['open']) / kline['open']) * 100
        except Exception:
            change = 0
        kline_text += f"K线{i + 1}: {trend} 开盘:{kline['open']:.5f} 收盘:{kline['close']:.5f} 涨跌:{change:+.5f}%\n"

    # 添加上次交易信号
    signal_text = ""
    if signal_history:
        last_signal = signal_history[-1]
        signal_text = f"\n【上次交易信号】\n信号: {last_signal.get('signal', 'N/A')}\n信心: {last_signal.get('confidence', 'N/A')}"

    # 添加当前持仓信息
    current_pos = get_current_position_fn()
    position_text = "无持仓" if not current_pos else f"{current_pos['side']}仓, 数量: {current_pos['size']}, 盈亏: {current_pos.get('unrealized_pnl',0):.5f}USDT"

    prompt = f"""
    你是一个专业的加密货币交易分析师。请基于以下{trade_config['symbol']} {trade_config['timeframe']}周期数据进行分析：

    {kline_text}

    {technical_analysis}

    {signal_text}

    【当前行情】
    - 当前价格: ${price_data['price']:,.5f}
    - 时间: {price_data['timestamp']}
    - 本K线最高: ${price_data.get('high',0):,.5f}
    - 本K线最低: ${price_data.get('low',0):,.5f}
    - 本K线成交量: {price_data.get('volume',0):.5f}
    - 价格变化: {price_data.get('price_change',0):+.5f}%
    - 当前持仓: {position_text}

    【分析要求】
    1. 基于{trade_config['timeframe']}K线趋势和技术指标给出交易信号: BUY(买入) / SELL(卖出) / HOLD(观望)
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
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": f"您是一位专业的交易员，专注于{trade_config['timeframe']}周期趋势分析。请结合K线形态和技术指标做出判断，并严格遵循JSON格式要求。"},
                {"role": "user", "content": prompt}
            ],
            stream=False,
            temperature=temperature
        )

        raw = response.choices[0].message.content
        # 提取JSON部分
        start_idx = raw.find('{')
        end_idx = raw.rfind('}') + 1

        if start_idx != -1 and end_idx != 0:
            json_str = raw[start_idx:end_idx]
            signal_data = safe_json_parse_fn(json_str)
            if signal_data is None:
                signal_data = create_fallback_signal_fn(price_data)
        else:
            signal_data = create_fallback_signal_fn(price_data)

        # 验证必需字段
        required_fields = ['signal', 'reason', 'stop_loss', 'take_profit', 'confidence']
        if not all(field in signal_data for field in required_fields):
            signal_data = create_fallback_signal_fn(price_data)

        # 附加时间戳并保存历史
        signal_data['timestamp'] = price_data.get('timestamp')
        signal_history.append(signal_data)
        if len(signal_history) > 30:
            signal_history.pop(0)

        # 保存原始回复与信号到日志（调用脚本层的 save_trade_log wrapper）
        try:
            save_trade_log_fn(price_data, raw, signal_data, get_current_position_fn())
        except Exception:
            # 不应阻塞主逻辑
            pass

        return signal_data, raw

    except Exception as e:
        print(f"DeepSeek 分析调用失败: {e}")
        return create_fallback_signal_fn(price_data), None


# 新增通用 execute_trade 函数，供多个脚本复用
def execute_trade(
    exchange,
    trade_config,
    signal_data,
    price_data,
    get_current_position_fn,
    save_trade_log_fn,
    deepseek_raw=None,
    settings_module=None
):
    """通用交易执行函数（支持 OKX 类似接口）。

    参数:
    - exchange: ccxt 交易所实例
    - trade_config: 脚本的 TRADE_CONFIG dict
    - signal_data: 来自 analyze_with_deepseek 的信号 dict
    - price_data: 来自 get_ohlcv_enhanced 的 price_data dict
    - get_current_position_fn: 无参函数，返回当前持仓
    - save_trade_log_fn: 无参 wrapper，用于保存日志，签名与脚本中 save_trade_log 保持一致
    - deepseek_raw: 可选，DeepSeek 的原始回复文本（用于记录）
    - settings_module: 可选，脚本的 settings 模块（用于读取 BROKER_TAG 等配置）

    返回: updated_position 或 None
    """
    try:
        current_position = get_current_position_fn()

        print(f"交易信号: {signal_data.get('signal')}")
        print(f"信心程度: {signal_data.get('confidence')}")
        print(f"理由: {signal_data.get('reason')}")
        try:
            print(f"止损: ${signal_data.get('stop_loss'):, .5f}")
            print(f"止盈: ${signal_data.get('take_profit'):, .5f}")
        except Exception:
            pass
        print(f"当前持仓: {current_position}")

        # 风险管理：低信心信号不执行
        if signal_data.get('confidence') == 'LOW' and not trade_config.get('test_mode'):
            print("⚠️ 低信心信号，跳过执行")
            try:
                save_trade_log_fn(price_data, deepseek_raw, signal_data, current_position, "skip", order_status="skipped")
            except Exception:
                pass
            return None

        if trade_config.get('test_mode'):
            print("测试模式 - 仅模拟交易")
            try:
                save_trade_log_fn(price_data, deepseek_raw, signal_data, current_position, operation_type='test_mode', order_status='test')
            except Exception:
                pass
            return None

        # 获取账户余额
        balance = exchange.fetch_balance()
        usdt_balance = None
        try:
            usdt_balance = balance['USDT']['free']
        except Exception:
            # 尝试不同键名
            usdt_balance = balance.get('free', {}).get('USDT') if isinstance(balance.get('free'), dict) else None

        # 智能保证金检查
        required_margin = 0
        operation_type = None
        signal = signal_data.get('signal')

        price = price_data.get('price', 0)
        amount = trade_config.get('amount', 0)
        leverage = trade_config.get('leverage', 1)

        if signal == 'BUY':
            if current_position and current_position.get('side') == 'short':
                required_margin = price * amount / leverage
                operation_type = "平空开多"
            elif not current_position:
                required_margin = price * amount / leverage
                operation_type = "开多仓"
            else:
                required_margin = 0
                operation_type = "保持多仓"

        elif signal == 'SELL':
            if current_position and current_position.get('side') == 'long':
                required_margin = price * amount / leverage
                operation_type = "平多开空"
            elif not current_position:
                required_margin = price * amount / leverage
                operation_type = "开空仓"
            else:
                required_margin = 0
                operation_type = "保持空仓"

        elif signal == 'HOLD':
            print("建议观望，不执行交易")
            try:
                save_trade_log_fn(price_data, deepseek_raw, signal_data, current_position, operation_type='hold', order_status='held')
            except Exception:
                pass
            return None

        print(f"操作类型: {operation_type}, 需要保证金: {required_margin:.5f} USDT")

        # 记录执行前的快照日志
        try:
            save_trade_log_fn(price_data, deepseek_raw, signal_data, current_position, operation_type=operation_type, required_margin=required_margin, order_status='precheck')
        except Exception:
            pass

        # 只有在需要额外保证金时才检查
        if required_margin > 0 and usdt_balance is not None:
            if required_margin > usdt_balance * 0.8:
                print(f"⚠️ 保证金不足，跳过交易。需要: {required_margin:.5f} USDT, 可用: {usdt_balance:.5f} USDT")
                try:
                    save_trade_log_fn(price_data, deepseek_raw, signal_data, current_position, "skip", order_status="skipped")
                except Exception:
                    pass
                return None
        else:
            print("✅ 无需额外保证金，继续执行")

        # 执行交易
        tag_param = {}
        if settings_module and hasattr(settings_module, 'BROKER_TAG'):
            tag_param['tag'] = getattr(settings_module, 'BROKER_TAG')

        # 下单逻辑
        try:
            if signal == 'BUY':
                if current_position and current_position.get('side') == 'short':
                    print("平空仓并开多仓...")
                    exchange.create_market_order(trade_config['symbol'], 'buy', current_position.get('size'), params={**{'reduceOnly': True}, **tag_param})
                    time.sleep(1)
                    exchange.create_market_order(trade_config['symbol'], 'buy', amount, params=tag_param)
                elif current_position and current_position.get('side') == 'long':
                    print("已有多头持仓，保持现状")
                else:
                    print("开多仓...")
                    params = {**tag_param, 'takeProfit': {'triggerPrice': signal_data.get('take_profit'), 'price': signal_data.get('take_profit'), 'reduceOnly': True}, 'stopLoss': {'triggerPrice': signal_data.get('stop_loss'), 'price': signal_data.get('stop_loss'), 'reduceOnly': True}}
                    exchange.create_market_order(trade_config['symbol'], 'buy', amount, params=params)

            elif signal == 'SELL':
                if current_position and current_position.get('side') == 'long':
                    print("平多仓并开空仓...")
                    exchange.create_market_order(trade_config['symbol'], 'sell', current_position.get('size'), params={**{'reduceOnly': True}, **tag_param})
                    time.sleep(1)
                    exchange.create_market_order(trade_config['symbol'], 'sell', amount, params=tag_param)
                elif current_position and current_position.get('side') == 'short':
                    exchange.create_market_order(trade_config['symbol'], 'buy', current_position.get('size'), params={**{'reduceOnly': True}, **tag_param})
                    print("空头持仓已平仓")
                else:
                    print("开空仓...")
                    params = {**tag_param, 'takeProfit': {'triggerPrice': signal_data.get('take_profit'), 'price': signal_data.get('take_profit'), 'reduceOnly': True}, 'stopLoss': {'triggerPrice': signal_data.get('stop_loss'), 'price': signal_data.get('stop_loss'), 'reduceOnly': True}}
                    exchange.create_market_order(trade_config['symbol'], 'sell', amount, params=params)

            print("订单执行成功")
            time.sleep(2)
            updated_position = get_current_position_fn()
            print(f"更新后持仓: {updated_position}")

            # 保存交易日志
            try:
                save_trade_log_fn(price_data, deepseek_raw, signal_data, current_position, operation_type, required_margin, "success", updated_position, extra={"order_id": "", "fee": 0})
            except Exception:
                pass

            return updated_position

        except Exception as e:
            print(f"下单过程中发生错误: {e}")
            import traceback
            traceback.print_exc()
            try:
                save_trade_log_fn(price_data, deepseek_raw, signal_data, current_position, operation_type, required_margin, "failed")
            except Exception:
                pass
            return None

    except Exception as e:
        print(f"执行交易失败: {e}")
        import traceback
        traceback.print_exc()
        return None

