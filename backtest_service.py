import math
from dataclasses import dataclass
from typing import Any, Callable, Optional

from kline_sync_service import build_range_window, ensure_table, get_mysql_config, mysql_connect, normalize_timeframe


@dataclass(frozen=True)
class Candle:
    ts_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float


def fetch_klines(symbol: str, timeframe: str, start_ms: int, end_ms: int) -> list[Candle]:
    tf = normalize_timeframe(timeframe)
    if not tf:
        raise ValueError("invalid timeframe")

    cfg = get_mysql_config()
    conn = mysql_connect(cfg)
    try:
        ensure_table(conn)
        sql = """
        SELECT open_time_ms, open_price, high_price, low_price, close_price, volume
        FROM okx_kline
        WHERE symbol=%s AND timeframe=%s AND open_time_ms >= %s AND open_time_ms < %s
        ORDER BY open_time_ms ASC
        """
        with conn.cursor() as cur:
            cur.execute(sql, (symbol, tf, int(start_ms), int(end_ms)))
            rows = cur.fetchall() or []
    finally:
        conn.close()

    candles: list[Candle] = []
    for row in rows:
        # Some rows may have missing prices depending on upstream ingestion.
        if row.get("open_price") is None or row.get("close_price") is None:
            continue
        candles.append(
            Candle(
                ts_ms=int(row["open_time_ms"]),
                open=float(row.get("open_price") or 0.0),
                high=float(row.get("high_price") or 0.0),
                low=float(row.get("low_price") or 0.0),
                close=float(row.get("close_price") or 0.0),
                volume=float(row.get("volume") or 0.0),
            )
        )
    return candles


def _sma(values: list[float], window: int, idx: int) -> Optional[float]:
    if window <= 0:
        return None
    start = idx - window + 1
    if start < 0:
        return None
    segment = values[start : idx + 1]
    if not segment:
        return None
    return sum(segment) / float(window)


def _rsi(values: list[float], period: int) -> list[Optional[float]]:
    if period <= 1:
        return [None for _ in values]
    rsis: list[Optional[float]] = [None for _ in values]
    gains: list[float] = []
    losses: list[float] = []

    for i in range(1, len(values)):
        change = values[i] - values[i - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

    if len(gains) < period:
        return rsis

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    def rsi_from(avg_g: float, avg_l: float) -> float:
        if avg_l <= 0:
            return 100.0
        rs = avg_g / avg_l
        return 100.0 - (100.0 / (1.0 + rs))

    rsis[period] = rsi_from(avg_gain, avg_loss)
    for i in range(period + 1, len(values)):
        g = gains[i - 1]
        l = losses[i - 1]
        avg_gain = (avg_gain * (period - 1) + g) / period
        avg_loss = (avg_loss * (period - 1) + l) / period
        rsis[i] = rsi_from(avg_gain, avg_loss)
    return rsis


def _std(values: list[float], window: int, idx: int) -> Optional[float]:
    if window <= 1:
        return None
    start = idx - window + 1
    if start < 0:
        return None
    segment = values[start : idx + 1]
    if not segment:
        return None
    mean = sum(segment) / float(window)
    var = sum((v - mean) ** 2 for v in segment) / float(window)
    return math.sqrt(var)


def _max_drawdown(equity: list[float]) -> float:
    peak = -float("inf")
    max_dd = 0.0
    for v in equity:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (peak - v) / peak
            if dd > max_dd:
                max_dd = dd
    return max_dd


def _sharpe(returns: list[float]) -> Optional[float]:
    if len(returns) < 3:
        return None
    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    if var <= 0:
        return None
    return mean / math.sqrt(var)


def _cost_rate_from_bps(bps: float) -> float:
    try:
        bps_f = float(bps)
    except Exception:
        return 0.0
    if bps_f < 0:
        bps_f = 0.0
    return bps_f / 10000.0


StrategyFn = Callable[[int, list[Candle], dict[str, Any], int], int]


def strategy_ma_crossover(idx: int, candles: list[Candle], params: dict[str, Any], current_pos: int) -> int:
    closes = [c.close for c in candles]
    fast = int(params.get("fast", 10))
    slow = int(params.get("slow", 30))
    if slow <= fast:
        slow = fast + 1

    fast_ma = _sma(closes, fast, idx)
    slow_ma = _sma(closes, slow, idx)
    if fast_ma is None or slow_ma is None:
        return 0
    if fast_ma > slow_ma:
        return 1
    if fast_ma < slow_ma:
        return -1
    return current_pos


def strategy_rsi_reversion(idx: int, candles: list[Candle], params: dict[str, Any], current_pos: int) -> int:
    closes = [c.close for c in candles]
    period = int(params.get("period", 14))
    buy = float(params.get("buy_below", 30))
    sell = float(params.get("sell_above", 70))
    exit_level = float(params.get("exit_level", 50))

    rsis = _rsi(closes, period)
    r = rsis[idx]
    if r is None:
        return 0

    # Mean reversion: fade extremes, exit near midline.
    if current_pos == 0:
        if r <= buy:
            return 1
        if r >= sell:
            return -1
        return 0

    if current_pos == 1 and r >= exit_level:
        return 0
    if current_pos == -1 and r <= exit_level:
        return 0
    return current_pos


def strategy_donchian_breakout(idx: int, candles: list[Candle], params: dict[str, Any], current_pos: int) -> int:
    entry = int(params.get("entry", 20))
    exit_ = int(params.get("exit", 10))
    if entry <= 1:
        entry = 20
    if exit_ <= 1:
        exit_ = 10

    if idx <= 0:
        return 0

    # Use previous window to avoid lookahead.
    start_entry = max(0, idx - entry)
    window_entry = candles[start_entry:idx]
    if len(window_entry) < entry:
        return 0

    highest = max(c.high for c in window_entry)
    lowest = min(c.low for c in window_entry)
    close = candles[idx].close

    if current_pos == 0:
        if close > highest:
            return 1
        if close < lowest:
            return -1
        return 0

    start_exit = max(0, idx - exit_)
    window_exit = candles[start_exit:idx]
    if len(window_exit) < exit_:
        return current_pos
    highest_exit = max(c.high for c in window_exit)
    lowest_exit = min(c.low for c in window_exit)

    if current_pos == 1 and close < lowest_exit:
        return 0
    if current_pos == -1 and close > highest_exit:
        return 0
    return current_pos


def strategy_adaptive_reversion(idx: int, candles: list[Candle], params: dict[str, Any], current_pos: int) -> int:
    closes = [c.close for c in candles]
    fast = int(params.get("fast", 20))
    slow = int(params.get("slow", 80))
    if slow <= fast:
        slow = fast + 1
    band_k = float(params.get("band_k", 1.5))
    trend_thresh = float(params.get("trend_thresh", 0.006))
    rsi_period = int(params.get("rsi_period", 14))
    rsi_buy = float(params.get("rsi_buy", 35))
    rsi_sell = float(params.get("rsi_sell", 65))
    exit_level = float(params.get("exit_level", 50))

    fast_ma = _sma(closes, fast, idx)
    slow_ma = _sma(closes, slow, idx)
    std = _std(closes, fast, idx)
    if fast_ma is None or slow_ma is None or std is None:
        return 0

    rsis = _rsi(closes, rsi_period)
    r = rsis[idx]
    if r is None or slow_ma == 0:
        return 0

    close = closes[idx]
    trend = (fast_ma - slow_ma) / slow_ma
    band = band_k * std

    # Profit-biased: avoid low-trend chop, follow trends and give trades room.
    if abs(trend) < trend_thresh:
        if current_pos != 0:
            return 0
        return 0

    if trend > 0:
        if current_pos == 0:
            if close > fast_ma + band or (close >= fast_ma and r >= exit_level):
                return 1
            return 0
        if current_pos == 1:
            if close < slow_ma or trend < 0:
                return 0
            return current_pos
        if current_pos == -1:
            return 0

    if trend < 0:
        if current_pos == 0:
            if close < fast_ma - band or (close <= fast_ma and r <= exit_level):
                return -1
            return 0
        if current_pos == -1:
            if close > slow_ma or trend > 0:
                return 0
            return current_pos
        if current_pos == 1:
            return 0

    return current_pos


STRATEGIES: dict[str, dict[str, Any]] = {
    "ma_crossover": {
        "name": "MA Crossover",
        "name_zh": "均线交叉",
        "description": "Fast/slow moving average crossover (long/short).",
        "description_zh": "短期/长期均线交叉：短均线上穿长均线做多；短均线下穿长均线做空。",
        "defaults": {"fast": 10, "slow": 30},
        "fn": strategy_ma_crossover,
        "warmup": 60,
    },
    "rsi_reversion": {
        "name": "RSI Reversion",
        "name_zh": "RSI 反转",
        "description": "Fade RSI extremes and exit near midline (long/short).",
        "description_zh": "RSI 均值回归：RSI 超卖做多、超买做空；回到中线附近退出持仓。",
        "defaults": {"period": 14, "buy_below": 30, "sell_above": 70, "exit_level": 50},
        "fn": strategy_rsi_reversion,
        "warmup": 30,
    },
    "donchian_breakout": {
        "name": "Donchian Breakout",
        "name_zh": "唐奇安突破",
        "description": "Turtle-style channel breakout with shorter exit channel.",
        "description_zh": "唐奇安通道突破：突破过去 N 根最高价做多、跌破最低价做空；用更短的通道反向突破退出。",
        "defaults": {"entry": 20, "exit": 10},
        "fn": strategy_donchian_breakout,
        "warmup": 60,
    },
    "adaptive_reversion": {
        "name": "Adaptive Reversion",
        "name_zh": "自适应回归",
        "description": "Profit-biased regime filter: skip chop, follow trend breakouts and hold longer.",
        "description_zh": "偏利润的自适应策略：过滤震荡行情，趋势突破顺势进场并持有更久。",
        "defaults": {
            "fast": 20,
            "slow": 80,
            "band_k": 1.5,
            "trend_thresh": 0.006,
            "rsi_period": 14,
            "rsi_buy": 35,
            "rsi_sell": 65,
            "exit_level": 50,
            "stop_loss_pct": 1.2,
            "take_profit_pct": 2.5,
            "max_hold_bars": 96,
        },
        "fn": strategy_adaptive_reversion,
        "warmup": 100,
    },
}


def backtest(
    candles: list[Candle],
    strategy_id: str,
    params: Optional[dict[str, Any]] = None,
    leverage: float = 1.0,
    fee_bps: float = 5.0,
    slippage_bps: float = 2.0,
) -> dict[str, Any]:
    if strategy_id not in STRATEGIES:
        raise ValueError(f"unknown strategy: {strategy_id}")

    if len(candles) < 10:
        raise ValueError("not enough kline data for backtest")

    meta = STRATEGIES[strategy_id]
    fn: StrategyFn = meta["fn"]
    warmup = int(meta.get("warmup", 0))
    merged_params = dict(meta.get("defaults") or {})
    if params:
        merged_params.update(params)

    try:
        lev = float(leverage)
    except Exception:
        lev = 1.0
    if lev <= 0:
        lev = 1.0
    if lev > 50:
        lev = 50.0

    cost_rate = _cost_rate_from_bps(fee_bps) + _cost_rate_from_bps(slippage_bps)
    try:
        stop_loss_pct = float(merged_params.get("stop_loss_pct", 0.0))
    except Exception:
        stop_loss_pct = 0.0
    try:
        take_profit_pct = float(merged_params.get("take_profit_pct", 0.0))
    except Exception:
        take_profit_pct = 0.0
    try:
        max_hold_bars = int(merged_params.get("max_hold_bars", 0))
    except Exception:
        max_hold_bars = 0

    pos = 0
    entry_price = None
    entry_ts = None
    entry_idx = None
    equity = 1.0
    equity_at_entry = 1.0
    equity_curve: list[float] = []
    realized_returns: list[float] = []
    trades: list[dict[str, Any]] = []

    def mark_to_market(close_price: float) -> float:
        nonlocal equity
        if pos == 0 or entry_price is None:
            return equity
        if entry_price <= 0:
            return equity
        if pos == 1:
            pnl = (close_price - entry_price) / entry_price
        else:
            pnl = (entry_price - close_price) / entry_price
        equity = equity_at_entry * (1.0 + lev * pnl)
        return equity

    for i in range(len(candles)):
        # mark equity at each candle close
        mark_to_market(candles[i].close)
        equity_curve.append(equity)

        # Need next candle open to execute changes
        if i >= len(candles) - 2:
            continue
        if i < warmup:
            continue

        desired = fn(i, candles, merged_params, pos)
        if desired not in (-1, 0, 1):
            desired = 0

        next_open = candles[i + 1].open
        next_ts = candles[i + 1].ts_ms

        force_exit = False
        if pos != 0 and entry_price is not None:
            close = candles[i].close
            if stop_loss_pct > 0:
                if pos == 1 and close <= entry_price * (1.0 - stop_loss_pct / 100.0):
                    force_exit = True
                if pos == -1 and close >= entry_price * (1.0 + stop_loss_pct / 100.0):
                    force_exit = True
            if take_profit_pct > 0:
                if pos == 1 and close >= entry_price * (1.0 + take_profit_pct / 100.0):
                    force_exit = True
                if pos == -1 and close <= entry_price * (1.0 - take_profit_pct / 100.0):
                    force_exit = True
            if max_hold_bars > 0 and entry_idx is not None and (i - entry_idx) >= max_hold_bars:
                force_exit = True

        if force_exit:
            desired = 0

        if desired == pos:
            continue

        # Close existing position at next open.
        if pos != 0 and entry_price is not None and next_open > 0:
            if pos == 1:
                gross = (next_open - entry_price) / entry_price
            else:
                gross = (entry_price - next_open) / entry_price

            # Approx fees/slippage on notional (scaled by leverage).
            net = lev * gross - (2.0 * cost_rate * lev)
            equity *= 1.0 + net
            realized_returns.append(net)
            trades.append(
                {
                    "side": "LONG" if pos == 1 else "SHORT",
                    "entry_ts_ms": int(entry_ts or 0),
                    "entry_price": float(entry_price),
                    "exit_ts_ms": int(next_ts),
                    "exit_price": float(next_open),
                    "return_pct": float(net * 100.0),
                }
            )
            pos = 0
            entry_price = None
            entry_ts = None
            entry_idx = None
            equity_at_entry = equity

        # Open new position at next open.
        if desired != 0 and next_open > 0 and not force_exit:
            pos = desired
            entry_price = float(next_open)
            entry_ts = int(next_ts)
            entry_idx = i + 1
            equity_at_entry = equity

    total_return = (equity_curve[-1] - 1.0) if equity_curve else 0.0
    bh_return = (candles[-1].close / candles[0].open - 1.0) if candles[0].open > 0 else 0.0
    dd = _max_drawdown(equity_curve) if equity_curve else 0.0

    wins = [t for t in trades if t.get("return_pct", 0.0) > 0]
    losses = [t for t in trades if t.get("return_pct", 0.0) <= 0]
    win_rate = (len(wins) / len(trades)) if trades else 0.0

    sum_win = sum(t["return_pct"] for t in wins)
    sum_loss = -sum(t["return_pct"] for t in losses)  # positive number
    profit_factor = (sum_win / sum_loss) if sum_loss > 0 else None

    sharpe = _sharpe(realized_returns)
    return {
        "strategy": {
            "id": strategy_id,
            "name": meta["name"],
            "description": meta.get("description", ""),
            "params": merged_params,
        },
        "candles": len(candles),
        "trades": len(trades),
        "total_return_pct": float(total_return * 100.0),
        "buy_hold_return_pct": float(bh_return * 100.0),
        "max_drawdown_pct": float(dd * 100.0),
        "win_rate_pct": float(win_rate * 100.0),
        "profit_factor": None if profit_factor is None else float(profit_factor),
        "sharpe_like": None if sharpe is None else float(sharpe),
        "leverage": float(lev),
        "fee_bps": float(fee_bps),
        "slippage_bps": float(slippage_bps),
        "cost_bps_total_per_side": float((cost_rate) * 10000.0),
        "trades_preview": trades[:50],
        "equity_end": float(equity_curve[-1] if equity_curve else equity),
    }


def backtest_from_dates(
    symbol: str,
    timeframe: str,
    start_date: str,
    end_date: str,
    tz_name: str,
    strategy_id: str,
    params: Optional[dict[str, Any]] = None,
    leverage: float = 1.0,
    fee_bps: float = 5.0,
    slippage_bps: float = 2.0,
) -> dict[str, Any]:
    tf = normalize_timeframe(timeframe)
    if not tf:
        raise ValueError("invalid timeframe")
    start_ms, end_ms = build_range_window(start_date, end_date, tf, tz_name)
    candles = fetch_klines(symbol=symbol, timeframe=tf, start_ms=start_ms, end_ms=end_ms)
    result = backtest(
        candles=candles,
        strategy_id=strategy_id,
        params=params,
        leverage=leverage,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
    )
    result["symbol"] = symbol
    result["timeframe"] = tf
    result["start_date"] = start_date
    result["end_date"] = end_date
    result["tz"] = tz_name
    result["start_ms"] = int(start_ms)
    result["end_ms"] = int(end_ms)
    return result
