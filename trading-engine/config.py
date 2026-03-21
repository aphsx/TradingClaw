import os

# ─── Binance ───
API_KEY = os.getenv("BINANCE_API_KEY", "")
SECRET_KEY = os.getenv("BINANCE_SECRET_KEY", "")
USE_TESTNET = os.getenv("USE_TESTNET", "false").lower() == "true"
BASE_URL = "https://testnet.binance.vision" if USE_TESTNET else "https://api.binance.com"

# ─── Database ───
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_NAME = os.getenv("DB_NAME", "regime_trader")
DB_USER = os.getenv("DB_USER", "trader")
DB_PASSWORD = os.getenv("DB_PASSWORD", "trader_pass_2026")

# ─── Redis ───
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

# ─── Trading ───
TRADING_MODE = os.getenv("TRADING_MODE", "live")
SYMBOL = os.getenv("SYMBOL", "BTCUSDT")
TIMEFRAME = os.getenv("TIMEFRAME", "1h")
LOOKBACK_DAYS = int(os.getenv("LOOKBACK_DAYS", "180"))

# ─── Regime ───
ADX_THRESHOLD = 20
VOLATILITY_THRESHOLD = 1.5

# ─── Fees ───
MAKER_FEE = 0.001
TAKER_FEE = 0.001
SLIPPAGE = 0.0005
TOTAL_FEE_PER_TRADE = (TAKER_FEE * 2) + SLIPPAGE
FEE_MULTIPLIER = 3.0

# ─── Risk ───
INITIAL_CAPITAL = float(os.getenv("INITIAL_CAPITAL", "10000"))
RISK_PER_TRADE = 0.02
MAX_DAILY_LOSS = 0.05
MAX_DRAWDOWN = 0.15
MAX_OPEN_TRADES = 3

# ─── Trend Strategy ───
TREND_EMA_FAST = 9
TREND_EMA_SLOW = 21
TREND_ATR_SL_MULT = 1.5
TREND_ATR_TP_MULT = 3.0

# ─── Range Strategy ───
RANGE_BB_PERIOD = 20
RANGE_BB_STD = 2.0
RANGE_RSI_OVERSOLD = 30
RANGE_RSI_OVERBOUGHT = 70
RANGE_ATR_SL_MULT = 1.0
RANGE_ATR_TP_MULT = 1.5

# ─── Volatile Strategy ───
VOL_VOLUME_SPIKE = 2.0
VOL_ATR_SL_MULT = 2.0
VOL_ATR_TP_MULT = 4.0

# ─── Loop ───
LOOP_INTERVAL_SECONDS = 60
MONITOR_INTERVAL_SECONDS = 15  # Check positions every 15s
