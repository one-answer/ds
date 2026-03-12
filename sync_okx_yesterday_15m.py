import argparse
import os
import time as pytime
import sys
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pymysql
import requests
from dotenv import load_dotenv


def parse_args():
    parser = argparse.ArgumentParser(description="Fetch yesterday 15m OHLCV from OKX and save to MySQL")
    parser.add_argument(
        "--symbol",
        default="XRP/USDT:USDT",
        help="OKX symbol, e.g. XRP/USDT:USDT or DOGE/USDT:USDT",
    )
    parser.add_argument("--timeframe", default="15m", choices=["15m"], help="K-line timeframe")
    parser.add_argument("--tz", default="Asia/Shanghai", help="Natural-day timezone for 'yesterday'")
    return parser.parse_args()


def get_mysql_config():
    cfg = {
        "host": os.getenv("MYSQL_HOST"),
        "port": os.getenv("MYSQL_PORT"),
        "user": os.getenv("MYSQL_USERNAME"),
        "password": os.getenv("MYSQL_PASSWORD"),
        "database": os.getenv("MYSQL_DB"),
    }
    missing = [k for k, v in cfg.items() if not v]
    if missing:
        raise RuntimeError(f"Missing MySQL env vars: {', '.join(missing)}")

    try:
        cfg["port"] = int(cfg["port"])
    except ValueError as exc:
        raise RuntimeError("MYSQL_PORT must be an integer") from exc

    return cfg


def mysql_connect(cfg):
    kwargs = {
        "host": cfg["host"],
        "port": cfg["port"],
        "user": cfg["user"],
        "password": cfg["password"],
        "database": cfg["database"],
        "charset": "utf8mb4",
        "autocommit": False,
        "cursorclass": pymysql.cursors.DictCursor,
    }
    if os.getenv("MYSQL_SSL_DISABLED", "0") != "1":
        kwargs["ssl"] = {"ssl": {}}
    return pymysql.connect(**kwargs)


def ensure_table(conn):
    sql = """
    CREATE TABLE IF NOT EXISTS okx_kline_15m (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        symbol VARCHAR(64) NOT NULL,
        timeframe VARCHAR(16) NOT NULL,
        open_time_ms BIGINT NOT NULL,
        open_time_utc DATETIME NOT NULL,
        open_price DOUBLE,
        high_price DOUBLE,
        low_price DOUBLE,
        close_price DOUBLE,
        volume DOUBLE,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uq_symbol_tf_open (symbol, timeframe, open_time_ms),
        INDEX idx_open_time (open_time_ms)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()


def build_yesterday_window(tz_name):
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        print(f"Invalid timezone '{tz_name}', fallback to UTC")
        tz = timezone.utc

    now_local = datetime.now(tz)
    yesterday = now_local.date() - timedelta(days=1)
    start_local = datetime.combine(yesterday, time.min, tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    return int(start_local.timestamp() * 1000), int(end_local.timestamp() * 1000), str(yesterday)


def _ccxt_symbol_to_inst_id(symbol: str) -> str:
    """Convert ccxt symbol to OKX instId.
    XRP/USDT:USDT -> XRP-USDT-SWAP  (perpetual swap)
    DOGE/USDT:USDT -> DOGE-USDT-SWAP
    XRP/USDT       -> XRP-USDT       (spot)
    """
    if ":" in symbol:
        base_quote = symbol.split(":")[0]
        base, quote = base_quote.split("/")
        return f"{base}-{quote}-SWAP"
    base, quote = symbol.split("/")
    return f"{base}-{quote}"


def _get_proxies() -> dict:
    """Return proxy dict from env vars or macOS system proxy."""
    proxy = (
        os.getenv("HTTPS_PROXY")
        or os.getenv("https_proxy")
        or os.getenv("HTTP_PROXY")
        or os.getenv("http_proxy")
    )
    if not proxy:
        # Auto-detect macOS system proxy via scutil
        try:
            import subprocess, re
            out = subprocess.check_output(["scutil", "--proxy"], text=True, timeout=3)
            host_m = re.search(r"HTTPSProxy\s*:\s*(\S+)", out)
            port_m = re.search(r"HTTPSPort\s*:\s*(\d+)", out)
            en_m = re.search(r"HTTPSEnable\s*:\s*(\d+)", out)
            if host_m and port_m and en_m and en_m.group(1) == "1":
                proxy = f"http://{host_m.group(1)}:{port_m.group(1)}"
        except Exception:
            pass
    if proxy:
        return {"http": proxy, "https": proxy}
    return {}


def fetch_okx_ohlcv(symbol, timeframe, start_ms, end_ms):
    """Fetch OHLCV candles from OKX REST API directly (no ccxt load_markets)."""
    inst_id = _ccxt_symbol_to_inst_id(symbol)
    url = "https://www.okx.com/api/v5/market/history-candles"
    proxies = _get_proxies()

    # OKX history-candles pagination:
    # `after=X`  → returns bars OLDER than X (ts < X), newest-first within result
    # `before=X` → returns bars NEWER than X (ts > X)
    # We want yesterday: start_ms <= ts < end_ms
    # Use after=end_ms to get bars older than end_ms, then keep ts >= start_ms.
    params = {
        "instId": inst_id,
        "bar": timeframe,
        "after": str(end_ms),
        "limit": "100",
    }

    retries = 3
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, params=params, timeout=20, proxies=proxies or None)
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") != "0":
                raise RuntimeError(f"OKX API error code={data.get('code')}: {data.get('msg', '')}")
            candles = data.get("data", [])
            # Each row: [ts_ms, o, h, l, c, vol, volCcy, volCcyQuote, confirm]
            rows = []
            for row in candles:
                ts_ms = int(row[0])
                if start_ms <= ts_ms < end_ms:
                    rows.append([ts_ms, float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5])])
            return rows
        except (requests.RequestException, RuntimeError) as exc:
            if attempt == retries:
                raise
            print(f"OKX request retry {attempt}/{retries}: {exc}")
            pytime.sleep(2)

    return []


def upsert_rows(conn, symbol, timeframe, rows):
    if not rows:
        return 0

    sql = """
    INSERT INTO okx_kline_15m (
        symbol, timeframe, open_time_ms, open_time_utc,
        open_price, high_price, low_price, close_price, volume
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
        open_price = VALUES(open_price),
        high_price = VALUES(high_price),
        low_price = VALUES(low_price),
        close_price = VALUES(close_price),
        volume = VALUES(volume),
        updated_at = CURRENT_TIMESTAMP
    """

    payload = []
    for ts_ms, o, h, l, c, v in rows:
        open_time_utc = datetime.fromtimestamp(int(ts_ms) / 1000, tz=timezone.utc).replace(tzinfo=None)
        payload.append((symbol, timeframe, int(ts_ms), open_time_utc, float(o), float(h), float(l), float(c), float(v)))

    with conn.cursor() as cur:
        affected = cur.executemany(sql, payload)
    conn.commit()
    return affected


def main():
    load_dotenv(dotenv_path=".env")
    args = parse_args()

    mysql_cfg = get_mysql_config()
    start_ms, end_ms, day_label = build_yesterday_window(args.tz)

    conn = mysql_connect(mysql_cfg)
    try:
        ensure_table(conn)
        print(f"MySQL table ready: {mysql_cfg['database']}.okx_kline_15m")

        print(f"Fetching OKX {args.symbol} {args.timeframe} for yesterday={day_label}, window_ms=[{start_ms}, {end_ms})")
        try:
            rows = fetch_okx_ohlcv(args.symbol, args.timeframe, start_ms, end_ms)
        except (requests.RequestException, RuntimeError) as exc:
            print(f"Fetch failed after retries: {exc}")
            return 2
        print(f"Fetched {len(rows)} rows from OKX")

        affected = upsert_rows(conn, args.symbol, args.timeframe, rows)
    finally:
        conn.close()

    print(f"Upsert finished. MySQL affected rows: {affected}")
    return 0


if __name__ == "__main__":
    sys.exit(main())




