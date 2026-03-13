import argparse
import os
import time
from datetime import datetime

import ccxt
from dotenv import load_dotenv
from openai import OpenAI

import common
import settings


def _build_trade_config(strategy: str) -> dict:
    base = {
        "leverage": 5,
        "timeframe": "15m",
        # Strategy scripts read this from settings.TRADE_TEST_MODE (env var override handled there).
        "test_mode": settings.TRADE_TEST_MODE,
        # 24h data (96x 15m candles)
        "data_points": 96,
        "analysis_periods": {"short_term": 20, "medium_term": 50, "long_term": 96},
    }

    per_strategy = {
        "doge": {"symbol": "DOGE/USDT:USDT", "amount": 6},
        "xrp": {"symbol": "XRP/USDT:USDT", "amount": 4},
    }

    key = (strategy or "").strip().lower()
    if key not in per_strategy:
        raise ValueError(f"Unknown strategy: {strategy!r} (expected: doge|xrp)")

    return {**base, **per_strategy[key]}


def _setup_exchange(exchange, trade_config: dict) -> bool:
    try:
        exchange.set_leverage(
            trade_config["leverage"],
            trade_config["symbol"],
            {"mgnMode": settings.MARGIN_MODE},
        )
        print(f"设置杠杆倍数: {trade_config['leverage']}x, mgnMode={settings.MARGIN_MODE}")

        balance = exchange.fetch_balance()
        usdt_balance = balance["USDT"]["free"]
        print(f"当前USDT余额: {usdt_balance:.5f}")
        return True
    except Exception as exc:
        print(f"交易所设置失败: {exc}")
        return False


def run(strategy: str) -> None:
    load_dotenv()

    trade_config = _build_trade_config(strategy)
    symbol = trade_config["symbol"]

    deepseek_client = OpenAI(
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url="https://api.deepseek.com",
    )

    exchange = ccxt.okx(
        {
            "options": {"defaultType": settings.DEFAULT_TYPE},
            "apiKey": os.getenv("OKX_API_KEY"),
            "secret": os.getenv("OKX_SECRET"),
            "password": os.getenv("OKX_PASSWORD"),
        }
    )

    db_path = os.path.join(os.path.dirname(__file__), "trading_logs.db")
    common.init_db(db_path)

    signal_history = []
    position = None
    deepseek_last_raw = None

    def save_trade_log(
        price_data=None,
        deepseek_raw=None,
        signal_data=None,
        current_position=None,
        operation_type=None,
        required_margin=None,
        order_status=None,
        updated_position=None,
        extra=None,
    ):
        return common.save_trade_log(
            db_path,
            trade_config,
            price_data,
            deepseek_raw,
            signal_data,
            current_position,
            operation_type,
            required_margin,
            order_status,
            updated_position,
            extra,
        )

    def get_current_position():
        return common.get_current_position(exchange, symbol, trade_config["leverage"])

    def analyze_with_deepseek(price_data):
        nonlocal deepseek_last_raw
        try:
            signal_data, raw = common.analyze_with_deepseek(
                deepseek_client,
                settings.DEEPSEEK_MODEL,
                price_data,
                trade_config,
                signal_history,
                get_current_position,
                common.safe_json_parse,
                common.create_fallback_signal,
                save_trade_log,
                max_kline=5,
                temperature=0.1,
            )
            if raw:
                deepseek_last_raw = raw
            return signal_data
        except Exception as exc:
            print(f"调用通用 DeepSeek 分析失败: {exc}")
            return common.create_fallback_signal(price_data)

    def analyze_with_retry(price_data, max_retries=2):
        for attempt in range(max_retries):
            try:
                signal_data = analyze_with_deepseek(price_data)
                if signal_data and not signal_data.get("is_fallback", False):
                    return signal_data
                print(f"第{attempt + 1}次尝试失败，进行重试...")
                time.sleep(1)
            except Exception as exc:
                print(f"第{attempt + 1}次尝试异常: {exc}")
                if attempt == max_retries - 1:
                    return common.create_fallback_signal(price_data)
                time.sleep(1)
        return common.create_fallback_signal(price_data)

    def execute_trade(signal_data, price_data):
        nonlocal position
        updated = common.execute_trade(
            exchange=exchange,
            trade_config=trade_config,
            signal_data=signal_data,
            price_data=price_data,
            get_current_position_fn=get_current_position,
            save_trade_log_fn=save_trade_log,
            deepseek_raw=deepseek_last_raw,
            settings_module=settings,
        )
        if updated is not None:
            position = updated
        return updated

    print(f"{symbol} OKX自动交易机器人启动成功！")
    print("融合技术指标策略 + OKX实盘接口")
    if trade_config["test_mode"]:
        print("当前为模拟模式，不会真实下单")
    else:
        print("实盘交易模式，请谨慎操作！")
    print(f"交易周期: {trade_config['timeframe']}")
    print("已启用完整技术指标分析和持仓跟踪功能")

    if not _setup_exchange(exchange, trade_config):
        print("交易所初始化失败，程序退出")
        return

    while True:
        wait_seconds = common.wait_for_next_period(15)
        if wait_seconds > 0:
            time.sleep(wait_seconds)

        print("\n" + "=" * 60)
        print(f"执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)

        price_data = common.get_ohlcv_enhanced(exchange, trade_config)
        if not price_data:
            time.sleep(60)
            continue

        print(f"{symbol.split('/')[0]}当前价格: ${price_data['price']:,.5f}")
        print(f"数据周期: {trade_config['timeframe']}")
        print(f"价格变化: {price_data['price_change']:+.5f}%")

        signal_data = analyze_with_retry(price_data)
        if signal_data.get("is_fallback", False):
            print("⚠️ 使用备用交易信号")

        execute_trade(signal_data, price_data)
        time.sleep(60)


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Unified DeepSeek OKX trading bot runner")
    parser.add_argument("--strategy", required=True, help="Strategy key: doge|xrp")
    args = parser.parse_args(argv)
    run(args.strategy)


if __name__ == "__main__":
    main()

