#!/bin/bash

# 1️⃣ 设置环境名称和 Python 版本
ENV_NAME="ds"
PYTHON_VERSION="3.10"

# 2️⃣ 要运行的 Python 脚本
SCRIPT_NAME="deepseek_ok_plus.py"
LOG_FILE="./app.log"

# 3️⃣ 检查 conda 环境是否存在
if ! conda info --envs | grep -q "$ENV_NAME"; then
    echo "🔧 创建 Conda 环境: $ENV_NAME (Python $PYTHON_VERSION)"
    conda create -y -n "$ENV_NAME" python="$PYTHON_VERSION"
fi

# 4️⃣ 激活环境
echo "🚀 激活环境: $ENV_NAME"
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate "$ENV_NAME"

# 5️⃣ 安装依赖
if [ -f "requirements.txt" ]; then
    echo "📦 安装依赖..."
    pip install -r requirements.txt
else
    echo "⚠️ 未找到 requirements.txt，跳过依赖安装。"
fi

# 6️⃣ 检查是否已有进程在运行
echo "🔍 检查是否已有 $SCRIPT_NAME 在运行..."
PID=$(pgrep -f "$SCRIPT_NAME")

if [ -n "$PID" ]; then
    echo "⚠️ 检测到正在运行的进程 (PID: $PID)，准备停止..."
    kill -9 $PID
    echo "✅ 已停止旧进程。"
else
    echo "✅ 未发现旧进程，直接启动新进程。"
fi

# 7️⃣ 启动新进程
echo "🚀 启动新进程..."
nohup env PYTHONUNBUFFERED=1 python "$SCRIPT_NAME" > "$LOG_FILE" 2>&1 &

NEW_PID=$!
echo "✅ 新进程已启动 (PID: $NEW_PID)"
echo "📄 日志输出: $LOG_FILE"
