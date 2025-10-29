# DeepSeek + OKX Auto Trader

简短说明
- 本项目基于 `deepseek` 接口与 `OKX` 交易 API，提供自动下单脚本（单向持仓模式）。
- 目录：`ds/`，包含主要脚本与运行脚本。

## 目录结构（主要文件）
- `deepseek_ok_plus.py` — 核心逻辑（通用）
- `deepseek_ok_plus_trx.py` — TRX 专用逻辑
- `deepseek_ok_plus_xrp.py` — XRP 专用逻辑
- `run.sh`, `run_trx.sh`, `run_xrp.sh` — 启动脚本
- `requirements.txt` — Python 依赖
- `.env` — 配置文件（须新建）

## 要求
- Python 3.10
- pip
- 推荐在 Ubuntu 服务器（香港/新加坡节点）运行

## 安装（本地或服务器）
1. 克隆仓库到 `ds/` 目录
2. 创建 Python 环境并激活（示例使用 conda）：
   - `conda create -n ds python=3.10`
   - `conda activate ds`
3. 安装依赖：
   - `pip install -r requirements.txt`

## 配置（` .env `）
在项目根目录创建 `.env` 并填写 API 凭证：

    DEEPSEEK_API_KEY=
    OKX_API_KEY=
    OKX_SECRET=
    OKX_PASSWORD=

> 请保管好密钥，不要提交到版本控制。

## 使用
- 启动通用脚本：  
  `./run.sh`
- 启动 TRX 专用：  
  `./run_trx.sh`
- 启动 XRP 专用：  
  `./run_xrp.sh`

脚本会加载 `.env` 中的配置并执行相应策略。

## 部署建议（Ubuntu / 推荐步骤）
1. 安装 Anaconda（示例）：
   - `wget https://repo.anaconda.com/archive/Anaconda3-2024.10-1-Linux-x86_64.sh`
   - `bash Anaconda3-2024.10-1-Linux-x86_64.sh`
   - `source /root/anaconda3/etc/profile.d/conda.sh`
   - `echo ". /root/anaconda3/etc/profile.d/conda.sh" >> ~/.bashrc`
2. 创建并激活环境（见上文）。
3. 安装 pm2 并使用作守护进程（可选）：
   - `apt install npm`
   - `npm install pm2 -g`
   - 例如：`pm2 start ./run.sh --name deepseek-okx`

## 常见问题与排查
- 无法连接 OKX：检查 `OKX_API_KEY` / `OKX_SECRET` / `OKX_PASSWORD` 是否正确并已开启 API 权限（交易/读取）。
- 依赖安装失败：确认 Python 版本为 3.10 并升级 pip：`pip install --upgrade pip`
- 日志定位：查看脚本输出或 `pm2 logs`（若使用 pm2）

