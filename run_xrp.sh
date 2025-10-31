#!/bin/bash
# Wrapper for starting deepseek_xrp using common runner

SCRIPT_NAME="deepseek_xrp.py"
LOG_FILE="./app_xrp.log"

# Optional: override ENV_NAME and PYTHON_VERSION here if needed
ENV_NAME="ds"
PYTHON_VERSION="3.10"

# Call common runner
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"$DIR/run_common.sh" "$SCRIPT_NAME" "$LOG_FILE" "$ENV_NAME" "$PYTHON_VERSION"
