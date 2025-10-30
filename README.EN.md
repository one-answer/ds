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
| Start general / DOGE | `./run_doge.sh` |
| Start XRP script | `./run_xrp.sh` |
| Configuration file | `.env` (project root) |
| Local logs | `trading_logs.db` (SQLite) |

## Current files (key items)
- `deepseek_ok_plus.py` — Core logic (general)
- `deepseek_ok_plus_xrp.py` — XRP-specific logic
- `run_doge.sh` — DOGE / general run script
- `run_xrp.sh` — XRP-specific run script
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
```

Keep credentials secure and do not commit them to version control.

## Usage (run scripts)
- Start the DOGE/general script:

```bash
./run_doge.sh
```

- Start the XRP-specific script:

```bash
./run_xrp.sh
```

The scripts load configuration from `.env` and run the corresponding strategy. To run in background, use `nohup`, `tmux`/`screen`, or a process manager on production servers.

## Local logs
During runtime the scripts write trades/events into `trading_logs.db` (SQLite). Use sqlite3 or a small script to query/export logs.

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
