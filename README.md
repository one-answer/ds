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
- 启动通用脚本：`./run_doge.sh`
- 启动 XRP 脚本：`./run_xrp.sh`
- 配置：在项目根放置 `.env`（见下）
- 本地日志：`trading_logs.db`（SQLite）

---

## 当前目录（主要文件）
- `deepseek_ok_plus.py` — 核心逻辑（通用）
- `deepseek_ok_plus_xrp.py` — XRP 专用逻辑
- `run_doge.sh` — DOGE/通用启动脚本（项目中以该脚本命名）
- `run_xrp.sh` — XRP 专用启动脚本
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
```

请妥善保管密钥，不要提交到版本控制。项目根已包含 `.gitignore`，请确保 `.env` 被忽略。

## 使用（运行脚本）
- 启动通用 / DOGE 脚本：

```bash
./run_doge.sh
```

- 启动 XRP 专用脚本：

```bash
./run_xrp.sh
```

这些脚本会读取同目录下的 `.env` 配置并执行相应策略。若要在后台运行，可使用 `nohup` 或 `tmux`/`screen`，或者在生产服务器上用进程管理器（例如 `systemd`、`pm2` 等）。

## 本地日志
运行期间脚本会将交易/事件记录到 `trading_logs.db`（SQLite）。可用 SQLite 工具或脚本查看/导出日志。

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
