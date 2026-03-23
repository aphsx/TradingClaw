"""
Mean Reversion Factor — BB/Keltner squeeze, RSI divergence, VWAP Z-score
Returns float in [-1.0, +1.0]: positive = expect price to rise, negative = expect fall
"""
import numpy as np
import pandas as pd


class MeanReversionFactor:
    """
    Components:
    1. BB %B position + Keltner squeeze state
    2. RSI divergence
    3. VWAP Z-score deviation
    """

    def score(self, df: pd.DataFrame, df_4h: pd.DataFrame = None) -> pd.Series:
        """Return per-bar mean reversion score in [-1, 1]."""
        scores = pd.Series(0.0, index=df.index)

        scores += self._bb_keltner_score(df) * 0.40
        scores += self._rsi_divergence_score(df) * 0.35
        scores += self._vwap_zscore_score(df) * 0.25

        # If 4h strongly trending, dampen mean reversion via merge_asof (O(N))
        if df_4h is not None and not df_4h.empty and 'adx' in df_4h.columns:
            aligned = pd.merge_asof(
                df[['close']].reset_index(), df_4h[['adx']].reset_index(),
                left_on=df.index.name or 'index', right_on=df_4h.index.name or 'index',
                direction='backward',
            ).set_index(df.index.name or 'index')
            adx_4h = aligned['adx'].reindex(scores.index).fillna(0)
            dampen_mask = adx_4h > 35
            scores = scores.where(~dampen_mask, scores * 0.3)

        return scores.clip(-1.0, 1.0)

    def _bb_keltner_score(self, df: pd.DataFrame) -> pd.Series:
        """
        BB %B: 0 = at lower band (oversold), 1 = at upper band (overbought)
        Squeeze (BB inside Keltner) amplifies the signal (breakout pending).
        Returns +1 at lower band (buy), -1 at upper band (sell).

        Fix #3: Dead zone added — BB %B between 0.20 and 0.80 (price near mid-band)
        gives zero score. Only extremes carry a signal. RSI threshold tightened
        from 35/65 to 25/75 to reduce false entries.
        """
        score = pd.Series(0.0, index=df.index)

        if 'bb_pct' not in df.columns:
            return score

        bb_pct = df['bb_pct'].fillna(0.5)

        # Raw mapping: 0 (lower band) = +1, 0.5 (mid) = 0, 1 (upper band) = -1
        raw = -(bb_pct * 2 - 1).clip(-1, 1)

        # Dead zone: price within 0.20–0.80 of band has no mean-reversion edge
        dead_zone = (bb_pct > 0.20) & (bb_pct < 0.80)
        score = raw.where(~dead_zone, 0.0)

        # Extra boost at hard extremes (%B < 0.10 or > 0.90)
        extreme_low  = (bb_pct < 0.10).astype(float) * 0.3
        extreme_high = (bb_pct > 0.90).astype(float) * -0.3
        score = score + extreme_low + extreme_high

        # Amplify when squeeze is active (BB inside Keltner = volatility compression)
        # Only applies when already in extreme territory (score != 0)
        if 'bb_inside_keltner' in df.columns:
            squeeze = df['bb_inside_keltner'].fillna(0)
            score = score * (1 + squeeze * 0.5)

        # RSI confirmation — tightened thresholds to reduce false signals
        if 'rsi_14' in df.columns:
            rsi = df['rsi_14'].fillna(50)
            rsi_boost = pd.Series(0.0, index=df.index)
            rsi_boost[rsi < 25] = 0.4   # was < 35
            rsi_boost[rsi > 75] = -0.4  # was > 65
            score = score + rsi_boost

        return score.clip(-1.0, 1.0)

    def _rsi_divergence_score(self, df: pd.DataFrame) -> pd.Series:
        """RSI divergence is a high-quality mean reversion signal."""
        if 'rsi_divergence' in df.columns:
            return df['rsi_divergence'].fillna(0).clip(-1.0, 1.0)
        return pd.Series(0.0, index=df.index)

    def _vwap_zscore_score(self, df: pd.DataFrame) -> pd.Series:
        """
        Z-score > 2: overbought, expect reversion down (-1)
        Z-score < -2: oversold, expect reversion up (+1)
        """
        if 'vwap_zscore' not in df.columns:
            return pd.Series(0.0, index=df.index)

        z = df['vwap_zscore'].fillna(0)
        # Z > 2 = sell signal, Z < -2 = buy signal, linear between -2 and 2
        score = -(z / 2.5).clip(-1.0, 1.0)
        return score
