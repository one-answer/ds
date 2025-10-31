#!/bin/bash
# Wrapper for starting deepseek_doge using common runner

SCRIPT_NAME="deepseek_doge.py"
LOG_FILE="./app_doge.log"

# Optional: override ENV_NAME and PYTHON_VERSION here if needed
ENV_NAME="ds"
PYTHON_VERSION="3.10"

# Call common runner
./run_common.sh" "$SCRIPT_NAME" "$LOG_FILE" "$ENV_NAME" "$PYTHON_VERSION"
