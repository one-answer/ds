import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from flask import Flask, jsonify, render_template, request

from kline_sync_service import (
    DAY_TIMEFRAMES,
    RANGE_TIMEFRAMES,
    normalize_timeframe,
    sync_day_kline,
    sync_range_kline,
)
from backtest_service import STRATEGIES as BACKTEST_STRATEGIES
from backtest_service import backtest_from_dates

BASE_DIR = Path(__file__).resolve().parent
STATE_FILE = BASE_DIR / "process_state.json"
STRATEGY_REGISTRY = BASE_DIR / "strategies.json"
DEFAULT_RULE_AMOUNTS = {
    "BTC/USDT:USDT": 0.01,
    "ETH/USDT:USDT": 0.1,
    "DOGE/USDT:USDT": 50,
    "XRP/USDT:USDT": 50,
}
DEFAULT_RULE_LEVERAGES = {
    "BTC/USDT:USDT": 1,
    "ETH/USDT:USDT": 1,
    "DOGE/USDT:USDT": 1,
    "XRP/USDT:USDT": 1,
}

DEFAULT_STRATEGIES = {
    "doge": {
        "script": "deepseek_trade.py",
        "args": ["--strategy", "doge"],
        "proc_match": "deepseek_trade.py --strategy doge",
        "log": "app_doge.log",
        "display": "DOGE",
        "type": "ai",
    },
    "xrp": {
        "script": "deepseek_trade.py",
        "args": ["--strategy", "xrp"],
        "proc_match": "deepseek_trade.py --strategy xrp",
        "log": "app_xrp.log",
        "display": "XRP",
        "type": "ai",
    },
}

KLINE_SYMBOLS = [
    "BTC/USDT:USDT",
    "ETH/USDT:USDT",
    "DOGE/USDT:USDT",
    "XRP/USDT:USDT",
]

MODE_ALIASES = {
    "live": "live",
    "real": "live",
    "paper": "paper",
    "sim": "paper",
    "simulated": "paper",
    "test": "paper",
}

SYNC_TYPE_ALIASES = {
    "day": "day",
    "single_day": "day",
    "range": "range",
    "date_range": "range",
}

app = Flask(__name__, template_folder=str(BASE_DIR / "templates"))


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {}

    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _normalize_strategy_entry(name: str, data: dict) -> dict:
    entry = dict(data or {})
    entry["display"] = entry.get("display") or name.upper()
    entry["script"] = entry.get("script") or ""
    entry["args"] = entry.get("args") or []
    entry["log"] = entry.get("log") or f"app_{name}.log"
    entry["type"] = entry.get("type") or "custom"
    if not entry.get("proc_match"):
        entry["proc_match"] = " ".join([entry["script"], *entry["args"]]).strip()
    return entry


def _load_registry_overrides() -> dict:
    if not STRATEGY_REGISTRY.exists():
        return {}
    try:
        raw = json.loads(STRATEGY_REGISTRY.read_text(encoding="utf-8"))
    except Exception:
        return {}

    if isinstance(raw, dict):
        return {str(k): v for k, v in raw.items() if k}

    if isinstance(raw, list):
        overrides = {}
        for item in raw:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            overrides[name] = item
        return overrides

    return {}


def _save_registry_overrides(overrides: dict) -> None:
    STRATEGY_REGISTRY.write_text(json.dumps(overrides, indent=2, ensure_ascii=False), encoding="utf-8")


def _extract_arg_value(args: list, flag: str) -> Optional[str]:
    try:
        idx = args.index(flag)
    except ValueError:
        return None
    if idx + 1 >= len(args):
        return None
    return str(args[idx + 1])


def load_strategies() -> dict:
    strategies = {k: _normalize_strategy_entry(k, v) for k, v in DEFAULT_STRATEGIES.items()}
    overrides = _load_registry_overrides()

    for name, data in overrides.items():
        strategies[name] = _normalize_strategy_entry(name, data)

    def _symbol_key(symbol: str) -> str:
        return symbol.replace("/", "_").replace(":", "_").lower()

    for sid, meta in BACKTEST_STRATEGIES.items():
        for symbol in KLINE_SYMBOLS:
            key = f"bt_{sid}_{_symbol_key(symbol)}"
            display = f"{meta.get('name_zh') or meta.get('name') or sid} · {symbol}"
            base_amount = DEFAULT_RULE_AMOUNTS.get(symbol, 1)
            base_leverage = DEFAULT_RULE_LEVERAGES.get(symbol, 1)
            override = overrides.get(key, {})
            amount = float(override.get("amount", base_amount))
            leverage = float(override.get("leverage", base_leverage))
            args = ["--strategy-id", sid, "--symbol", symbol, "--amount", str(amount), "--leverage", str(leverage)]
            entry = {
                "script": "rule_trade.py",
                "args": args,
                "proc_match": f"rule_trade.py --strategy-id {sid} --symbol {symbol}",
                "log": f"app_{key}.log",
                "display": override.get("display") or display,
                "type": override.get("type") or "backtest",
                "amount": amount,
                "leverage": leverage,
            }
            strategies[key] = _normalize_strategy_entry(key, entry)

    for name, entry in strategies.items():
        args = entry.get("args") or []
        amount = entry.get("amount")
        leverage = entry.get("leverage")
        if amount is None:
            v = _extract_arg_value(args, "--amount")
            if v is not None:
                try:
                    entry["amount"] = float(v)
                except Exception:
                    pass
        if leverage is None:
            v = _extract_arg_value(args, "--leverage")
            if v is not None:
                try:
                    entry["leverage"] = float(v)
                except Exception:
                    pass

    return strategies


def _is_pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _find_pid_by_script(script_name: str) -> Optional[int]:
    try:
        output = subprocess.check_output(["pgrep", "-f", script_name], text=True).strip()
    except subprocess.CalledProcessError:
        return None

    if not output:
        return None

    for line in output.splitlines():
        line = line.strip()
        if line.isdigit() and int(line) != os.getpid():
            return int(line)
    return None


def _refresh_state(state: dict, strategies: dict) -> dict:
    updated = dict(state)
    for name in strategies:
        pid = updated.get(name, {}).get("pid")
        if pid and not _is_pid_alive(pid):
            updated[name] = {}
    return updated


def _strategy_status(name: str, state: dict, strategies: dict) -> dict:
    strategy = strategies[name]
    current = state.get(name, {})
    pid = current.get("pid")
    running = bool(pid and _is_pid_alive(pid))

    if not running:
        detected_pid = _find_pid_by_script(strategy.get("proc_match") or strategy["script"])
        if detected_pid:
            pid = detected_pid
            running = True

    args = strategy.get("args") or []
    script_label = " ".join([strategy["script"], *args]).strip()
    return {
        "name": name,
        "display": strategy["display"],
        "script": script_label,
        "log": strategy["log"],
        "running": running,
        "pid": pid,
        "started_at": current.get("started_at"),
        "mode": current.get("mode", "live"),
    }


def _normalize_mode(value) -> str:
    if value is None:
        return "live"
    return MODE_ALIASES.get(str(value).strip().lower(), "live")


def _normalize_sync_type(value) -> str:
    if value is None:
        return "day"
    return SYNC_TYPE_ALIASES.get(str(value).strip().lower(), "day")


def _start_strategy(name: str, mode: str = "live") -> tuple[bool, str, dict]:
    mode = _normalize_mode(mode)
    strategies = load_strategies()
    state = _refresh_state(load_state(), strategies)
    status = _strategy_status(name, state, strategies)
    if status["running"]:
        state[name] = {
            "pid": status["pid"],
            "started_at": state.get(name, {}).get("started_at") or _utc_now_iso(),
            "mode": state.get(name, {}).get("mode", "live"),
        }
        save_state(state)
        return False, f"{name} already running", status

    strategy = strategies[name]
    script_path = BASE_DIR / strategy["script"]
    log_path = BASE_DIR / strategies[name]["log"]
    args = strategy.get("args") or []

    with open(log_path, "a", encoding="utf-8") as log_file:
        child_env = {
            **os.environ,
            "PYTHONUNBUFFERED": "1",
            # Strategy scripts read this variable from settings.TRADE_TEST_MODE.
            "TRADE_TEST_MODE": "1" if mode == "paper" else "0",
        }
        proc = subprocess.Popen(
            [sys.executable, str(script_path), *args],
            cwd=str(BASE_DIR),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            env=child_env,
            start_new_session=True,
        )

    state[name] = {"pid": proc.pid, "started_at": _utc_now_iso(), "mode": mode}
    save_state(state)
    return True, f"{name} started in {mode} mode", _strategy_status(name, state, strategies)


def _stop_strategy(name: str, timeout_seconds: int = 8) -> tuple[bool, str, dict]:
    strategies = load_strategies()
    state = _refresh_state(load_state(), strategies)
    status = _strategy_status(name, state, strategies)
    pid = status.get("pid")

    if not pid:
        return False, f"{name} is not running", status

    # The bot runs in its own process group. Stop gracefully first, then force kill.
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass

    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if not _is_pid_alive(pid):
            break
        time.sleep(0.3)

    if _is_pid_alive(pid):
        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    state[name] = {}
    save_state(state)
    return True, f"{name} stopped", _strategy_status(name, state, strategies)


def _tail_log(file_path: Path, lines: int = 120) -> str:
    if not file_path.exists():
        return ""

    all_lines = file_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    return "\n".join(all_lines[-lines:])


@app.route("/")
def index():
    return render_template("index.html")


@app.get("/api/strategies")
def api_strategies():
    strategies = load_strategies()
    state = _refresh_state(load_state(), strategies)
    save_state(state)
    return jsonify([_strategy_status(name, state, strategies) for name in strategies])


@app.post("/api/strategies/<name>/start")
def api_start(name: str):
    strategies = load_strategies()
    if name not in strategies:
        return jsonify({"error": f"unknown strategy: {name}"}), 404

    body = request.get_json(silent=True) or {}
    mode = _normalize_mode(body.get("mode"))

    changed, message, status = _start_strategy(name, mode=mode)
    return jsonify({"ok": changed, "message": message, "status": status})


@app.post("/api/strategies/<name>/stop")
def api_stop(name: str):
    strategies = load_strategies()
    if name not in strategies:
        return jsonify({"error": f"unknown strategy: {name}"}), 404

    changed, message, status = _stop_strategy(name)
    return jsonify({"ok": changed, "message": message, "status": status})


@app.get("/api/strategies/<name>/logs")
def api_logs(name: str):
    strategies = load_strategies()
    if name not in strategies:
        return jsonify({"error": f"unknown strategy: {name}"}), 404

    try:
        lines = int(request.args.get("lines", "120"))
    except ValueError:
        lines = 120

    lines = max(20, min(lines, 1000))
    log_path = BASE_DIR / strategies[name]["log"]
    content = _tail_log(log_path, lines)
    return jsonify({"name": name, "log": strategies[name]["log"], "content": content})


@app.post("/api/strategies/<name>/config")
def api_strategy_config(name: str):
    strategies = load_strategies()
    if name not in strategies:
        return jsonify({"error": f"unknown strategy: {name}"}), 404

    body = request.get_json(silent=True) or {}
    try:
        amount = float(body.get("amount"))
    except (TypeError, ValueError):
        return jsonify({"error": "invalid amount"}), 400
    try:
        leverage = float(body.get("leverage"))
    except (TypeError, ValueError):
        return jsonify({"error": "invalid leverage"}), 400

    if amount <= 0 or leverage <= 0:
        return jsonify({"error": "amount/leverage must be > 0"}), 400

    overrides = _load_registry_overrides()
    overrides[name] = {
        **(overrides.get(name) or {}),
        "amount": amount,
        "leverage": leverage,
    }
    _save_registry_overrides(overrides)
    return jsonify({"ok": True, "amount": amount, "leverage": leverage})


@app.get("/api/kline/options")
def api_kline_options():
    allowed_range_timeframes = sorted({*DAY_TIMEFRAMES, *RANGE_TIMEFRAMES})
    return jsonify(
        {
            "symbols": KLINE_SYMBOLS,
            "day_timeframes": sorted(DAY_TIMEFRAMES),
            "range_timeframes": allowed_range_timeframes,
            "default_tz": "Asia/Shanghai",
        }
    )


@app.post("/api/kline/sync")
def api_kline_sync():
    body = request.get_json(silent=True) or {}
    symbol = str(body.get("symbol") or "XRP/USDT:USDT").strip()
    sync_type = _normalize_sync_type(body.get("sync_type"))
    timeframe = normalize_timeframe(body.get("timeframe"))
    tz_name = str(body.get("tz") or "Asia/Shanghai").strip()

    if not timeframe:
        return jsonify({"error": "invalid timeframe"}), 400

    if symbol not in KLINE_SYMBOLS:
        return jsonify({"error": f"unsupported symbol: {symbol}"}), 400

    try:
        if sync_type == "day":
            if timeframe not in DAY_TIMEFRAMES:
                return jsonify({"error": "day sync only supports 5m, 15m, 1H"}), 400

            day_text = str(body.get("date") or "").strip()
            if not day_text:
                return jsonify({"error": "date is required (YYYY-MM-DD)"}), 400

            result = sync_day_kline(symbol=symbol, timeframe=timeframe, day_text=day_text, tz_name=tz_name)
        else:
            allowed_range_timeframes = {*DAY_TIMEFRAMES, *RANGE_TIMEFRAMES}
            if timeframe not in allowed_range_timeframes:
                return jsonify({"error": "range sync only supports 5m, 15m, 1H, 1D, 1M"}), 400

            start_date = str(body.get("start_date") or "").strip()
            end_date = str(body.get("end_date") or "").strip()
            if not start_date or not end_date:
                return jsonify({"error": "start_date and end_date are required (YYYY-MM-DD)"}), 400

            result = sync_range_kline(
                symbol=symbol,
                timeframe=timeframe,
                start_text=start_date,
                end_text=end_date,
                tz_name=tz_name,
            )

        return jsonify({"ok": True, "message": "kline sync completed", "result": result})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": f"kline sync failed: {exc}"}), 500


@app.get("/api/backtest/options")
def api_backtest_options():
    strategies = []
    for sid, meta in BACKTEST_STRATEGIES.items():
        strategies.append(
            {
                "id": sid,
                "name": meta.get("name", sid),
                "name_zh": meta.get("name_zh", ""),
                "description": meta.get("description", ""),
                "description_zh": meta.get("description_zh", ""),
                "param_labels": meta.get("param_labels") or {},
                "param_labels_zh": meta.get("param_labels_zh") or {},
                "param_help": meta.get("param_help") or {},
                "param_help_zh": meta.get("param_help_zh") or {},
                "param_range": meta.get("param_range") or {},
                "param_presets": meta.get("param_presets") or {},
                "param_presets_zh": meta.get("param_presets_zh") or {},
                "defaults": meta.get("defaults") or {},
            }
        )
    strategies.sort(key=lambda item: item["id"])
    return jsonify(
        {
            "symbols": KLINE_SYMBOLS,
            "timeframes": sorted({*DAY_TIMEFRAMES, *RANGE_TIMEFRAMES}),
            "strategies": strategies,
            "default_tz": "Asia/Shanghai",
            "defaults": {
                "initial_capital": 1000.0,
                "leverage": 1.0,
                "fee_bps": 5.0,
                "slippage_bps": 2.0,
            },
        }
    )


@app.post("/api/backtest/run")
def api_backtest_run():
    body = request.get_json(silent=True) or {}
    symbol = str(body.get("symbol") or "XRP/USDT:USDT").strip()
    timeframe = normalize_timeframe(body.get("timeframe"))
    tz_name = str(body.get("tz") or "Asia/Shanghai").strip()
    start_date = str(body.get("start_date") or "").strip()
    end_date = str(body.get("end_date") or "").strip()
    strategy_id = str(body.get("strategy_id") or "ma_crossover").strip()
    params = body.get("params") if isinstance(body.get("params"), dict) else {}

    try:
        initial_capital = float(body.get("initial_capital", 1000.0))
    except (TypeError, ValueError):
        initial_capital = 1000.0
    if initial_capital <= 0:
        initial_capital = 1000.0

    try:
        leverage = float(body.get("leverage", 1.0))
    except (TypeError, ValueError):
        leverage = 1.0
    try:
        fee_bps = float(body.get("fee_bps", 5.0))
    except (TypeError, ValueError):
        fee_bps = 5.0
    try:
        slippage_bps = float(body.get("slippage_bps", 2.0))
    except (TypeError, ValueError):
        slippage_bps = 2.0

    if not timeframe:
        return jsonify({"error": "invalid timeframe"}), 400
    if symbol not in KLINE_SYMBOLS:
        return jsonify({"error": f"unsupported symbol: {symbol}"}), 400
    if not start_date or not end_date:
        return jsonify({"error": "start_date and end_date are required (YYYY-MM-DD)"}), 400
    if strategy_id not in BACKTEST_STRATEGIES:
        return jsonify({"error": f"unknown strategy: {strategy_id}"}), 400

    try:
        result = backtest_from_dates(
            symbol=symbol,
            timeframe=timeframe,
            start_date=start_date,
            end_date=end_date,
            tz_name=tz_name,
            strategy_id=strategy_id,
            params=params,
            leverage=leverage,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
        )
        # backtest_service returns equity_end as a ratio (starts from 1.0).
        equity_ratio = float(result.get("equity_end", 1.0))
        result["initial_capital"] = float(initial_capital)
        result["equity_end_capital"] = float(initial_capital) * equity_ratio
        result["pnl_capital"] = result["equity_end_capital"] - float(initial_capital)
        return jsonify({"ok": True, "result": result})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": f"backtest failed: {exc}"}), 500


if __name__ == "__main__":
    host = os.getenv("WEB_MANAGER_HOST", "127.0.0.1")
    port = int(os.getenv("WEB_MANAGER_PORT", "8080"))
    debug = os.getenv("WEB_MANAGER_DEBUG", "0") == "1"
    app.run(host=host, port=port, debug=debug)
