"""
Volume/Flow Factor — OBV trend, CVD, funding rate trend, open interest
Returns float in [-1.0, +1.0]
"""
import numpy as np
import pandas as pd


class VolumeFlowFactor:
    """
    Components:
    1. OBV trend (buying/selling pressure over time)
    2. Cumulative Volume Delta (net buy vs sell volume)
    3. Funding rate trend (crypto-specific)
    4. Volume spike direction
    """

    def __init__(self):
        self._funding_cache = {}     # symbol -> list of recent rates
        self._oi_cache = {}          # symbol -> list of recent OI

    def update_funding(self, symbol: str, rate: float):
        """Update funding rate cache (called from main loop)."""
        if symbol not in self._funding_cache:
            self._funding_cache[symbol] = []
        self._funding_cache[symbol].append(rate)
        if len(self._funding_cache[symbol]) > 10:
            self._funding_cache[symbol].pop(0)

    def update_oi(self, symbol: str, oi: float):
        """Update open interest cache."""
        if symbol not in self._oi_cache:
            self._oi_cache[symbol] = []
        self._oi_cache[symbol].append(oi)
        if len(self._oi_cache[symbol]) > 10:
            self._oi_cache[symbol].pop(0)

    def score(self, df: pd.DataFrame, df_4h: pd.DataFrame = None,
              symbol: str = None) -> pd.Series:
        scores = pd.Series(0.0, index=df.index)

        scores += self._obv_score(df) * 0.35
        scores += self._cvd_score(df) * 0.35
        scores += self._volume_spike_score(df) * 0.20
        scores += self._funding_score(symbol) * 0.10

        # ── 4h OBV confirmation: blend 15% 4h directional bias into the score ──
        # Aligns 1h volume pressure with the broader 4h buying/selling trend.
        if df_4h is not None and len(df_4h) >= 20:
            conf_4h = self._4h_volume_confirmation(df, df_4h)
            scores = scores * 0.85 + conf_4h * 0.15

        return scores.clip(-1.0, 1.0)

    def _obv_score(self, df: pd.DataFrame) -> pd.Series:
        """OBV trend: rising OBV = buying pressure = bullish."""
        if 'obv_slope' not in df.columns:
            return pd.Series(0.0, index=df.index)

        slope = df['obv_slope'].fillna(0)
        # Normalize slope to [-1, 1]
        slope_std = slope.rolling(50, min_periods=10).std().fillna(1)
        score = (slope / (slope_std * 2 + 1e-10)).clip(-1.0, 1.0)
        return score

    def _cvd_score(self, df: pd.DataFrame) -> pd.Series:
        """CVD: net buyer volume vs seller volume over 20 bars."""
        if 'cvd_20' not in df.columns:
            return pd.Series(0.0, index=df.index)

        cvd = df['cvd_20'].fillna(0)
        # Normalize by average volume to make cross-symbol comparable
        avg_vol = df['volume'].rolling(20).mean().fillna(1)
        cvd_norm = (cvd / (avg_vol * 20 + 1e-10)).clip(-2, 2) / 2
        return cvd_norm.clip(-1.0, 1.0)

    def _volume_spike_score(self, df: pd.DataFrame) -> pd.Series:
        """Volume spike with price direction = momentum confirmation."""
        score = pd.Series(0.0, index=df.index)

        if 'volume_ratio' not in df.columns:
            return score

        vol_ratio = df['volume_ratio'].fillna(1)
        body = df['close'] - df['open']

        # High volume + up candle = bullish; high volume + down candle = bearish
        spike = (vol_ratio > 1.5).astype(float)
        direction = np.sign(body)
        score = spike * direction * ((vol_ratio - 1.5) / 3.0).clip(0, 1)

        return score.clip(-1.0, 1.0)

    def _4h_volume_confirmation(self, df: pd.DataFrame, df_4h: pd.DataFrame) -> pd.Series:
        """
        4h OBV slope as directional confirmation, aligned to 1h timestamps via merge_asof.
        Rising 4h OBV = sustained buying pressure = bullish confirmation.
        """
        if 'obv_slope' not in df_4h.columns:
            return pd.Series(0.0, index=df.index)

        slope_4h = df_4h['obv_slope'].fillna(0)
        slope_std = slope_4h.rolling(20, min_periods=5).std().fillna(1)
        score_4h = (slope_4h / (slope_std * 2 + 1e-10)).clip(-1.0, 1.0)

        # Align 4h score to 1h index (forward-fill, no look-ahead)
        idx_name = df.index.name or 'timestamp'
        df_tmp = pd.DataFrame(index=df.index).rename_axis(idx_name).reset_index()
        df4_tmp = pd.DataFrame({'score_4h': score_4h}).rename_axis(idx_name).reset_index()
        merged = pd.merge_asof(df_tmp, df4_tmp, on=idx_name, direction='backward')
        merged = merged.set_index(idx_name)

        return merged['score_4h'].fillna(0).reindex(df.index, fill_value=0)

    def _funding_score(self, symbol: str = None) -> float:
        """
        EMA-smoothed funding rate trend.
        Rising funding = longs paying more = bearish pressure.
        Falling funding = shorts paying more = bullish pressure.

        Uses EMA (α=0.3) instead of raw 3-point diff to reduce noise.
        Requires at least 3 cached readings to produce a signal.
        """
        if symbol is None or symbol not in self._funding_cache:
            return 0.0

        rates = self._funding_cache[symbol]
        if len(rates) < 3:
            return 0.0

        alpha = 0.3  # EMA smoothing factor (~5-bar half-life)

        # EMA of the most recent readings
        ema_recent = rates[-1]
        for r in reversed(rates[-min(5, len(rates)):]):
            ema_recent = alpha * r + (1 - alpha) * ema_recent

        # EMA of the older half (baseline)
        half = max(1, len(rates) // 2)
        ema_old = rates[0]
        for r in rates[:half]:
            ema_old = alpha * r + (1 - alpha) * ema_old

        trend = ema_recent - ema_old
        # Rising funding = negative score; 0.05% (0.0005) change → score of ±1
        return float(np.clip(-trend / 0.0005, -1.0, 1.0))
