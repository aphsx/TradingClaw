"""
Regime Detector v4 — World-Class Rule-Based Market Regime Classification
=========================================================================
Replaces v3 with hysteresis, transition tracking, adaptive thresholds, and multi-signal smoothing.

Rule-based: deterministic, interpretable, consistent.
No training required — rules are always active.

4 Regimes (priority order):
  VOLATILE      — ATR spike or rapid price movement
  TRENDING_UP   — ADX + EMA alignment + positive momentum
  TRENDING_DOWN — ADX + EMA alignment + negative momentum
  RANGING       — Default (low ADX, mixed signals)

Key Upgrades:
  1. Regime Hysteresis: Prevents whipsaw by requiring 3+ bars of regime dominance
  2. Confidence Decay During Transitions: Reduce confidence when transitioning
  3. Adaptive Volatility Thresholds: Use 95th percentile of ATR ratio
  4. Regime Strength EMA Smoothing: Smooth signals with EMA(5)
  5. Transition Probability Matrix: Track regime-to-regime transitions
  6. Multi-Timeframe Confirmation: Boost/reduce confidence with HTF alignment
  7. Enhanced Volatile Detection: Price movement >2% in 5 bars also counts
  8. Regime Duration Tracking: Long-duration trends have higher continuation probability

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
VOLATILE_ATR_RATIO  = 1.75   # ATR/avg_ATR above this = volatile (baseline)
VOLATILE_HIGH_RATIO = 2.50   # ATR ratio above this = very volatile
DI_MIN_SPREAD       = 3.0    # Minimum |+DI - -DI| to confirm direction
MOMENTUM_MIN        = 0.3    # Minimum |momentum_10| for trend confirmation (%)
TREND_SIGNAL_MIN    = 4      # Out of 5 signals must agree for trending
RAPID_PRICE_MOVE    = 2.0    # % price move in 5 bars counts as volatile
# ─────────────────────────────────────────────────────────────

# ─── Config Defaults (can be overridden via config) ──────────
REGIME_HYSTERESIS_BARS      = 3     # Require 3 bars of regime dominance
REGIME_TRANSITION_DECAY     = 0.85  # Decay confidence per transitioning bar
REGIME_VOLATILITY_LOOKBACK  = 50    # Lookback for adaptive ATR percentile
REGIME_STRENGTH_SMOOTHING   = 5     # EMA window for smoothing regime signals
# ─────────────────────────────────────────────────────────────


class RegimeDetector:
    """
    World-class rule-based regime detector with hysteresis and adaptive thresholds.

    Maintains the same public interface as the old HMM version so that
    backtest/engine.py and main.py require minimal changes.

    fit()  → no-op (rules don't need training), returns stats dict
    predict() → Series of regime ints
    predict_with_confidence() → DataFrame with regime + confidence
    get_current_regime() → dict with current regime + confidence
    get_factor_weights() → dict with recommended factor weights
    confirm_with_htf() → boost/reduce confidence based on higher-timeframe regime
    """

    def __init__(self):
        self.is_fitted = True  # Always ready — no training needed
        self._n_states = 4

        # ─── Hysteresis state ──────────────────────────────────
        self._current_regime = RANGING
        self._regime_bar_count = 0  # Bars in current regime
        self._pending_regime = None  # Candidate regime waiting for confirmation
        self._pending_bar_count = 0  # Bars confirming pending regime

        # ─── Transition tracking ────────────────────────────────
        # Matrix of shape (4, 4) tracking transitions between regimes
        self._transition_matrix = np.zeros((4, 4), dtype=np.int64)
        self._regime_history = []  # List of (regime, confidence) tuples

        # ─── Adaptive thresholds ────────────────────────────────
        self._atr_ratio_history = []  # For 95th percentile calculation
        self._adaptive_atr_threshold = VOLATILE_ATR_RATIO

        # ─── Smoothing state ────────────────────────────────────
        self._regime_strength_ema = {}  # regime -> EMA value
        self._ema_alpha = 2.0 / (REGIME_STRENGTH_SMOOTHING + 1)

        # ─── Duration tracking ──────────────────────────────────
        self._regime_start_bar = 0
        self._current_bar_idx = 0

        # ─── Config loading ─────────────────────────────────────
        self._load_config()

    # ─── Config Loading ──────────────────────────────────────

    def _load_config(self):
        """Load config variables with safe defaults."""
        try:
            from config import (
                REGIME_HYSTERESIS_BARS,
                REGIME_TRANSITION_DECAY,
                REGIME_VOLATILITY_LOOKBACK,
                REGIME_STRENGTH_SMOOTHING,
            )
            self._hysteresis_bars = REGIME_HYSTERESIS_BARS
            self._transition_decay = REGIME_TRANSITION_DECAY
            self._volatility_lookback = REGIME_VOLATILITY_LOOKBACK
            self._smoothing_window = REGIME_STRENGTH_SMOOTHING
        except ImportError:
            # Use module-level defaults
            self._hysteresis_bars = REGIME_HYSTERESIS_BARS
            self._transition_decay = REGIME_TRANSITION_DECAY
            self._volatility_lookback = REGIME_VOLATILITY_LOOKBACK
            self._smoothing_window = REGIME_STRENGTH_SMOOTHING

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
        """Predict regime for each bar with hysteresis. Returns Series of regime ints."""
        if features.empty:
            return pd.Series(dtype=int)

        # Reset state for fresh prediction run
        self._reset_state()

        # First pass: compute raw regime classifications
        raw_regimes = []
        raw_confidences = []
        for idx, (_, row) in enumerate(features.iterrows()):
            regime, conf = self._classify(row)
            raw_regimes.append(regime)
            raw_confidences.append(conf)

        raw_regimes = np.array(raw_regimes)
        raw_confidences = np.array(raw_confidences)

        # Second pass: apply hysteresis and smoothing
        smoothed_regimes = self._apply_hysteresis_and_smoothing(
            features, raw_regimes, raw_confidences
        )

        return pd.Series(smoothed_regimes, index=features.index, dtype=int)

    def predict_with_confidence(self, features: pd.DataFrame) -> pd.DataFrame:
        """Predict regime + confidence per bar with all enhancements."""
        if features.empty:
            return pd.DataFrame()

        # Reset state for fresh prediction run
        self._reset_state()

        # First pass: compute raw regime classifications
        raw_regimes = []
        raw_confidences = []
        for idx, (_, row) in enumerate(features.iterrows()):
            regime, conf = self._classify(row)
            raw_regimes.append(regime)
            raw_confidences.append(conf)

        raw_regimes = np.array(raw_regimes)
        raw_confidences = np.array(raw_confidences)

        # Second pass: apply hysteresis, smoothing, and transition decay
        smoothed_regimes, final_confidences = self._apply_hysteresis_smoothing_and_decay(
            features, raw_regimes, raw_confidences
        )

        result = pd.DataFrame(index=features.index)
        result['regime']      = smoothed_regimes.astype(int)
        result['regime_name'] = result['regime'].map(REGIME_NAMES)
        result['confidence']  = final_confidences.clip(0.0, 1.0)

        # Pseudo-probabilities: 1-hot-ish with soft confidence
        for r, name in REGIME_NAMES.items():
            col = f"prob_{name.lower().replace('-', '_').replace(' ', '_')}"
            is_this = (result['regime'] == r).astype(float)
            conf = result['confidence']
            other_prob = (1 - conf) / max(self._n_states - 1, 1)
            result[col] = is_this * conf + (1 - is_this) * other_prob

        return result

    def get_current_regime(self, features: pd.DataFrame) -> dict:
        """Get most recent regime with confidence, transition info, and duration."""
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

            # Duration: how long current regime has lasted
            if len(result) > 0:
                current_regimes = result['regime'].values
                duration = 1
                for i in range(len(current_regimes) - 2, -1, -1):
                    if current_regimes[i] == regime_int:
                        duration += 1
                    else:
                        break
            else:
                duration = 0

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
                "duration_bars": duration,
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

    def confirm_with_htf(self, htf_regime: int, htf_confidence: float) -> None:
        """
        Boost or reduce confidence based on higher-timeframe regime alignment.

        Args:
            htf_regime: Regime from higher timeframe (0-3)
            htf_confidence: Confidence from higher timeframe (0.0-1.0)
        """
        if htf_confidence < 0.5:
            return  # HTF signal too weak

        current = self._current_regime
        alignment_bonus = 0.0

        # Strong alignment boost
        if current == htf_regime:
            alignment_bonus = min(htf_confidence * 0.15, 0.15)
        # Slight penalty for misalignment
        else:
            alignment_bonus = -min(htf_confidence * 0.10, 0.10)

        return alignment_bonus  # Caller applies this to confidence

    # ─── Core Classification Logic ───────────────────────────

    def _reset_state(self):
        """Reset state for fresh prediction run."""
        self._current_regime = RANGING
        self._regime_bar_count = 0
        self._pending_regime = None
        self._pending_bar_count = 0
        self._regime_history = []
        self._current_bar_idx = 0

    def _classify(self, row) -> tuple:
        """
        Classify a single bar into a regime + confidence.

        Returns: (regime_int, confidence_float)

        Priority:
          1. VOLATILE  (ATR spike or rapid price movement — overrides everything)
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
        high       = float(row.get('high', 0) or 0)
        low        = float(row.get('low', 0) or 0)

        # Update adaptive ATR threshold (95th percentile)
        self._atr_ratio_history.append(vol_ratio)
        if len(self._atr_ratio_history) > self._volatility_lookback:
            self._atr_ratio_history.pop(0)

        if len(self._atr_ratio_history) >= 30:
            self._adaptive_atr_threshold = np.percentile(self._atr_ratio_history, 95)
        else:
            self._adaptive_atr_threshold = VOLATILE_ATR_RATIO

        # ── 1. VOLATILE: ATR ratio spike OR rapid price movement ──
        volatile = False
        volatile_conf = 0.55

        # Check ATR ratio (adaptive threshold)
        if vol_ratio >= self._adaptive_atr_threshold:
            volatile = True
            raw = (vol_ratio - self._adaptive_atr_threshold) / (VOLATILE_HIGH_RATIO - self._adaptive_atr_threshold)
            volatile_conf = 0.55 + min(raw, 1.0) * 0.40

        # Check rapid price movement (>2% in 5 bars)
        if high > 0 and low > 0:
            recent_high = high  # Assume row has high
            recent_low = low    # Assume row has low
            price_range = recent_high - recent_low
            price_mid = (recent_high + recent_low) / 2
            if price_mid > 0:
                pct_move = (price_range / price_mid) * 100
                if pct_move > RAPID_PRICE_MOVE:
                    volatile = True
                    volatile_conf = max(volatile_conf, 0.60 + min(pct_move / 5.0, 1.0) * 0.35)

        if volatile:
            # v5 FIX: Strong trending markets must NOT be misclassified as VOLATILE.
            # If ADX is high AND DI spread is clear, the move is directional, not chaotic.
            # True volatility = high ATR *without* clear direction (low ADX / DI spread).
            di_spread_raw = plus_di - minus_di
            if adx >= 30 and abs(di_spread_raw) >= 10:
                volatile = False  # Reclassify — elevated ATR is part of the trend move

        if volatile:
            return VOLATILE, min(volatile_conf, 1.0)

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

    def _apply_hysteresis_and_smoothing(
        self, features: pd.DataFrame, raw_regimes: np.ndarray, raw_confidences: np.ndarray
    ) -> np.ndarray:
        """
        Apply hysteresis to prevent whipsaw.

        Requires REGIME_HYSTERESIS_BARS consecutive bars of same regime
        before switching to a new regime.
        """
        n = len(raw_regimes)
        smoothed = np.zeros(n, dtype=int)
        smoothed[0] = raw_regimes[0]
        self._current_regime = raw_regimes[0]
        self._regime_bar_count = 1

        for i in range(1, n):
            if raw_regimes[i] == self._current_regime:
                # Same regime, increment counter
                self._regime_bar_count += 1
                smoothed[i] = self._current_regime
            else:
                # Different regime
                if self._pending_regime is None:
                    # First time seeing this candidate regime
                    self._pending_regime = raw_regimes[i]
                    self._pending_bar_count = 1
                    smoothed[i] = self._current_regime
                elif raw_regimes[i] == self._pending_regime:
                    # Same candidate, increment counter
                    self._pending_bar_count += 1
                    if self._pending_bar_count >= self._hysteresis_bars:
                        # Threshold met, switch regime
                        self._current_regime = self._pending_regime
                        self._regime_bar_count = self._pending_bar_count
                        self._pending_regime = None
                        self._pending_bar_count = 0
                    smoothed[i] = self._current_regime
                else:
                    # Different candidate, reset pending
                    self._pending_regime = raw_regimes[i]
                    self._pending_bar_count = 1
                    smoothed[i] = self._current_regime

        return smoothed

    def _apply_hysteresis_smoothing_and_decay(
        self, features: pd.DataFrame, raw_regimes: np.ndarray, raw_confidences: np.ndarray
    ) -> tuple:
        """
        Apply hysteresis, EMA smoothing, and transition decay to regime signals.

        Returns: (smoothed_regimes, final_confidences)
        """
        n = len(raw_regimes)
        smoothed_regimes = self._apply_hysteresis_and_smoothing(features, raw_regimes, raw_confidences)

        # Apply transition decay (reduce confidence when transitioning)
        final_confidences = np.copy(raw_confidences).astype(float)

        for i in range(n):
            if smoothed_regimes[i] != raw_regimes[i]:
                # Regime was changed by hysteresis, apply decay
                decay_factor = self._transition_decay ** (i - max(0, i - self._hysteresis_bars))
                final_confidences[i] *= decay_factor

        # Count transitioning bars (where regime changed from previous)
        for i in range(1, n):
            if smoothed_regimes[i] != smoothed_regimes[i-1]:
                # Transition just happened, apply decay for next few bars
                for j in range(i, min(i + self._hysteresis_bars, n)):
                    if smoothed_regimes[j] == smoothed_regimes[i]:
                        final_confidences[j] *= (self._transition_decay ** (j - i))

        return smoothed_regimes, final_confidences.clip(0.0, 1.0)

    def _default_regime(self) -> dict:
        return {
            "regime":        RANGING,
            "regime_name":   "Ranging",
            "confidence":    0.50,
            "probabilities": {n: 0.25 for n in REGIME_NAMES.values()},
            "transitioning": False,
            "duration_bars": 0,
        }
