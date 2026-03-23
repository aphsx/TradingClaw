"""
Regime Detector v3 — Rule-Based Market Regime Classification
=============================================================
Replaces Gaussian HMM (unsupervised, N/A accuracy).

Rule-based: deterministic, interpretable, consistent.
No training required — rules are always active.

4 Regimes (priority order):
  VOLATILE      — ATR spike or rapid price movement
  TRENDING_UP   — ADX + EMA alignment + positive momentum
  TRENDING_DOWN — ADX + EMA alignment + negative momentum
  RANGING       — Default (low ADX, mixed signals)

Confidence: 0.0-1.0 based on how clearly criteria are met.
"""
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings('ignore')

import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Public regime constants
TRENDING_UP   = 0
RANGING       = 1
VOLATILE      = 2
TRENDING_DOWN = 3

REGIME_NAMES = {
    TRENDING_UP:   "Trending-Up",
    RANGING:       "Ranging",
    VOLATILE:      "Volatile",
    TRENDING_DOWN: "Trending-Down",
}
REGIME_COLORS = {
    TRENDING_UP:   "#1D9E75",
    RANGING:       "#378ADD",
    VOLATILE:      "#D85A30",
    TRENDING_DOWN: "#C0392B",
}

# ─── Thresholds ──────────────────────────────────────────────
ADX_TREND_MIN       = 23.0   # ADX must exceed this to be "trending"
ADX_STRONG_TREND    = 35.0   # ADX above this = high confidence trend
ADX_RANGE_MAX       = 20.0   # ADX below this = clear ranging
VOLATILE_ATR_RATIO  = 1.75   # ATR/avg_ATR above this = volatile
VOLATILE_HIGH_RATIO = 2.50   # ATR ratio above this = very volatile
DI_MIN_SPREAD       = 3.0    # Minimum |+DI - -DI| to confirm direction
MOMENTUM_MIN        = 0.3    # Minimum |momentum_10| for trend confirmation (%)
TREND_SIGNAL_MIN    = 4      # Out of 5 signals must agree for trending
# ─────────────────────────────────────────────────────────────


class RegimeDetector:
    """
    Rule-based regime detector.

    Maintains the same public interface as the old HMM version so that
    backtest/engine.py and main.py require minimal changes.

    fit()  → no-op (rules don't need training), returns stats dict
    predict() → Series of regime ints
    predict_with_confidence() → DataFrame with regime + confidence
    get_current_regime() → dict with current regime + confidence
    """

    def __init__(self):
        self.is_fitted = True  # Always ready — no training needed
        self._n_states = 4

    # ─── Public API ──────────────────────────────────────────

    def fit(self, df: pd.DataFrame, features: pd.DataFrame) -> dict:
        """
        No-op for rule-based detector.
        Returns a stats dict matching the old HMM interface for compatibility.
        """
        self.is_fitted = True
        if len(features) == 0:
            return {"error": "Empty features"}

        # Compute distribution on training set (for reporting)
        sample_regimes = self.predict(features)
        dist = {REGIME_NAMES[r]: int((sample_regimes == r).sum())
                for r in REGIME_NAMES}

        return {
            "model":              "RuleBased",
            "n_states":           self._n_states,
            "state_map":          {str(i): REGIME_NAMES[i] for i in range(4)},
            "regime_distribution": dist,
            "holdout_unique_regimes": 4,
            "cv_accuracy":        "Rule-based (deterministic)",
            "holdout_accuracy":   "Rule-based (deterministic)",
        }

    def predict(self, features: pd.DataFrame) -> pd.Series:
        """Predict regime for each bar. Returns Series of regime ints."""
        if features.empty:
            return pd.Series(dtype=int)

        regimes = features.apply(
            lambda row: self._classify(row)[0], axis=1
        ).astype(int)
        return regimes

    def predict_with_confidence(self, features: pd.DataFrame) -> pd.DataFrame:
        """Predict regime + confidence per bar."""
        if features.empty:
            return pd.DataFrame()

        results = features.apply(
            lambda row: pd.Series(self._classify(row)), axis=1
        )
        results.columns = ['regime', 'confidence']

        result = pd.DataFrame(index=features.index)
        result['regime']      = results['regime'].astype(int)
        result['regime_name'] = result['regime'].map(REGIME_NAMES)
        result['confidence']  = results['confidence'].clip(0.0, 1.0)

        # Pseudo-probabilities: 1-hot-ish with soft confidence
        for r, name in REGIME_NAMES.items():
            col = f"prob_{name.lower().replace('-', '_').replace(' ', '_')}"
            is_this = (result['regime'] == r).astype(float)
            conf = result['confidence']
            other_prob = (1 - conf) / max(self._n_states - 1, 1)
            result[col] = is_this * conf + (1 - is_this) * other_prob

        return result

    def get_current_regime(self, features: pd.DataFrame) -> dict:
        """Get most recent regime with confidence and transition info."""
        try:
            result = self.predict_with_confidence(features)
            if result.empty:
                return self._default_regime()

            latest      = result.iloc[-1]
            regime_int  = int(latest['regime'])
            confidence  = float(latest['confidence'])

            # Transition: last 5 bars spanning >2 regimes
            if len(result) >= 5:
                recent_regimes    = result['regime'].values[-5:]
                is_transitioning  = len(set(recent_regimes)) > 2
            else:
                is_transitioning = False

            probs = {}
            for r, rname in REGIME_NAMES.items():
                col = f"prob_{rname.lower().replace('-', '_').replace(' ', '_')}"
                probs[rname] = float(latest.get(col, 0.25))

            return {
                "regime":       regime_int,
                "regime_name":  REGIME_NAMES.get(regime_int, "Ranging"),
                "confidence":   confidence,
                "probabilities": probs,
                "transitioning": is_transitioning,
            }
        except Exception:
            return self._default_regime()

    def get_factor_weights(self, features: pd.DataFrame) -> dict:
        """Return recommended factor weights for the current regime."""
        from strategies.signal_engine import REGIME_WEIGHTS, DEFAULT_WEIGHTS
        try:
            current = self.get_current_regime(features)
            regime  = current.get('regime', -1)
            return REGIME_WEIGHTS.get(regime, DEFAULT_WEIGHTS)
        except Exception:
            return DEFAULT_WEIGHTS

    # ─── Core Classification Logic ───────────────────────────

    def _classify(self, row) -> tuple:
        """
        Classify a single bar into a regime + confidence.

        Returns: (regime_int, confidence_float)

        Priority:
          1. VOLATILE  (ATR spike — overrides everything)
          2. TRENDING_UP / TRENDING_DOWN  (ADX + alignment)
          3. RANGING   (default)
        """
        # ── Extract features ──
        adx        = float(row.get('adx', 20) or 20)
        plus_di    = float(row.get('plus_di', 25) or 25)
        minus_di   = float(row.get('minus_di', 25) or 25)
        vol_ratio  = float(row.get('volatility_ratio', 1.0) or 1.0)
        e9_slope   = float(row.get('ema_9_slope', 0) or 0)
        e21_slope  = float(row.get('ema_21_slope', 0) or 0)
        mom10      = float(row.get('momentum_10', 0) or 0)
        rsi        = float(row.get('rsi_14', 50) or 50)
        bb_width   = float(row.get('bb_width', 5) or 5)
        obv_slope  = float(row.get('obv_slope', 0) or 0)

        # ── 1. VOLATILE: ATR ratio spike ──
        if vol_ratio >= VOLATILE_ATR_RATIO:
            # Confidence scales with how far above threshold
            raw = (vol_ratio - VOLATILE_ATR_RATIO) / (VOLATILE_HIGH_RATIO - VOLATILE_ATR_RATIO)
            conf = 0.55 + min(raw, 1.0) * 0.40
            return VOLATILE, conf

        # ── 2. TRENDING: ADX + direction agreement ──
        di_spread = plus_di - minus_di  # >0 = bullish, <0 = bearish

        if adx >= ADX_TREND_MIN and abs(di_spread) >= DI_MIN_SPREAD:
            # Gather bullish signals
            bullish_signals = [
                di_spread > 0,                         # +DI > -DI
                e9_slope > 0,                          # Short EMA trending up
                e21_slope > 0,                         # Medium EMA trending up
                mom10 > MOMENTUM_MIN,                  # Positive momentum
                rsi > 45,                              # RSI not in bear territory
            ]
            # Gather bearish signals
            bearish_signals = [
                di_spread < 0,                         # -DI > +DI
                e9_slope < 0,
                e21_slope < 0,
                mom10 < -MOMENTUM_MIN,
                rsi < 55,
            ]

            bull_count = sum(bullish_signals)
            bear_count = sum(bearish_signals)

            if bull_count >= TREND_SIGNAL_MIN:
                # Confidence: blend ADX strength + signal agreement
                adx_norm  = min((adx - ADX_TREND_MIN) / (ADX_STRONG_TREND - ADX_TREND_MIN), 1.0)
                sig_norm  = (bull_count - TREND_SIGNAL_MIN) / (len(bullish_signals) - TREND_SIGNAL_MIN + 1e-6)
                conf = 0.55 + adx_norm * 0.25 + sig_norm * 0.20
                return TRENDING_UP, min(conf, 1.0)

            if bear_count >= TREND_SIGNAL_MIN:
                adx_norm  = min((adx - ADX_TREND_MIN) / (ADX_STRONG_TREND - ADX_TREND_MIN), 1.0)
                sig_norm  = (bear_count - TREND_SIGNAL_MIN) / (len(bearish_signals) - TREND_SIGNAL_MIN + 1e-6)
                conf = 0.55 + adx_norm * 0.25 + sig_norm * 0.20
                return TRENDING_DOWN, min(conf, 1.0)

        # ── 3. RANGING: Default ──
        # Confidence is higher when ADX is clearly low
        if adx < ADX_RANGE_MAX:
            conf = 0.60 + (ADX_RANGE_MAX - adx) / ADX_RANGE_MAX * 0.35
        else:
            # Mixed signals (ADX medium, but trend conditions not met)
            conf = 0.50 + max(0, (ADX_TREND_MIN - adx) / ADX_TREND_MIN) * 0.15
        return RANGING, min(conf, 0.95)

    def _default_regime(self) -> dict:
        return {
            "regime":        RANGING,
            "regime_name":   "Ranging",
            "confidence":    0.50,
            "probabilities": {n: 0.25 for n in REGIME_NAMES.values()},
            "transitioning": False,
        }
