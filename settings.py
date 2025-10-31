import os

# Broker/order tag used in create_market_order params; can be overridden by env var BROKER_TAG
BROKER_TAG = os.getenv('BROKER_TAG', 'f1ee03b510d5SUDE')

# OKX margin mode (e.g., 'cross' or 'isolated')
MARGIN_MODE = os.getenv('MARGIN_MODE', 'cross')

# CCXT default type for OKX (e.g., 'swap' or 'spot')
DEFAULT_TYPE = os.getenv('DEFAULT_TYPE', 'swap')

# DeepSeek model name (can be overridden by env)
DEEPSEEK_MODEL = os.getenv('DEEPSEEK_MODEL', 'deepseek-chat')

