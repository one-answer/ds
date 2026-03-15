import argparse
import json
import os
import time
from datetime import datetime

import ccxt
from dotenv import load_dotenv

import common
import settings
from backtest_service import Candle, STRATEGIES


def _parse_timeframe_minutes(tf: str) -> int:
    tf = str(tf or "").strip()
    if tf.endswith("m"):
        return int(tf[:-1])
    if tf.endswith("H") or tf.endswith("h"):
        return int(tf[:-1]) * 60
    if tf.endswith("D") or tf.endswith("d"):
        return int(tf[:-1]) * 1440
    if tf == "1M":
        return 43200
    raise ValueError(f"unsupported timeframe: {tf}")


def _wait_for_next_period(minutes: int) -> None:
    period_seconds = max(60, int(minutes) * 60)
    now = time.time()
    wait = period_seconds - (now % period_seconds)
    if wait < 1:
        wait += period_seconds
    print(f"🕒 等待 {int(wait)} 秒到下一根K线...")
    time.sleep(wait)


def _fetch_candles(exchange, symbol: str, timeframe: str, limit: int) -> list[Candle]:
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
    candles: list[Candle] = []
    for row in ohlcv or []:
        candles.append(
            Candle(
                ts_ms=int(row[0]),
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]),
            )
        )
    return candles


def _get_proxies() -> dict:
    proxy = (
        os.getenv("HTTPS_PROXY")
        or os.getenv("https_proxy")
        or os.getenv("HTTP_PROXY")
        or os.getenv("http_proxy")
    )
    if proxy:
        return {"http": proxy, "https": proxy}
    return {}


def _build_exchange():
    exchange = ccxt.okx(
        {
            "enableRateLimit": True,
            "timeout": 30000,
            "options": {"defaultType": settings.DEFAULT_TYPE},
            "apiKey": os.getenv("OKX_API_KEY"),
            "secret": os.getenv("OKX_SECRET"),
            "password": os.getenv("OKX_PASSWORD"),
        }
    )
    api_base = os.getenv("OKX_API_BASE")
    if api_base:
        exchange.urls["api"] = {"public": api_base, "private": api_base}
    proxies = _get_proxies()
    if proxies:
        exchange.proxies = proxies
    return exchange


def _build_signal_data(signal: str, price: float, params: dict, reason: str) -> dict:
    sl_pct = float(params.get("stop_loss_pct") or 1.0)
    tp_pct = float(params.get("take_profit_pct") or 2.0)
    if signal == "BUY":
        stop_loss = price * (1.0 - sl_pct / 100.0)
        take_profit = price * (1.0 + tp_pct / 100.0)
    elif signal == "SELL":
        stop_loss = price * (1.0 + sl_pct / 100.0)
        take_profit = price * (1.0 - tp_pct / 100.0)
    else:
        stop_loss = price * (1.0 - sl_pct / 100.0)
        take_profit = price * (1.0 + tp_pct / 100.0)

    return {
        "signal": signal,
        "reason": reason,
        "stop_loss": float(stop_loss),
        "take_profit": float(take_profit),
        "confidence": "MEDIUM",
    }


def run(strategy_id: str, symbol: str, timeframe: str, amount: float, leverage: float, params_text=None) -> None:
    load_dotenv()

    if strategy_id not in STRATEGIES:
        raise ValueError(f"unknown strategy: {strategy_id}")

    meta = STRATEGIES[strategy_id]
    fn = meta["fn"]
    params = dict(meta.get("defaults") or {})
    if params_text:
        try:
            override = json.loads(params_text)
            if isinstance(override, dict):
                params.update(override)
        except Exception:
            pass

    trade_config = {
        "symbol": symbol,
        "timeframe": timeframe,
        "amount": float(amount),
        "leverage": float(leverage),
        "test_mode": settings.TRADE_TEST_MODE,
    }

    exchange = _build_exchange()

    db_path = os.path.join(os.path.dirname(__file__), "trading_logs.db")
    common.init_db(db_path)

    def save_trade_log(*args, **kwargs):
        return common.save_trade_log(db_path, trade_config, *args, **kwargs)

    def get_current_position():
        return common.get_current_position(exchange, symbol, trade_config["leverage"])

    try:
        exchange.set_leverage(trade_config["leverage"], trade_config["symbol"], {"mgnMode": settings.MARGIN_MODE})
    except Exception as exc:
        print(f"设置杠杆失败: {exc}")

    print(f"{symbol} 策略交易启动: {strategy_id}")
    if trade_config["test_mode"]:
        print("当前为模拟模式，不会真实下单")
    else:
        print("实盘交易模式，请谨慎操作！")
    print(f"交易周期: {trade_config['timeframe']}")

    tf_minutes = _parse_timeframe_minutes(timeframe)

    while True:
        _wait_for_next_period(tf_minutes)
        print("\n" + "=" * 60)
        print(f"执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)

        try:
            candles = _fetch_candles(exchange, symbol, timeframe, limit=max(120, int(params.get("slow", 80)) + 10))
        except ccxt.NetworkError as exc:
            print(f"网络异常: {exc}")
            time.sleep(30)
            continue
        except Exception as exc:
            print(f"获取K线失败: {exc}")
            time.sleep(30)
            continue
        if len(candles) < 10:
            time.sleep(30)
            continue

        price = candles[-1].close
        prev = candles[-2].close if len(candles) >= 2 else price
        price_change = ((price - prev) / prev) * 100 if prev else 0.0
        price_data = {"price": price, "price_change": price_change, "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

        current_position = get_current_position()
        if current_position and current_position.get("side") == "long":
            pos = 1
        elif current_position and current_position.get("side") == "short":
            pos = -1
        else:
            pos = 0

        idx = max(0, len(candles) - 2)
        desired = fn(idx, candles, params, pos)
        if desired not in (-1, 0, 1):
            desired = 0

        if desired == 1 and pos != 1:
            signal = "BUY"
        elif desired == -1 and pos != -1:
            signal = "SELL"
        elif desired == 0 and pos != 0:
            signal = "CLOSE"
        else:
            signal = "HOLD"

        reason = f"strategy={strategy_id} desired={desired} pos={pos}"
        signal_data = _build_signal_data(signal, price, params, reason)

        common.execute_trade(
            exchange=exchange,
            trade_config=trade_config,
            signal_data=signal_data,
            price_data=price_data,
            get_current_position_fn=get_current_position,
            save_trade_log_fn=save_trade_log,
            deepseek_raw=None,
            settings_module=settings,
        )

        time.sleep(5)


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Rule-based strategy runner")
    parser.add_argument("--strategy-id", required=True, help="Backtest strategy id")
    parser.add_argument("--symbol", required=True, help="Symbol, e.g. BTC/USDT:USDT")
    parser.add_argument("--timeframe", default=os.getenv("RULE_TRADE_TIMEFRAME", "15m"))
    parser.add_argument("--amount", type=float, default=float(os.getenv("RULE_TRADE_AMOUNT", "1")))
    parser.add_argument("--leverage", type=float, default=float(os.getenv("RULE_TRADE_LEVERAGE", "1")))
    parser.add_argument("--params", default=os.getenv("RULE_TRADE_PARAMS"))
    args = parser.parse_args(argv)
    run(args.strategy_id, args.symbol, args.timeframe, args.amount, args.leverage, args.params)


if __name__ == "__main__":
    main()
