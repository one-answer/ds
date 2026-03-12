import os


def _env_to_bool(name, default=False):
	value = os.getenv(name)
	if value is None:
		return default
	return str(value).strip().lower() in {"1", "true", "yes", "on", "y"}

# Broker/order tag used in create_market_order params; can be overridden by env var BROKER_TAG
BROKER_TAG = os.getenv('BROKER_TAG', 'f1ee03b510d5SUDE')

# OKX margin mode (e.g., 'cross' or 'isolated')
MARGIN_MODE = os.getenv('MARGIN_MODE', 'cross')

# CCXT default type for OKX (e.g., 'swap' or 'spot')
DEFAULT_TYPE = os.getenv('DEFAULT_TYPE', 'swap')

# DeepSeek model name (can be overridden by env)
DEEPSEEK_MODEL = os.getenv('DEEPSEEK_MODEL', 'deepseek-chat')

# Trading mode override for strategy scripts: True = simulated mode, False = live mode
TRADE_TEST_MODE = _env_to_bool('TRADE_TEST_MODE', False)

