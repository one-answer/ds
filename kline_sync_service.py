import os
import time as pytime
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional, Union
from zoneinfo import ZoneInfo

import pymysql
import requests

STORAGE_TZ_NAME = "Asia/Shanghai"
STORAGE_TZ = ZoneInfo(STORAGE_TZ_NAME)

TIMEFRAME_ALIASES = {
    "5m": "5m",
    "15m": "15m",
    "1h": "1H",
    "1H": "1H",
    "1d": "1D",
    "1D": "1D",
    "1m": "1M",
    "1M": "1M",
}

DAY_TIMEFRAMES = {"5m", "15m", "1H"}
RANGE_TIMEFRAMES = {"1D", "1M"}


def normalize_timeframe(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    return TIMEFRAME_ALIASES.get(str(value).strip())


def parse_iso_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _resolve_tz(tz_name: str) -> Union[timezone, ZoneInfo]:
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return timezone.utc


def _day_window(day_text: str, tz_name: str) -> tuple[int, int]:
    day = parse_iso_date(day_text)
    tz = _resolve_tz(tz_name)
    start_local = datetime.combine(day, time.min, tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    return int(start_local.timestamp() * 1000), int(end_local.timestamp() * 1000)


def build_range_window(start_text: str, end_text: str, timeframe: str, tz_name: str) -> tuple[int, int]:
    start_day = parse_iso_date(start_text)
    end_day = parse_iso_date(end_text)
    if end_day < start_day:
        raise ValueError("end_date must be greater than or equal to start_date")

    tz = _resolve_tz(tz_name)
    if timeframe == "1M":
        start_month = date(start_day.year, start_day.month, 1)
        if end_day.month == 12:
            end_exclusive = date(end_day.year + 1, 1, 1)
        else:
            end_exclusive = date(end_day.year, end_day.month + 1, 1)
        start_local = datetime.combine(start_month, time.min, tzinfo=tz)
        end_local = datetime.combine(end_exclusive, time.min, tzinfo=tz)
    else:
        start_local = datetime.combine(start_day, time.min, tzinfo=tz)
        end_local = datetime.combine(end_day + timedelta(days=1), time.min, tzinfo=tz)

    return int(start_local.timestamp() * 1000), int(end_local.timestamp() * 1000)


def get_mysql_config() -> dict:
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
        port = int(str(cfg["port"]))
    except ValueError as exc:
        raise RuntimeError("MYSQL_PORT must be an integer") from exc

    return {
        "host": cfg["host"],
        "port": port,
        "user": cfg["user"],
        "password": cfg["password"],
        "database": cfg["database"],
    }


def mysql_connect(cfg: dict):
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


def ensure_kline_triggers(conn, table: str = "okx_kline") -> None:
    """
    Ensure DB-side timestamps are Shanghai local time regardless of MySQL server/session time_zone.

    We do this via triggers using UTC_TIMESTAMP()+8 hours so it doesn't depend on time zone tables.
    """
    trigger_insert = f"{table}_bi_shanghai_ts"
    trigger_update = f"{table}_bu_shanghai_ts"

    existing = set()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT trigger_name
                FROM information_schema.triggers
                WHERE trigger_schema = DATABASE()
                  AND trigger_name IN (%s, %s)
                """,
                (trigger_insert, trigger_update),
            )
            existing = {str(r.get("trigger_name")) for r in (cur.fetchall() or []) if r.get("trigger_name")}
    except Exception:
        return

    utc_plus_8 = "DATE_ADD(UTC_TIMESTAMP(), INTERVAL 8 HOUR)"

    if trigger_insert not in existing:
        sql = (
            f"CREATE TRIGGER `{trigger_insert}` BEFORE INSERT ON `{table}` "
            f"FOR EACH ROW SET "
            f"NEW.created_at = COALESCE(NEW.created_at, {utc_plus_8}), "
            f"NEW.updated_at = COALESCE(NEW.updated_at, {utc_plus_8})"
        )
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
            conn.commit()
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            print(f"[warn] cannot create trigger {trigger_insert}: {exc}")

    if trigger_update not in existing:
        sql = (
            f"CREATE TRIGGER `{trigger_update}` BEFORE UPDATE ON `{table}` "
            f"FOR EACH ROW SET NEW.updated_at = {utc_plus_8}"
        )
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
            conn.commit()
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            print(f"[warn] cannot create trigger {trigger_update}: {exc}")


def ensure_table(conn) -> None:
    sql = """
    CREATE TABLE IF NOT EXISTS okx_kline (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        symbol VARCHAR(64) NOT NULL,
        timeframe VARCHAR(16) NOT NULL,
        open_time_ms BIGINT NOT NULL,
        open_time_shanghai DATETIME NOT NULL COMMENT 'Asia/Shanghai local time (UTC+8)',
        open_price DOUBLE,
        high_price DOUBLE,
        low_price DOUBLE,
        close_price DOUBLE,
        volume DOUBLE,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uq_symbol_tf_open (symbol, timeframe, open_time_ms),
        INDEX idx_symbol_tf_time (symbol, timeframe, open_time_ms)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()

    # Backward compatible: if an older table still uses `open_time_utc`, rename it in-place.
    with conn.cursor() as cur:
        cur.execute("SHOW COLUMNS FROM okx_kline LIKE 'open_time_shanghai'")
        has_new = bool(cur.fetchone())
        cur.execute("SHOW COLUMNS FROM okx_kline LIKE 'open_time_utc'")
        has_old = bool(cur.fetchone())
        if (not has_new) and has_old:
            cur.execute(
                "ALTER TABLE okx_kline "
                "CHANGE COLUMN open_time_utc open_time_shanghai DATETIME NOT NULL "
                "COMMENT 'Asia/Shanghai local time (UTC+8)'"
            )
            conn.commit()

    ensure_kline_triggers(conn, table="okx_kline")


def _ccxt_symbol_to_inst_id(symbol: str) -> str:
    if ":" in symbol:
        base_quote = symbol.split(":")[0]
        base, quote = base_quote.split("/")
        return f"{base}-{quote}-SWAP"
    base, quote = symbol.split("/")
    return f"{base}-{quote}"


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


def _request_okx(url: str, params: dict, proxies: dict) -> list:
    retries = 3
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, params=params, timeout=20, proxies=proxies or None)
            resp.raise_for_status()
            body = resp.json()
            if body.get("code") != "0":
                raise RuntimeError(f"OKX API error code={body.get('code')}: {body.get('msg', '')}")
            return body.get("data", [])
        except (requests.RequestException, RuntimeError):
            if attempt == retries:
                raise
            pytime.sleep(1.5)
    return []


def fetch_okx_ohlcv_range(symbol: str, timeframe: str, start_ms: int, end_ms: int) -> list[list[float]]:
    if start_ms >= end_ms:
        return []

    url = "https://www.okx.com/api/v5/market/history-candles"
    inst_id = _ccxt_symbol_to_inst_id(symbol)
    proxies = _get_proxies()

    cursor = end_ms
    rows_by_ts: dict[int, list[float]] = {}

    for _ in range(2000):
        params = {
            "instId": inst_id,
            "bar": timeframe,
            "after": str(cursor),
            "limit": "100",
        }
        candles = _request_okx(url, params, proxies)
        if not candles:
            break

        oldest_ts = cursor
        reached_lower_bound = False
        for row in candles:
            ts_ms = int(row[0])
            oldest_ts = min(oldest_ts, ts_ms)
            if ts_ms < start_ms:
                reached_lower_bound = True
                continue
            if ts_ms >= end_ms:
                continue
            rows_by_ts[ts_ms] = [
                ts_ms,
                float(row[1]),
                float(row[2]),
                float(row[3]),
                float(row[4]),
                float(row[5]),
            ]

        if oldest_ts >= cursor:
            break
        cursor = oldest_ts

        if reached_lower_bound:
            break

    return [rows_by_ts[k] for k in sorted(rows_by_ts)]


def upsert_rows(conn, symbol: str, timeframe: str, rows: list[list[float]]) -> int:
    if not rows:
        return 0

    sql = """
    INSERT INTO okx_kline (
        symbol, timeframe, open_time_ms, open_time_shanghai,
        open_price, high_price, low_price, close_price, volume,
        created_at, updated_at
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
        open_price = VALUES(open_price),
        high_price = VALUES(high_price),
        low_price = VALUES(low_price),
        close_price = VALUES(close_price),
        volume = VALUES(volume),
        updated_at = VALUES(updated_at)
    """

    now_shanghai = datetime.now(tz=STORAGE_TZ).replace(tzinfo=None)
    payload = []
    for ts_ms, o, h, l, c, v in rows:
        # Store Shanghai local time (UTC+8) for easier inspection/querying.
        open_time_shanghai = datetime.fromtimestamp(int(ts_ms) / 1000, tz=STORAGE_TZ).replace(tzinfo=None)
        payload.append(
            (
                symbol,
                timeframe,
                int(ts_ms),
                open_time_shanghai,
                float(o),
                float(h),
                float(l),
                float(c),
                float(v),
                now_shanghai,
                now_shanghai,
            )
        )

    with conn.cursor() as cur:
        affected = cur.executemany(sql, payload)
    conn.commit()
    return int(affected)


def sync_day_kline(symbol: str, timeframe: str, day_text: str, tz_name: str) -> dict:
    start_ms, end_ms = _day_window(day_text, tz_name)
    cfg = get_mysql_config()
    conn = mysql_connect(cfg)
    try:
        ensure_table(conn)
        rows = fetch_okx_ohlcv_range(symbol, timeframe, start_ms, end_ms)
        affected = upsert_rows(conn, symbol, timeframe, rows)
    finally:
        conn.close()

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "date": day_text,
        "fetched": len(rows),
        "affected": affected,
        "start_ms": start_ms,
        "end_ms": end_ms,
    }


def sync_range_kline(symbol: str, timeframe: str, start_text: str, end_text: str, tz_name: str) -> dict:
    start_ms, end_ms = build_range_window(start_text, end_text, timeframe, tz_name)
    cfg = get_mysql_config()
    conn = mysql_connect(cfg)
    try:
        ensure_table(conn)
        rows = fetch_okx_ohlcv_range(symbol, timeframe, start_ms, end_ms)
        affected = upsert_rows(conn, symbol, timeframe, rows)
    finally:
        conn.close()

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "start_date": start_text,
        "end_date": end_text,
        "fetched": len(rows),
        "affected": affected,
        "start_ms": start_ms,
        "end_ms": end_ms,
    }
