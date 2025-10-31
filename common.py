import json
import re
from datetime import datetime
import sqlite3
import pandas as pd


def init_db(db_path):
    """Initialize the SQLite database and create table if not exists."""
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute('''
            CREATE TABLE IF NOT EXISTS trade_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT,
                symbol TEXT,
                timeframe TEXT,
                price REAL,
                price_change REAL,
                deepseek_raw TEXT,
                signal TEXT,
                reason TEXT,
                stop_loss REAL,
                take_profit REAL,
                confidence TEXT,
                current_position TEXT,
                operation_type TEXT,
                required_margin REAL,
                order_status TEXT,
                updated_position TEXT,
                extra TEXT
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
        stop_loss = float(signal_data.get('stop_loss')) if signal_data and signal_data.get('stop_loss') is not None else None
        take_profit = float(signal_data.get('take_profit')) if signal_data and signal_data.get('take_profit') is not None else None
        confidence = signal_data.get('confidence') if signal_data else None

        cur.execute('''
            INSERT INTO trade_logs (
                created_at, symbol, timeframe, price, price_change, deepseek_raw, signal, reason, stop_loss, take_profit, confidence,
                current_position, operation_type, required_margin, order_status, updated_position, extra
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        ohlcv = exchange.fetch_ohlcv(trade_config['symbol'], trade_config['timeframe'], limit=trade_config['data_points'])
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
    """返回到下一个 period_minutes 分钟整点需要等待的秒数。

    规则与原脚本一致：如果当前已接近整点（分钟模 period 为 0 且秒数 < 10），
    则立即返回 0 以便立刻执行。
    """
    try:
        now = datetime.now()
        current_minute = now.minute
        current_second = now.second

        remainder = current_minute % period_minutes
        if remainder == 0 and current_second < 10:
            return 0

        minutes_to_wait = period_minutes - remainder
        seconds_to_wait = minutes_to_wait * 60 - current_second

        print(f"🕒 等待 {minutes_to_wait} 分 {60 - current_second} 秒到整点...")
        return seconds_to_wait
    except Exception as e:
        # 在任何意外情况下，返回一个较短的回退等待时间，避免阻塞
        print(f"计算等待时间失败: {e}")
        return 5


def create_fallback_signal(price_data):
    return {
        "signal": "HOLD",
        "reason": "因技术分析暂时不可用，采取保守策略",
        "stop_loss": price_data['price'] * 0.98,
        "take_profit": price_data['price'] * 1.02,
        "confidence": "LOW",
        "is_fallback": True
    }
