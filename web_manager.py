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

BASE_DIR = Path(__file__).resolve().parent
STATE_FILE = BASE_DIR / "process_state.json"

STRATEGIES = {
    "doge": {
        "script": "deepseek_doge.py",
        "log": "app_doge.log",
        "display": "DOGE",
    },
    "xrp": {
        "script": "deepseek_xrp.py",
        "log": "app_xrp.log",
        "display": "XRP",
    },
}

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


def _refresh_state(state: dict) -> dict:
    updated = dict(state)
    for name in STRATEGIES:
        pid = updated.get(name, {}).get("pid")
        if pid and not _is_pid_alive(pid):
            updated[name] = {}
    return updated


def _strategy_status(name: str, state: dict) -> dict:
    strategy = STRATEGIES[name]
    current = state.get(name, {})
    pid = current.get("pid")
    running = bool(pid and _is_pid_alive(pid))

    if not running:
        detected_pid = _find_pid_by_script(strategy["script"])
        if detected_pid:
            pid = detected_pid
            running = True

    return {
        "name": name,
        "display": strategy["display"],
        "script": strategy["script"],
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
    state = _refresh_state(load_state())
    status = _strategy_status(name, state)
    if status["running"]:
        state[name] = {
            "pid": status["pid"],
            "started_at": state.get(name, {}).get("started_at") or _utc_now_iso(),
            "mode": state.get(name, {}).get("mode", "live"),
        }
        save_state(state)
        return False, f"{name} already running", status

    script_path = BASE_DIR / STRATEGIES[name]["script"]
    log_path = BASE_DIR / STRATEGIES[name]["log"]

    with open(log_path, "a", encoding="utf-8") as log_file:
        child_env = {
            **os.environ,
            "PYTHONUNBUFFERED": "1",
            # Strategy scripts read this variable from settings.TRADE_TEST_MODE.
            "TRADE_TEST_MODE": "1" if mode == "paper" else "0",
        }
        proc = subprocess.Popen(
            [sys.executable, str(script_path)],
            cwd=str(BASE_DIR),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            env=child_env,
            start_new_session=True,
        )

    state[name] = {"pid": proc.pid, "started_at": _utc_now_iso(), "mode": mode}
    save_state(state)
    return True, f"{name} started in {mode} mode", _strategy_status(name, state)


def _stop_strategy(name: str, timeout_seconds: int = 8) -> tuple[bool, str, dict]:
    state = _refresh_state(load_state())
    status = _strategy_status(name, state)
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
    return True, f"{name} stopped", _strategy_status(name, state)


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
    state = _refresh_state(load_state())
    save_state(state)
    return jsonify([_strategy_status(name, state) for name in STRATEGIES])


@app.post("/api/strategies/<name>/start")
def api_start(name: str):
    if name not in STRATEGIES:
        return jsonify({"error": f"unknown strategy: {name}"}), 404

    body = request.get_json(silent=True) or {}
    mode = _normalize_mode(body.get("mode"))

    changed, message, status = _start_strategy(name, mode=mode)
    return jsonify({"ok": changed, "message": message, "status": status})


@app.post("/api/strategies/<name>/stop")
def api_stop(name: str):
    if name not in STRATEGIES:
        return jsonify({"error": f"unknown strategy: {name}"}), 404

    changed, message, status = _stop_strategy(name)
    return jsonify({"ok": changed, "message": message, "status": status})


@app.get("/api/strategies/<name>/logs")
def api_logs(name: str):
    if name not in STRATEGIES:
        return jsonify({"error": f"unknown strategy: {name}"}), 404

    try:
        lines = int(request.args.get("lines", "120"))
    except ValueError:
        lines = 120

    lines = max(20, min(lines, 1000))
    log_path = BASE_DIR / STRATEGIES[name]["log"]
    content = _tail_log(log_path, lines)
    return jsonify({"name": name, "log": STRATEGIES[name]["log"], "content": content})


@app.get("/api/kline/options")
def api_kline_options():
    return jsonify(
        {
            "symbols": ["DOGE/USDT:USDT", "XRP/USDT:USDT"],
            "day_timeframes": sorted(DAY_TIMEFRAMES),
            "range_timeframes": sorted(RANGE_TIMEFRAMES),
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

    try:
        if sync_type == "day":
            if timeframe not in DAY_TIMEFRAMES:
                return jsonify({"error": "day sync only supports 5m, 15m, 1H"}), 400

            day_text = str(body.get("date") or "").strip()
            if not day_text:
                return jsonify({"error": "date is required (YYYY-MM-DD)"}), 400

            result = sync_day_kline(symbol=symbol, timeframe=timeframe, day_text=day_text, tz_name=tz_name)
        else:
            if timeframe not in RANGE_TIMEFRAMES:
                return jsonify({"error": "range sync only supports 1D, 1M"}), 400

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


if __name__ == "__main__":
    host = os.getenv("WEB_MANAGER_HOST", "127.0.0.1")
    port = int(os.getenv("WEB_MANAGER_PORT", "8080"))
    debug = os.getenv("WEB_MANAGER_DEBUG", "0") == "1"
    app.run(host=host, port=port, debug=debug)

