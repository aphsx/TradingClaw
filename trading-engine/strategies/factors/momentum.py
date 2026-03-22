"""
Momentum Factor — MACD, Stoch RSI, ROC, candlestick patterns
Returns float in [-1.0, +1.0]
"""
import numpy as np
import pandas as pd


class MomentumFactor:
    """
    Components:
    1. MACD histogram momentum/acceleration
    2. Stochastic RSI crossover
    3. Multi-period Rate of Change
    4. Candlestick patterns (engulfing, pin bar)
    """

    def score(self, df: pd.DataFrame, df_4h: pd.DataFrame = None) -> pd.Series:
        scores = pd.Series(0.0, index=df.index)

        scores += self._macd_score(df) * 0.35
        scores += self._stoch_rsi_score(df) * 0.25
        scores += self._roc_score(df, df_4h) * 0.25
        scores += self._candle_pattern_score(df) * 0.15

        return scores.clip(-1.0, 1.0)

    def _macd_score(self, df: pd.DataFrame) -> pd.Series:
        """MACD histogram direction + acceleration."""
        score = pd.Series(0.0, index=df.index)

        if 'macd_hist' not in df.columns:
            return score

        hist = df['macd_hist'].fillna(0)

        # Normalize histogram by ATR for cross-symbol comparability
        atr = df['atr_14'].fillna(1) if 'atr_14' in df.columns else pd.Series(1.0, index=df.index)
        hist_norm = (hist / (atr + 1e-10)).clip(-3, 3) / 3

        score = hist_norm

        # Amplify when histogram is accelerating (slope positive for bullish)
        if 'macd_hist_slope' in df.columns:
            slope = np.sign(df['macd_hist_slope'].fillna(0))
            # Same direction as histogram = momentum building
            accel_bonus = (np.sign(hist) == slope).astype(float) * 0.3 * slope
            score = (score + accel_bonus).clip(-1.0, 1.0)

        return score

    def _stoch_rsi_score(self, df: pd.DataFrame) -> pd.Series:
        """Stochastic RSI: %K/%D crossover + extreme zones."""
        score = pd.Series(0.0, index=df.index)

        if 'stoch_rsi_k' not in df.columns or 'stoch_rsi_d' not in df.columns:
            return score

        k = df['stoch_rsi_k'].fillna(50)
        d = df['stoch_rsi_d'].fillna(50)

        # Position: oversold (<20) = bullish, overbought (>80) = bearish
        pos_score = pd.Series(0.0, index=df.index)
        pos_score[k < 20] = 1.0
        pos_score[k > 80] = -1.0
        pos_score[(k >= 20) & (k <= 80)] = -(k[(k >= 20) & (k <= 80)] - 50) / 50

        # Crossover signal (K crosses D)
        cross_up = ((k > d) & (k.shift(1) <= d.shift(1))).astype(float)
        cross_down = ((k < d) & (k.shift(1) >= d.shift(1))).astype(float)
        cross_score = cross_up - cross_down

        # Stronger signal when cross happens in extreme zone
        oversold_cross = cross_up * (k < 30).astype(float)
        overbought_cross = cross_down * (k > 70).astype(float)

        score = pos_score * 0.4 + cross_score * 0.3 + oversold_cross * 0.5 - overbought_cross * 0.5
        return score.clip(-1.0, 1.0)

    def _roc_score(self, df: pd.DataFrame, df_4h: pd.DataFrame = None) -> pd.Series:
        """Rate of change on 1h + 4h confirmation."""
        score = pd.Series(0.0, index=df.index)

        if 'roc_5' in df.columns:
            roc = df['roc_5'].fillna(0)
            # Normalize by rolling std
            roc_std = roc.rolling(50, min_periods=10).std().fillna(1)
            score = (roc / (roc_std * 2 + 1e-10)).clip(-1.0, 1.0)

        if 'momentum_10' in df.columns:
            mom = df['momentum_10'].fillna(0)
            mom_std = mom.rolling(50, min_periods=10).std().fillna(1)
            score = (score + (mom / (mom_std * 2 + 1e-10)).clip(-1.0, 1.0)) / 2

        # 4h ROC confirmation — O(N) via merge_asof (was O(N²))
        if df_4h is not None and not df_4h.empty and 'momentum_10' in df_4h.columns:
            idx_name = df.index.name or 'index'
            idx_name_4h = df_4h.index.name or 'index'
            aligned = pd.merge_asof(
                score.rename('score').reset_index(),
                df_4h[['momentum_10']].reset_index(),
                left_on=idx_name,
                right_on=idx_name_4h,
                direction='backward',
            ).set_index(idx_name)
            mom_4h = aligned['momentum_10'].reindex(score.index).fillna(0)
            # Amplify by 20% when 4h momentum agrees with 1h score direction
            confirmation_mask = np.sign(mom_4h) == np.sign(score)
            score = score.where(~confirmation_mask, score * 1.2)

        return score.clip(-1.0, 1.0)

    def _candle_pattern_score(self, df: pd.DataFrame) -> pd.Series:
        """Candlestick patterns as directional signals."""
        score = pd.Series(0.0, index=df.index)

        if 'is_engulfing' in df.columns:
            body = df['close'] - df['open']
            # Bullish engulfing
            bull_eng = (df['is_engulfing'] == 1) & (body > 0)
            bear_eng = (df['is_engulfing'] == 1) & (body < 0)
            score += bull_eng.astype(float) * 0.6
            score -= bear_eng.astype(float) * 0.6

        if 'is_pin_bar' in df.columns:
            if 'low' in df.columns and 'open' in df.columns:
                lower_wick = df[['close', 'open']].min(axis=1) - df['low']
                upper_wick = df['high'] - df[['close', 'open']].max(axis=1)
                bull_pin = (df['is_pin_bar'] == 1) & (lower_wick > upper_wick)
                bear_pin = (df['is_pin_bar'] == 1) & (upper_wick > lower_wick)
                score += bull_pin.astype(float) * 0.4
                score -= bear_pin.astype(float) * 0.4

        return score.clip(-1.0, 1.0)
