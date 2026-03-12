<p style="text-align:left">
  <a href="./README.md"><img alt="中文" src="https://img.shields.io/badge/中文-CN-0b70d5.svg?style=flat-square"></a>
</p>


# DeepSeek + OKX Auto Trader

Summary
- This project integrates the `deepseek` API with the OKX trading API to provide automated order scripts (single-side position mode).
- Repository folder: `ds/`, contains main scripts and run wrappers.

## Quick reference
| Item | Command / File |
|---|---|
| Start general / DOGE | `./run_crypto.sh doge` |
| Start XRP script | `./run_crypto.sh xrp` |
| Start web manager | `python web_manager.py` |
| Configuration file | `.env` (project root) |
| Local logs | `trading_logs.db` (SQLite) |

## Current files (key items)
- `deepseek_ok_plus.py` — Core logic (general)
- `deepseek_ok_plus_xrp.py` — XRP-specific logic
- `run_crypto.sh` — Unified runner script. Accepts `doge` or `xrp`, prepares environment, installs dependencies, stops previous process (if any), and starts the selected script with logs.
- `web_manager.py` — Web control service to start/stop strategies and read logs.
- `templates/index.html` — Web dashboard page.
- `requirements.txt` — Python dependencies
- `.env` — Configuration file (create before running)
- `trading_logs.db` — Local SQLite logs/records (generated/updated at runtime)

> Note: There is no `deepseek_ok_plus_trx.py` or `run_trx.sh` in this repository; if TRX support is required, check other branches or older versions.

## Requirements
- Python 3.10 (recommended)
- pip

## Installation (local or server)
1. Clone the repository into the `ds/` directory.
2. Create and activate a Python environment (example: venv or conda):

- Using venv (macOS / Linux):

```bash
python3.10 -m venv .venv
source .venv/bin/activate
```

- Or using conda:

```bash
conda create -n ds python=3.10
conda activate ds
```

3. Install dependencies:

```bash
pip install -r requirements.txt
```

## Configuration (`.env`)
Create a `.env` file in the project root (`ds/`) and add API credentials, for example:

```
DEEPSEEK_API_KEY=
OKX_API_KEY=
OKX_SECRET=
OKX_PASSWORD=

# Optional: MySQL log storage (preferred when configured)
MYSQL_USERNAME=
MYSQL_PASSWORD=
MYSQL_HOST=
MYSQL_PORT=
MYSQL_DB=
```

Keep credentials secure and do not commit them to version control.

## Usage (run scripts)
- Start the DOGE/general script:

```bash
./run_crypto.sh doge
```

- Start the XRP-specific script:

```bash
./run_crypto.sh xrp
```

Migration note:
- The previous wrapper scripts `run_doge.sh` and `run_xrp.sh` were removed and replaced by `run_crypto.sh`.
- If you previously used `./run_doge.sh` or `./run_xrp.sh`, please switch to `./run_crypto.sh doge` or `./run_crypto.sh xrp`.

The scripts load configuration from `.env` and run the corresponding strategy. To run in background, use `nohup`, `tmux`/`screen`, or a process manager on production servers.

## Usage (web visual manager)
After installing dependencies, start the web manager:

```bash
python web_manager.py
```

Default URL: `http://127.0.0.1:8080`

Features:
- Check DOGE / XRP runtime status and PID
- Start or stop a selected crypto strategy from the UI
- Choose trading mode before start: `Live (Real Trading)` or `Simulated (Paper)`
- View latest logs for each strategy (`app_doge.log` / `app_xrp.log`)

Optional environment variables:
- `WEB_MANAGER_HOST` (default `127.0.0.1`)
- `WEB_MANAGER_PORT` (default `8080`)
- `WEB_MANAGER_DEBUG` (`1` enables Flask debug)

## Import yesterday 15m K-lines into MySQL
Make sure `.env` has: `MYSQL_USERNAME`, `MYSQL_PASSWORD`, `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_DB`.

Run:

```bash
python sync_okx_yesterday_15m.py --symbol XRP/USDT:USDT
```

Notes:
- Auto-creates `okx_kline_15m` if missing
- Uses `Asia/Shanghai` natural-day "yesterday" by default
- You can pass timezone via `--tz`, for example `--tz UTC`

## Local logs
During runtime the scripts write trades/events to MySQL first when `MYSQL_*` variables are fully configured; otherwise they fall back to `trading_logs.db` (SQLite).

For first-time MySQL setup, run once:

```bash
python init_mysql_tables.py
```

This creates the database (if missing) and the `trade_logs` table automatically.

## Deployment suggestions (optional)
- Recommended to deploy on a stable Linux server (e.g., Ubuntu). Use `tmux`/`systemd`/`pm2` or other process managers to keep scripts running.
- Typical flow: create virtualenv → install deps → configure `.env` → start with `tmux` or `systemd`.

## Troubleshooting
- Cannot connect to OKX: verify `OKX_API_KEY`, `OKX_SECRET`, `OKX_PASSWORD` and ensure API permissions (trade/read) are enabled.
- Dependency installation fails: ensure Python 3.10 and upgrade pip:

```bash
pip install --upgrade pip
```

- Logs: check script stdout/stderr or open `trading_logs.db`.

## To-do / Suggested improvements
- Add TRX-specific script if TRX support is needed.
- Add unit tests, example `systemd` or `pm2` config, and instructions to export `trading_logs.db` data.

This is the English version — see Chinese: README.md


## Acknowledgements
Thanks to the project: [huojichuanqi/ds](https://github.com/huojichuanqi/ds) — parts of this project were inspired by or reference that repository.
