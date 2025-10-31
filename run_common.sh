#!/bin/bash
# Common runner shared by run_doge.sh and run_xrp.sh
# Usage: run_common.sh <script_name> <log_file> [env_name] [python_version]

# Accept positional args or environment variables
SCRIPT_NAME="${1:-$SCRIPT_NAME}"
LOG_FILE="${2:-$LOG_FILE}"
ENV_NAME="${3:-${ENV_NAME:-ds}}"
PYTHON_VERSION="${4:-${PYTHON_VERSION:-3.10}}"

if [ -z "$SCRIPT_NAME" ] || [ -z "$LOG_FILE" ]; then
  echo "Usage: $0 <script_name> <log_file> [env_name] [python_version]"
  exit 2
fi

echo "Using ENV_NAME=$ENV_NAME PYTHON_VERSION=$PYTHON_VERSION SCRIPT_NAME=$SCRIPT_NAME LOG_FILE=$LOG_FILE"

# Ensure conda is available
if ! command -v conda >/dev/null 2>&1; then
  echo "conda not found in PATH. Please install Anaconda/Miniconda and ensure 'conda' is on your PATH."
  exit 1
fi

# Create conda env if missing
if ! conda info --envs | grep -q "$ENV_NAME"; then
    echo "🔧 Creating Conda environment: $ENV_NAME (Python $PYTHON_VERSION)"
    conda create -y -n "$ENV_NAME" python="$PYTHON_VERSION"
fi

# Activate environment
echo "🚀 Activating environment: $ENV_NAME"
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate "$ENV_NAME"

# Install dependencies if requirements.txt exists
if [ -f "requirements.txt" ]; then
    echo "📦 Installing dependencies..."
    pip install -r requirements.txt
else
    echo "⚠️ requirements.txt not found, skipping dependency install."
fi

# Check for existing process(es)
echo "🔍 Checking for running process: $SCRIPT_NAME"
PIDS=$(pgrep -f "$SCRIPT_NAME" || true)

if [ -n "$PIDS" ]; then
    echo "⚠️ Found running process(es): $PIDS - stopping..."

    for pid in $PIDS; do
        # Skip this script's own PID, its parent, and bash internal PID if present
        if [ "$pid" -eq $$ ] || { [ -n "$BASHPID" ] && [ "$pid" -eq "$BASHPID" ]; } || [ "$pid" -eq "$PPID" ]; then
            echo "⚠️ Skipping PID $pid (self/parent)"
            continue
        fi

        # Double-check the matched process actually contains the script name in its command line
        cmd=$(ps -p "$pid" -o args= 2>/dev/null || true)
        if [ -z "$cmd" ]; then
            echo "⚠️ Could not read command for PID $pid - skipping"
            continue
        fi

        if echo "$cmd" | grep -q -- "$SCRIPT_NAME"; then
            echo "🧭 Sending TERM to $pid (cmd: $cmd)"
            kill -TERM "$pid" 2>/dev/null || true
        else
            echo "⚠️ PID $pid command does not match script name (cmd: $cmd) - skipping"
        fi
    done

    echo "⏳ Waiting for processes to exit..."
    sleep 3

    # Re-check remaining matching processes and force kill if needed
    REMAINING=$(pgrep -f "$SCRIPT_NAME" || true)
    if [ -n "$REMAINING" ]; then
        echo "⚠️ Force killing remaining: $REMAINING"
        kill -9 $REMAINING || true
    fi

    echo "✅ Stopped old process(es)."
else
    echo "✅ No old process found, starting new one."
fi

# Start new process
echo "🚀 Starting new process..."
nohup env PYTHONUNBUFFERED=1 python "$SCRIPT_NAME" > "$LOG_FILE" 2>&1 &

NEW_PID=$!
echo "✅ New process started (PID: $NEW_PID)"
echo "📄 Log file: $LOG_FILE"
