import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from root of project (TradingClaw/.env) — single source of truth.
# Falls back to trading-engine/.env if root file not found (legacy support).
# Inside Docker env vars are injected directly, so load_dotenv() is a no-op there.
_root_env = Path(__file__).resolve().parent.parent / ".env"
_local_env = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=_root_env if _root_env.exists() else _local_env)

# ─── OKX API ───
API_KEY = os.getenv("OKX_API_KEY", "")
SECRET_KEY = os.getenv("OKX_SECRET_KEY", "")
PASSPHRASE = os.getenv("OKX_PASSPHRASE", "")
USE_FUTURES = os.getenv("USE_FUTURES", "false").lower() == "true"
USE_TESTNET = os.getenv("USE_TESTNET", "false").lower() == "true"

BASE_URL = "" # Not used anymore since we will rely purely on CCXT


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

# ─── Capital Tiers ───────────────────────────────────────────
# (max_capital_usd, risk_pct, min_notional_usd, label)
# Risk % scales UP for small accounts so trades are still meaningful.
# min_notional is the smallest order value the engine will attempt.
# Binance Futures minimum notional is ~$5 for most pairs.
CAPITAL_TIERS = [
    # (max_capital, risk_pct, min_order_usd, label)
    # min_order คือ order ขั้นต่ำสุดที่ bot จะ place (ยก size ขึ้นมาถึงค่านี้ถ้า Kelly ให้น้อยกว่า)
    (50,           0.15,  6.0,  "Micro    <$50"),    # $30  → Kelly ~$0.09  → min order $6
    (200,          0.12, 10.0,  "Small    $50-200"), # $100 → Kelly ~$0.24  → min order $10
    (500,          0.08, 15.0,  "Medium   $200-500"),# $300 → Kelly ~$0.72  → min order $15
    (2_000,        0.05, 25.0,  "Standard $500-2k"), # $1k  → Kelly ~$3.0   → min order $25
    (float("inf"), 0.02, 50.0,  "Large    $2k+"),    # $10k → Kelly ~$40.0  → min order $50
]

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
# INITIAL_CAPITAL is used ONLY as a fallback when the live balance
# cannot be fetched from Binance (e.g. network error at startup).
# Set to 0 to force auto-detect; any non-zero value acts as a fallback.
INITIAL_CAPITAL = float(os.getenv("INITIAL_CAPITAL", "0"))
# At 5x leverage, 1% of margin = 5% actual exposure → safer for futures
RISK_PER_TRADE = 0.015  # 1.5% risk per trade — meaningful at 10x leverage
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
RANGE_BB_STD_RANGE = 1.5   # 1.5σ trigger zone for range entries (more signals)
RANGE_RSI_OVERSOLD = 35    # Widened from 30: easier to trigger, still meaningful
RANGE_RSI_OVERBOUGHT = 65  # Widened from 70
# 1.5x ATR for SL: crypto 5x lev needs more room than 1.0x
RANGE_ATR_SL_MULT = 1.5
RANGE_ATR_TP_MULT = 1.5

# ─── Volatile Strategy ───
# Require stronger volume confirmation (2.5x vs 2.0x) to cut false positives
VOL_VOLUME_SPIKE = 2.5
VOL_ATR_SL_MULT = 2.0
VOL_ATR_TP_MULT = 4.0

# ─── Loop ───
LOOP_INTERVAL_SECONDS = 60
MONITOR_INTERVAL_SECONDS = 15  # Check positions every 15s

# ─── Multi-Symbol & Multi-Timeframe ───
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
TIMEFRAMES = ["1h", "4h"]

# ─── Trailing Stops ───
TRAILING_STOP_ACTIVATION = 0.005  # Activate trailing stop at 0.5% profit
TRAILING_STOP_DISTANCE = 0.003    # Trail 0.3% behind price

# ─── Position Management ───
MAX_POSITION_AGE_HOURS = 24       # Close if open >24h with no progress
MIN_WIN_RATE_SAMPLE = 20          # Minimum trades before Kelly sizing kicks in
KELLY_FRACTION = 0.5              # Use half Kelly to be conservative
MAX_CORRELATED_POSITIONS = 2      # Max positions with correlation > 0.7

# ─── Volatility Adjustment ───
VOLATILITY_SCALE_HIGH = 1.5       # Scale down position if vol > 1.5x average
VOLATILITY_SCALE_LOW = 0.5        # Scale up position if vol < 0.5x average

# ─── Futures Settings ───
LEVERAGE = int(os.getenv("LEVERAGE", "10"))         # 10x leverage — meaningful PnL on small capital
MARGIN_TYPE = os.getenv("MARGIN_TYPE", "ISOLATED")  # ISOLATED or CROSSED
MAX_MARGIN_RATIO = 0.75                              # Warn when margin ratio > 75%
EMERGENCY_MARGIN_RATIO = 0.90                        # Force close all at 90%
LIQUIDATION_SAFETY_PCT = 0.15                        # SL must be 15% away from liquidation

# ─── Funding Rate ───
MAX_FUNDING_RATE = 0.001       # Skip entry if funding > 0.1% per 8h
FUNDING_CHECK_INTERVAL = 300   # Check funding every 5 min

# ─── Multi-Factor Signal Engine ───
COMPOSITE_ENTRY_THRESHOLD = 0.40    # Min |composite score| to enter (default fallback)
COMPOSITE_STRONG_THRESHOLD = 0.70   # Score >= this = high-confidence (fires immediately)

# Issue #4: Regime-specific entry thresholds.
# Volatile: higher threshold because noise floor is higher (more false positives).
# Ranging:  lower threshold because MeanReversion signals are structurally weaker.
# Trending: standard — trend signals are the most reliable.
COMPOSITE_THRESHOLD_BY_REGIME = {
    0: 0.40,  # Trending-Up:   standard (trend signals are reliable)
    1: 0.33,  # Ranging:       lower   (MR signals are directionally weaker)
    2: 0.50,  # Volatile:      higher  (noise floor is high → demand more conviction)
    3: 0.40,  # Trending-Down: standard
}

# Factor group weights (default; adjusted by regime at runtime)
FACTOR_WEIGHT_TREND     = 0.25
FACTOR_WEIGHT_MEAN_REV  = 0.20
FACTOR_WEIGHT_MOMENTUM  = 0.20
FACTOR_WEIGHT_VOLUME    = 0.20
FACTOR_WEIGHT_VOLATILITY = 0.15

# ─── HMM Regime Detection ───
HMM_N_STATES         = 4      # Trend-Up, Trend-Down, Range, Volatile
HMM_RETRAIN_BARS     = 500    # Retrain every N new bars per symbol
HMM_N_ITER           = 200    # Max EM iterations

# ─── ML Ensemble Filter ───
ML_WALK_FORWARD_SPLITS = 5    # TimeSeriesSplit folds
ML_MIN_SAMPLES         = 50   # Min trades before training
ML_THRESHOLD           = 0.55 # Default threshold (tuned per retrain)

# ─── Scaled Entry / Exit ───
SCALED_ENTRY_LEGS      = 3              # 1=market only, 3=split entry
# v3: No partial TPs for Trend/Breakout — pure trailing stop lets winners run.
# MeanRev uses fixed TP at EMA21. These constants kept for backtest engine compatibility.
PARTIAL_TP1_R          = 3.0
PARTIAL_TP2_R          = 3.0
PARTIAL_TP_FRACTIONS   = [0.0, 0.0, 1.0]   # 100% at trailing stop — no partials

# ─── Dynamic Stops ───
CHANDELIER_PERIOD      = 22
CHANDELIER_MULT        = 3.0
SWING_LOOKBACK         = 15   # Bars to look for swing high/low

# ─── Portfolio Risk ───
MAX_PORTFOLIO_HEAT     = 0.06  # Max 6% capital at risk across all positions
DRAWDOWN_SCALE_LEVELS  = [0.05, 0.08, 0.12, 0.15]  # Drawdown thresholds
DRAWDOWN_SIZE_FACTORS  = [1.0,  0.75, 0.50, 0.25]  # Corresponding size multipliers

# ─── Regime Monitoring & Circuit Breakers ───
# Prevents trading in a regime that has been consistently losing.
REGIME_MIN_CONFIDENCE       = 0.55   # Skip entry if HMM confidence < this
REGIME_REDUCE_AFTER_LOSSES  = 3      # After N consecutive losses in a regime: size × 0.5
REGIME_DISABLE_AFTER_LOSSES = 5      # After N consecutive losses: disable regime for REGIME_COOLDOWN_BARS
REGIME_COOLDOWN_BARS        = 20     # Bars to wait before re-enabling a disabled regime
REGIME_CIRCUIT_R_THRESHOLD  = -4.0   # Cumulative R < this also triggers disable

# ─── Trade Health Monitoring ───
TRADE_HEALTH_MIN_HOURS      = 3      # Minimum hours before health check activates
TRADE_HEALTH_R_THRESHOLD    = -0.35  # If at this R-multiple, tighten SL
TRADE_HEALTH_SL_TIGHTEN_PCT = 0.50   # Move SL this fraction toward entry price

# ─── v3 Strategy Parameters ──────────────────────────────────

# Strategy 1: Trend Follow
TREND_ADX_MIN              = 25     # ADX must be above this to enter trend trade
TREND_EMA_ALIGN_REQUIRED   = 3      # Out of 3 EMA alignments (9>21, 21>50, 50>200)

# Strategy 2: Volatility Breakout
BREAKOUT_DONCHIAN_PERIOD   = 20     # Donchian channel lookback
BREAKOUT_VOLUME_MULT       = 1.5    # Volume must be >= this multiple of average
BREAKOUT_ATR_EXPAND        = 1.05   # ATR must be expanding by this ratio

# Strategy 3: Mean Reversion (very tight — only RANGING regime)
MR_BB_PCT_MAX              = 0.08   # BB %B must be <= this for long (extreme oversold)
MR_RSI_MAX                 = 28     # RSI must be <= this for long
MR_ADX_MAX                 = 20     # ADX must be <= this (truly ranging)
MR_CONFIDENCE_MIN          = 0.65   # Regime confidence must be >= this for MR

# General signal gate
REGIME_CONFIDENCE_MIN      = 0.52   # Skip ALL entries if regime confidence below this
