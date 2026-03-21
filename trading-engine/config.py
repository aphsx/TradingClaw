"""
Configuration - reads from environment variables (Docker)
"""
import os

# ─── Binance API ───
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

# ─── Trading ───
TRADING_MODE = os.getenv("TRADING_MODE", "backtest")  # backtest / live / paper
SYMBOL = os.getenv("SYMBOL", "BTCUSDT")
TIMEFRAME = os.getenv("TIMEFRAME", "1h")
LOOKBACK_DAYS = int(os.getenv("LOOKBACK_DAYS", "180"))

# ─── Regime Detection ───
ADX_THRESHOLD = 20
VOLATILITY_THRESHOLD = 1.5
HMM_STATES = 3

# ─── Fees ───
MAKER_FEE = 0.001
TAKER_FEE = 0.001
SLIPPAGE = 0.0005
TOTAL_FEE_PER_TRADE = (TAKER_FEE * 2) + SLIPPAGE
FEE_MULTIPLIER = 3.0

# ─── Risk Management ───
INITIAL_CAPITAL = float(os.getenv("INITIAL_CAPITAL", "10000"))
RISK_PER_TRADE = 0.02
MAX_DAILY_LOSS = 0.05
MAX_DRAWDOWN = 0.15
MAX_OPEN_TRADES = 3

# ─── Strategy: Trend ───
TREND_EMA_FAST = 9
TREND_EMA_SLOW = 21
TREND_ATR_PERIOD = 14
TREND_ATR_SL_MULT = 1.5
TREND_ATR_TP_MULT = 3.0
TREND_ATR_TRAIL_MULT = 2.0

# ─── Strategy: Range ───
RANGE_BB_PERIOD = 20
RANGE_BB_STD = 2.0
RANGE_RSI_PERIOD = 14
RANGE_RSI_OVERSOLD = 30
RANGE_RSI_OVERBOUGHT = 70
RANGE_ATR_SL_MULT = 1.0
RANGE_ATR_TP_MULT = 1.5

# ─── Strategy: Volatile ───
VOL_VOLUME_SPIKE = 2.0
VOL_MOMENTUM_PERIOD = 10
VOL_ATR_SL_MULT = 2.0
VOL_ATR_TP_MULT = 4.0

# ─── Live Trading Loop ───
LOOP_INTERVAL_SECONDS = 60  # Check every N seconds in live mode
