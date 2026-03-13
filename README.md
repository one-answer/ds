<h1 id="chinese">DeepSeek + OKX Auto Trader</h1>

<p style="text-align:right">
  <a href="./README.EN.md"><img alt="English" src="https://img.shields.io/badge/English-EN-6c757d.svg?style=flat-square"></a>
</p>

<!-- English note: make the bilingual link more prominent -->
<p style="text-align:right; margin-top:-1.2rem;">
  <strong>This is the Chinese version — see English: <a href="./README.EN.md">README.EN.md</a></strong>
</p>

---

## 简短说明
- 本项目基于 `deepseek` 接口与 `OKX` 交易 API，提供自动下单脚本（单向持仓模式）。
- 目录：`ds/`，包含主要脚本与运行脚本。

## 快速参考
- 启动通用 / DOGE 脚本：`./run_crypto.sh doge`
- 启动 XRP 脚本：`./run_crypto.sh xrp`
- 启动页面管理：`python web_manager.py`（默认 `http://127.0.0.1:8080`）
- 配置：在项目根放置 `.env`（见下）
- 本地日志：`trading_logs.db`（SQLite）

---

## 当前目录（主要文件）
- `deepseek_ok_plus.py` — 核心逻辑（通用）
- `deepseek_ok_plus_xrp.py` — XRP 专用逻辑
- `run_crypto.sh` — 统一的启动脚本，接受参数 `doge` 或 `xrp`，负责环境准备、依赖安装、停止/启动进程并写日志
- `web_manager.py` — 页面化管理入口，提供策略启动/停止/状态与日志接口
- `templates/index.html` — Web 管理页面
- `requirements.txt` — Python 依赖
- `.env` — 配置文件（示例见下方，须在运行前新建）
- `trading_logs.db` — 本地 SQLite 日志/记录（运行时生成/更新）

> 注：仓库中没有 `deepseek_ok_plus_trx.py` 或 `run_trx.sh`（若需 TRX 支持请检查其他分支或旧版）。

## 要求
- Python 3.10（推荐）
- pip

## 安装（本地或服务器）
1. 克隆仓库到 `ds/` 目录
2. 创建并激活 Python 环境（示例使用 `venv` 或 `conda`）：

- 使用 venv（macOS / Linux）：

```bash
python3.10 -m venv .venv
source .venv/bin/activate
```

- 或使用 conda：

```bash
conda create -n ds python=3.10
conda activate ds
```

3. 安装依赖：

```bash
pip install -r requirements.txt
```

## 配置（`.env`）
在项目根目录（`ds/`）创建 `.env` 并填写 API 凭证，例如：

```
DEEPSEEK_API_KEY=
OKX_API_KEY=
OKX_SECRET=
OKX_PASSWORD=

# 可选：MySQL 日志存储（配置后优先写入 MySQL）
MYSQL_USERNAME=
MYSQL_PASSWORD=
MYSQL_HOST=
MYSQL_PORT=
MYSQL_DB=
```

请妥善保管密钥，不要提交到版本控制。项目根已包含 `.gitignore`，请确保 `.env` 被忽略。

## 使用（运行脚本）
推荐使用统一脚本 `run_crypto.sh`：

- 启动 DOGE 脚本：

```bash
./run_crypto.sh doge
```

- 启动 XRP 脚本：

```bash
./run_crypto.sh xrp
```

迁移说明：
- 之前项目中存在 `run_doge.sh` 与 `run_xrp.sh` 两个 wrapper 脚本，但它们已被删除并由 `run_crypto.sh` 统一替代。
- 若你之前使用 `./run_doge.sh` 或 `./run_xrp.sh`，请改为使用 `./run_crypto.sh doge` 或 `./run_crypto.sh xrp`。

这些脚本会读取同目录下的 `.env` 配置并执行相应策略。若要在后台运行，可使用 `nohup` 或 `tmux`/`screen`，或者在生产服务器上用进程管理器（例如 `systemd`、`pm2` 等）。

## 使用（页面可视化管理）
安装依赖后启动 Web 管理服务：

```bash
python web_manager.py
```

默认访问地址：`http://127.0.0.1:8080`

页面能力：
- 查看 DOGE / XRP 当前运行状态与 PID
- 一键启动或停止某类虚拟货币策略
- 启动前可点选交易模式：`Live (Real Trading)` 或 `Simulated (Paper)`
- 查看每个策略最近日志（`app_doge.log` / `app_xrp.log`）
- K 线同步面板支持：
  - 交易对：`BTC/USDT:USDT`、`ETH/USDT:USDT`、`DOGE/USDT:USDT`、`XRP/USDT:USDT`
  - 单日同步：`5m` / `15m` / `1H`
  - 日期范围同步：`1D` / `1M`

可选环境变量：
- `WEB_MANAGER_HOST`（默认 `127.0.0.1`）
- `WEB_MANAGER_PORT`（默认 `8080`）
- `WEB_MANAGER_DEBUG`（`1` 开启 Flask debug）

## 导入昨日15分钟K线到MySQL
先确认 `.env` 已配置：`MYSQL_USERNAME`、`MYSQL_PASSWORD`、`MYSQL_HOST`、`MYSQL_PORT`、`MYSQL_DB`。

执行：

```bash
python sync_okx_yesterday_15m.py --symbol XRP/USDT:USDT
```

说明：
- 会自动创建表 `okx_kline_15m`（不存在时）
- 默认按 `Asia/Shanghai` 的“昨日自然日”抓取 `15m` K线
- 可通过 `--tz` 指定时区，例如 `--tz UTC`

## 本地日志
运行期间脚本会优先将交易/事件记录到 MySQL（当 `MYSQL_*` 配置完整时）；否则回退到 `trading_logs.db`（SQLite）。

若是首次接入 MySQL，可先执行一次建表：

```bash
python init_mysql_tables.py
```

会自动创建数据库（若不存在）和 `trade_logs` 表。

## 部署建议（可选）
- 推荐在稳定的 Linux 服务器（例如 Ubuntu）上部署。生产环境可使用 `tmux`/`systemd`/`pm2` 或其他进程管理器保持脚本长期运行。
- 常见流程：创建虚拟环境 → 安装依赖 → 配置 `.env` → 使用 `tmux` 或 `systemd` 启动脚本。

## 常见问题与排查
- 无法连接 OKX：检查 `OKX_API_KEY` / `OKX_SECRET` / `OKX_PASSWORD` 是否正确并已开启 API 权限（交易/读取）。
- 依赖安装失败：确认 Python 版本为 3.10，并升级 pip：

```bash
pip install --upgrade pip
```

- 日志定位：查看脚本输出或打开 `trading_logs.db`。

---

<!-- English content moved to README.EN.md -->

## 致谢
非常感谢并致谢项目： [huojichuanqi/ds](https://github.com/huojichuanqi/ds) — 本项目部分灵感或实现参考自该仓库。
