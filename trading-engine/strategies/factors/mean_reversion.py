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

        # If 4h strongly trending, dampen mean reversion (trend overrides)
        if df_4h is not None and not df_4h.empty:
            for bar_idx in df.index:
                row_4h = df_4h[df_4h.index <= bar_idx]
                if row_4h.empty:
                    continue
                adx_4h = float(row_4h.iloc[-1].get('adx', 0) if 'adx' in row_4h.columns else 0)
                if adx_4h > 35:
                    scores.loc[bar_idx] *= 0.3  # Strongly trending 4h = dampen range trades

        return scores.clip(-1.0, 1.0)

    def _bb_keltner_score(self, df: pd.DataFrame) -> pd.Series:
        """
        BB %B: 0 = at lower band (oversold), 1 = at upper band (overbought)
        Squeeze (BB inside Keltner) amplifies the signal (breakout pending).
        Returns +1 at lower band (buy), -1 at upper band (sell).
        """
        score = pd.Series(0.0, index=df.index)

        if 'bb_pct' not in df.columns:
            return score

        bb_pct = df['bb_pct'].fillna(0.5)
        # Convert: 0 (lower band) = +1, 0.5 (mid) = 0, 1 (upper band) = -1
        score = -(bb_pct * 2 - 1).clip(-1, 1)

        # Amplify when squeeze is active (BB inside Keltner = volatility compression)
        if 'bb_inside_keltner' in df.columns:
            squeeze = df['bb_inside_keltner'].fillna(0)
            # Only amplify, don't reverse direction
            score = score * (1 + squeeze * 0.5)

        # Also check RSI level (oversold/overbought confirmation)
        if 'rsi_14' in df.columns:
            rsi = df['rsi_14'].fillna(50)
            # Boost score at RSI extremes
            rsi_boost = pd.Series(0.0, index=df.index)
            rsi_boost[rsi < 35] = 0.3
            rsi_boost[rsi > 65] = -0.3
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
