#!/usr/bin/env bash
set -euo pipefail

# run_crypto.sh - unified runner for crypto scripts (doge/xrp)
# Usage: run_crypto.sh <crypto>
# Example: ./run_crypto.sh doge

usage() {
  cat <<EOF
Usage: $0 {doge|xrp} [--] [args...]

This script activates the 'ds' conda environment (creates it if missing),
installs requirements from requirements.txt if present, stops any running
process for the selected script, and starts the corresponding Python script
with logs redirected to the appropriate logfile.
EOF
  exit 1
}

if [ "${1:-}" = "" ]; then
  usage
fi

# Normalize first arg to lowercase in a POSIX-compatible way (macOS bash lacks ${var,,})
LCASE=$(printf "%s" "$1" | tr '[:upper:]' '[:lower:]')

case "$LCASE" in
  -h|--help)
    usage
    ;;
  doge)
    SCRIPT_NAME="deepseek_doge.py"
    LOG_FILE="./app_doge.log"
    shift
    ;;
  xrp)
    SCRIPT_NAME="deepseek_xrp.py"
    LOG_FILE="./app_xrp.log"
    shift
    ;;
  *)
    echo "Unknown crypto: $1"
    usage
    ;;
esac

ENV_NAME="ds"
PYTHON_VERSION="3.10"

echo "🔧 Ensuring conda environment: $ENV_NAME (Python $PYTHON_VERSION)"

# If conda isn't available, warn but continue (user may use system python)
if ! command -v conda >/dev/null 2>&1; then
  echo "⚠️  'conda' not found in PATH. Skipping conda environment creation/activation." >&2
else
  if ! conda info --envs | grep -q "^$ENV_NAME\b"; then
    echo "🔧 Creating Conda environment: $ENV_NAME (Python $PYTHON_VERSION)"
    conda create -y -n "$ENV_NAME" python="$PYTHON_VERSION"
  fi

  echo "🚀 Activating environment: $ENV_NAME"
  # shellcheck source=/dev/null
  source "$(conda info --base)/etc/profile.d/conda.sh"
  conda activate "$ENV_NAME"
fi

# Install dependencies if requirements.txt exists
if [ -f "requirements.txt" ]; then
  echo "📦 Installing dependencies from requirements.txt..."
  pip install -r requirements.txt
else
  echo "⚠️  requirements.txt not found, skipping dependency installation."
fi

# Ensure PID lookup doesn't break script on non-zero exit
PID=$(pgrep -f "$SCRIPT_NAME" || true)

if [ -n "$PID" ]; then
  echo "⚠️  Detected running process(es) for $SCRIPT_NAME (PID(s): $PID), stopping..."
  kill -9 $PID || true
  echo "✅ Stopped old process(es)."
else
  echo "✅ No existing process found for $SCRIPT_NAME."
fi

# Start new process
echo "🚀 Starting $SCRIPT_NAME (logs -> $LOG_FILE)"
nohup env PYTHONUNBUFFERED=1 python "$SCRIPT_NAME" > "$LOG_FILE" 2>&1 &
NEW_PID=$!

echo "✅ New process started (PID: $NEW_PID)"
echo "📄 Log file: $LOG_FILE"
