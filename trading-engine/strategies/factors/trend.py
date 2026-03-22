"""
Trend Factor — Multi-layer trend confirmation score
Returns float in [-1.0, +1.0]: positive = bullish, negative = bearish
"""
import numpy as np
import pandas as pd


class TrendFactor:
    """
    Components:
    1. Multi-TF EMA alignment (EMA 9 > 21 > 50 > 200)
    2. ADX strength + DI spread direction
    3. Ichimoku cloud position
    4. VWAP trend
    """

    def score(self, df: pd.DataFrame, df_4h: pd.DataFrame = None) -> pd.Series:
        """Return per-bar trend score in [-1, 1]."""
        idx = df.index
        scores = pd.Series(0.0, index=idx)

        scores += self._ema_alignment(df, df_4h) * 0.35
        scores += self._adx_di_score(df) * 0.30
        scores += self._ichimoku_score(df) * 0.20
        scores += self._vwap_trend_score(df) * 0.15

        return scores.clip(-1.0, 1.0)

    def _ema_alignment(self, df: pd.DataFrame, df_4h: pd.DataFrame = None) -> pd.Series:
        """Score based on EMA stack alignment."""
        score = pd.Series(0.0, index=df.index)

        emas = {}
        for p in [9, 21, 50, 200]:
            col = f'ema_{p}'
            if col in df.columns:
                emas[p] = df[col]

        if len(emas) < 2:
            return score

        close = df['close']

        # Count how many EMA pairs are correctly ordered
        pairs = [(9, 21), (21, 50), (50, 200)]
        for fast, slow in pairs:
            if fast in emas and slow in emas:
                bull = (emas[fast] > emas[slow]).astype(float)
                bear = (emas[fast] < emas[slow]).astype(float)
                score += (bull - bear) / len(pairs)

        # Price above/below EMA 50
        if 50 in emas:
            above = (close > emas[50]).astype(float)
            score += (above * 2 - 1) * 0.2

        # 4h EMA confirmation if available
        if df_4h is not None and not df_4h.empty:
            for bar_idx in df.index:
                row_4h = df_4h[df_4h.index <= bar_idx]
                if row_4h.empty:
                    continue
                r4 = row_4h.iloc[-1]
                if 'ema_9' in r4 and 'ema_21' in r4:
                    if r4['ema_9'] > r4['ema_21']:
                        score.loc[bar_idx] += 0.2
                    elif r4['ema_9'] < r4['ema_21']:
                        score.loc[bar_idx] -= 0.2

        return score.clip(-1.0, 1.0)

    def _adx_di_score(self, df: pd.DataFrame) -> pd.Series:
        """ADX strength * DI direction."""
        score = pd.Series(0.0, index=df.index)
        if 'adx' not in df.columns:
            return score

        adx = df['adx'].fillna(0)
        # Normalize ADX: 20 = weak, 40 = strong, cap at 60
        adx_strength = ((adx - 20) / 40).clip(0.0, 1.0)

        if 'plus_di' in df.columns and 'minus_di' in df.columns:
            plus_di = df['plus_di'].fillna(25)
            minus_di = df['minus_di'].fillna(25)
            di_sum = (plus_di + minus_di).replace(0, 1e-10)
            di_direction = (plus_di - minus_di) / di_sum  # -1 to +1
            score = adx_strength * di_direction
        else:
            # Fallback: just use slope
            if 'ema_9_slope' in df.columns:
                score = np.sign(df['ema_9_slope'].fillna(0)) * adx_strength

        return score.clip(-1.0, 1.0)

    def _ichimoku_score(self, df: pd.DataFrame) -> pd.Series:
        """Ichimoku cloud position score."""
        if 'ichimoku_position' in df.columns:
            return df['ichimoku_position'].fillna(0).clip(-1.0, 1.0)

        score = pd.Series(0.0, index=df.index)
        if 'ichimoku_tenkan' in df.columns and 'ichimoku_kijun' in df.columns:
            tk_diff = df['ichimoku_tenkan'] - df['ichimoku_kijun']
            score = np.sign(tk_diff).fillna(0)
        return score

    def _vwap_trend_score(self, df: pd.DataFrame) -> pd.Series:
        """Score based on price position relative to VWAP."""
        score = pd.Series(0.0, index=df.index)

        if 'vwap_zscore' in df.columns:
            z = df['vwap_zscore'].fillna(0).clip(-3, 3)
            score = (z / 3).clip(-1.0, 1.0)
        elif 'vwap_distance' in df.columns:
            score = np.sign(df['vwap_distance'].fillna(0))

        return score
