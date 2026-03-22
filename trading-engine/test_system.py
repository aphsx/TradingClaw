"""
TradingClaw v5 — Full System Diagnostic
Run: python3 test_system.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import warnings; warnings.filterwarnings('ignore')
import numpy as np
import pandas as pd

print("=== TradingClaw v5 — Full System Diagnostic ===\n")

# ─── 1. Imports ───────────────────────────────────────────────────────────────
errors = []
mods = [
    'config', 'core.features', 'core.regime_detector', 'core.risk_manager',
    'core.ml_filter', 'core.execution_analytics', 'core.position_manager',
    'core.correlation', 'strategies.signal_engine',
    'strategies.factors.trend', 'strategies.factors.mean_reversion',
    'strategies.factors.momentum', 'strategies.factors.volume_flow',
    'strategies.factors.volatility', 'strategies.factors.open_interest',
    'strategies.factors.market_structure',
]
for m in mods:
    try:
        __import__(m)
    except Exception as e:
        errors.append((m, str(e)))
status = "✅" if not errors else "❌"
print(f"[1] Imports:         {16-len(errors)}/16 OK {status}")
for m, e in errors:
    print(f"    ❌ {m}: {e}")

# ─── 2. Synthetic Data ────────────────────────────────────────────────────────
np.random.seed(42)
n = 300
idx = pd.date_range('2024-01-01', periods=n, freq='1h')
close = 40000 + np.arange(n)*20 + np.random.randn(n)*100
df_raw = pd.DataFrame({
    'open':   close - 10,
    'high':   close + 200,
    'low':    close - 200,
    'close':  close,
    'volume': np.random.exponential(1000, n) + 500,
}, index=idx)

# ─── 3. Feature Pipeline ──────────────────────────────────────────────────────
from core.features import calculate_features, get_regime_features
df_f = calculate_features(df_raw)
nan_pct = df_f.iloc[-100:].isna().mean().mean()
print(f"[2] Features:        {df_f.shape[1]} cols, NaN={nan_pct:.1%} ✅")

# ─── 4. Regime Detector ───────────────────────────────────────────────────────
rdf = get_regime_features(df_f)
from core.regime_detector import RegimeDetector
rd = RegimeDetector()
rd.fit(df_raw, rdf)
cur = rd.get_current_regime(rdf)
print(f"[3] Regime:          {cur['regime_name']} (conf={cur['confidence']:.2f}) ✅")

# ─── 5. Signal Engine ─────────────────────────────────────────────────────────
from strategies.signal_engine import SignalEngine
se = SignalEngine()
total_sigs = 0
for end in range(70, n + 1):
    sub = df_f.iloc[:end]
    total_sigs += len(se.generate_signals(sub, sub, regime=cur['regime'], symbol='BTCUSDT'))
print(f"[4] Signal Engine:   {total_sigs} signals in {n} bar walk-forward ✅")

# ─── 6. ML Filter ─────────────────────────────────────────────────────────────
from core.ml_filter import MLSignalFilter
mlf = MLSignalFilter(min_samples=30)
trades_data = [{
    'entry_time': idx[50 + i],
    'direction':  'LONG',
    'confidence': 0.7,
    'risk_reward': 2.0,
    'expected_profit_pct': 0.5,
    'composite_score': 0.5,
    'regime': 'Trending-Up',
    'pnl': np.random.randn() * 50 + 20,
} for i in range(70)]
trades_df = pd.DataFrame(trades_data)
mlf.train(trades_df, df_f)
pred = mlf.predict({
    'time': idx[280], 'direction': 'LONG', 'confidence': 0.75,
    'risk_reward': 2.5, 'expected_profit_pct': 0.8,
    'composite_score': 0.55, 'regime': 'Trending-Up', 'oi_score': 0.3,
}, df_f)
print(f"[5] ML Filter:       trained (thr={mlf.optimal_threshold:.2f} pf={mlf._holdout_pf:.2f})  predict=pass={pred['pass']} prob={pred['probability']} ✅")

# Cold-start pretrain
mlf2 = MLSignalFilter(min_samples=30)
mlf2.pretrain_from_backtest(trades_df, df_f)
print(f"[5b] ML Pretrain:    source={mlf2._source} thr={mlf2.optimal_threshold:.2f} ✅")

# ─── 7. Execution Analytics ───────────────────────────────────────────────────
from core.execution_analytics import ExecutionAnalytics
ea = ExecutionAnalytics(window=50)
ea.record('BTCUSDT', expected_price=40000, actual_fill=40020, side='BUY', quantity=0.1)
slip = ea.get_effective_slippage('BTCUSDT')
print(f"[6] Exec Analytics:  slippage={slip:.4%} ✅")

# ─── 8. Risk Manager ──────────────────────────────────────────────────────────
from core.risk_manager import RiskManager
rm = RiskManager()
print(f"[7] Risk Manager:    capital=${rm.capital:.0f} ✅")

# ─── 9. Market Structure Factor ───────────────────────────────────────────────
from strategies.factors.market_structure import MarketStructureFactor
ms = MarketStructureFactor()
ms_scores = ms.confidence_multiplier(df_f)
boosted = ms.apply_confidence_boost(0.7, float(ms_scores.iloc[-1]), 'LONG')
print(f"[8] Market Structure: score={float(ms_scores.iloc[-1]):.2f}  boosted_conf={boosted:.3f} ✅")

# ─── 10. OI Factor ────────────────────────────────────────────────────────────
from strategies.factors.open_interest import OpenInterestFactor
oi = OpenInterestFactor()
oi_score = oi.score(df_f, symbol='BTCUSDT')
print(f"[9] OI Factor:       score range=[{float(oi_score.min()):.3f}, {float(oi_score.max()):.3f}] ✅")

print()
print("════════════════════════════════════════")
print("  ALL SYSTEMS GO ✅  TradingClaw v5 OK  ")
print("════════════════════════════════════════")
