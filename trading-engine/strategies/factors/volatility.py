"""
Volatility Factor — ATR regime, BB squeeze, RV/HV ratio
Returns float in [-1.0, +1.0] indicating expected breakout direction,
or 0 (no strong directional signal from volatility alone).
Mainly used for position sizing and risk adjustments.
"""
import numpy as np
import pandas as pd


class VolatilityFactor:
    """
    Components:
    1. ATR regime (low/normal/high)
    2. BB width percentile (squeeze detection)
    3. Realized vs historical volatility ratio
    """

    def score(self, df: pd.DataFrame, df_4h: pd.DataFrame = None) -> pd.Series:
        """
        Volatility itself is mostly direction-neutral.
        Score reflects squeeze breakout direction bias when compressing.
        """
        scores = pd.Series(0.0, index=df.index)

        scores += self._squeeze_breakout_score(df) * 0.50
        scores += self._rv_hv_score(df) * 0.30
        scores += self._atr_regime_score(df) * 0.20

        return scores.clip(-1.0, 1.0)

    def atr_multiplier(self, df: pd.DataFrame) -> pd.Series:
        """
        Return ATR SL multiplier based on current volatility regime.
        Low vol -> 1.0x, Normal -> 1.5x, High vol -> 2.5x
        """
        if 'volatility_ratio' not in df.columns:
            return pd.Series(1.5, index=df.index)

        vr = df['volatility_ratio'].fillna(1.0)
        mult = pd.Series(1.5, index=df.index)
        mult[vr < 0.7] = 1.0
        mult[(vr >= 0.7) & (vr <= 1.3)] = 1.5
        mult[vr > 1.3] = 2.0 + (vr[vr > 1.3] - 1.3) * 0.8
        return mult.clip(1.0, 3.0)

    def position_size_multiplier(self, df: pd.DataFrame) -> pd.Series:
        """Scale position size based on volatility (higher vol = smaller size)."""
        if 'volatility_ratio' not in df.columns:
            return pd.Series(1.0, index=df.index)

        vr = df['volatility_ratio'].fillna(1.0)
        # High vol regime: scale down; low vol: allow slight scale up
        mult = (1.0 / vr.clip(0.5, 2.0)).clip(0.5, 1.3)
        return mult

    def _squeeze_breakout_score(self, df: pd.DataFrame) -> pd.Series:
        """
        BB squeeze (BB inside Keltner) + recent direction = breakout bias.
        When squeeze ends, price tends to move in the direction of the prior trend.
        """
        score = pd.Series(0.0, index=df.index)

        if 'bb_inside_keltner' not in df.columns:
            return score

        squeeze = df['bb_inside_keltner'].fillna(0)

        # Direction of price during squeeze = likely breakout direction
        if 'ema_9_slope' in df.columns:
            slope = df['ema_9_slope'].fillna(0)
            # During squeeze, bias toward the direction price was moving
            score = squeeze * np.sign(slope) * 0.6

        # When squeeze ends (was 1, now 0), strong signal
        squeeze_end = ((squeeze == 0) & (squeeze.shift(1) == 1)).astype(float)
        if 'close' in df.columns and 'ema_9' in df.columns:
            above_ema = (df['close'] > df['ema_9']).astype(float) * 2 - 1
            score += squeeze_end * above_ema * 0.8

        return score.clip(-1.0, 1.0)

    def _rv_hv_score(self, df: pd.DataFrame) -> pd.Series:
        """
        RV/HV ratio — continuous gradient instead of hard thresholds:
          ratio << 1  → compression (positive bias toward breakout)
          ratio == 1  → neutral (0)
          ratio >> 1  → spiking (negative bias, uncertainty)
        Uses smooth tanh mapping so score changes continuously.
        """
        if 'rv_hv_ratio' not in df.columns:
            return pd.Series(0.0, index=df.index)

        rv_hv = df['rv_hv_ratio'].fillna(1.0)
        # Centre around 1, scale so ±1.0 ratio deviation → ±0.5 score
        # tanh(-x) where x = (rv_hv - 1) gives: low ratio → positive, high ratio → negative
        centered = (rv_hv - 1.0).clip(-2.0, 2.0)
        score = pd.Series(np.tanh(-centered * 0.8) * 0.4, index=df.index)
        return score

    def _atr_regime_score(self, df: pd.DataFrame) -> pd.Series:
        """
        ATR regime score — continuous gradient instead of hard thresholds.
        Low vol (vr < 1) → slight positive (breakout potential)
        High vol (vr > 1) → slight negative (mean reversion potential)
        """
        if 'volatility_ratio' not in df.columns:
            return pd.Series(0.0, index=df.index)

        vr = df['volatility_ratio'].fillna(1.0)
        # Smooth inverse: low vol = positive bias, high vol = negative
        # tanh(-(vr-1)) ranges from +1 (vr→0) to -1 (vr→∞)
        centered = (vr - 1.0).clip(-2.0, 2.0)
        score = pd.Series(np.tanh(-centered * 1.0) * 0.35, index=df.index)
        return score
