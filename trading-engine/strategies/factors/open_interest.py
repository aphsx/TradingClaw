"""
OpenInterest Factor — Issue #5
=================================
Uses Open Interest (OI) changes and Long/Short Ratio from Binance Futures
as a signal factor.

Key insight (2026 standard practice):
  - Rising price + rising OI = trend continuation (new money flowing in)
  - Rising price + falling OI = short-covering rally (weak, likely to fade)
  - Falling price + rising OI = trend continuation downward
  - Falling price + falling OI = long liquidation, likely temporary
  - Long/Short ratio extremes = positioning imbalance → mean reversion

Returns float in [-1.0, +1.0]
"""
import numpy as np
import pandas as pd
from collections import deque


class OpenInterestFactor:
    """
    Components:
    1. OI change direction vs price change (divergence/convergence)
    2. Long/Short ratio extremes (crowded positioning signal)
    3. OI change rate of change (acceleration = conviction)
    """

    def __init__(self, cache_size: int = 20):
        self._oi_cache: dict = {}        # symbol -> deque of (timestamp, oi_value)
        self._ls_cache: dict = {}        # symbol -> deque of (timestamp, long_ratio)
        self._cache_size = cache_size

    def update_oi(self, symbol: str, oi: float):
        """Update Open Interest cache. Called from main loop."""
        if symbol not in self._oi_cache:
            self._oi_cache[symbol] = deque(maxlen=self._cache_size)
        self._oi_cache[symbol].append(oi)

    def update_long_short_ratio(self, symbol: str, long_ratio: float):
        """Update Long/Short ratio cache. long_ratio = fraction in [0,1] of longs."""
        if symbol not in self._ls_cache:
            self._ls_cache[symbol] = deque(maxlen=self._cache_size)
        self._ls_cache[symbol].append(long_ratio)

    def score(self, df: pd.DataFrame, symbol: str = None) -> pd.Series:
        """
        Compute OI factor score for the full DataFrame.
        Returns a pd.Series of the same length as df, with only the last bar
        having the live OI signal (older bars get 0 — OI is not in OHLCV).
        """
        scores = pd.Series(0.0, index=df.index)

        if symbol is None:
            return scores

        oi_score   = self._oi_momentum_score(df, symbol)
        ls_score   = self._long_short_score(symbol)

        # Blend: OI momentum 70%, L/S positioning 30%
        combined = oi_score * 0.70 + ls_score * 0.30

        # Only apply to last bar (OI is real-time, not historical in df)
        if len(scores) > 0:
            scores.iloc[-1] = float(np.clip(combined, -1.0, 1.0))

        return scores

    def _oi_momentum_score(self, df: pd.DataFrame, symbol: str) -> float:
        """
        OI change vs price change:
          price_up + OI_up   → bullish  (trend conviction)
          price_up + OI_down → weak     (squeeze/covering, slight bearish)
          price_dn + OI_up   → bearish  (trend conviction)
          price_dn + OI_down → weak reversal candidate (slight bullish)
        """
        oi_hist = self._oi_cache.get(symbol)
        if not oi_hist or len(oi_hist) < 3:
            return 0.0

        oi_vals = list(oi_hist)
        # OI % change over last 3 readings
        oi_change = (oi_vals[-1] - oi_vals[-3]) / (abs(oi_vals[-3]) + 1e-10)

        # Price % change over same window (last bar in df)
        if len(df) < 2:
            return 0.0
        price_change = (df['close'].iloc[-1] - df['close'].iloc[-3]) / (df['close'].iloc[-3] + 1e-10)

        # Normalize both changes
        oi_norm    = float(np.clip(oi_change    / 0.05, -1.0, 1.0))  # 5% OI change = full signal
        price_norm = float(np.clip(price_change / 0.02, -1.0, 1.0))  # 2% price change = full signal

        # Confluence: same direction → amplified signal
        # Divergence: opposite direction → weakened or counter signal
        confluence = oi_norm * price_norm  # positive = both agree
        if confluence > 0:
            # Both rising or both falling → strong trend signal aligned with price direction
            return float(np.clip(price_norm * (1.0 + abs(oi_norm) * 0.5), -1.0, 1.0))
        else:
            # Divergence (price up / OI down, or price down / OI up)
            # → weaker signal; fade slightly against price direction
            return float(np.clip(price_norm * 0.3, -1.0, 1.0))

    def _long_short_score(self, symbol: str) -> float:
        """
        Long/Short ratio extreme = crowded positioning → mean reversion signal.
        High long ratio (>0.65) → bearish (too many longs, potential squeeze down)
        Low long ratio (<0.35)  → bullish (too many shorts, potential squeeze up)
        Neutral (0.4–0.6)       → no signal (0.0)
        """
        ls_hist = self._ls_cache.get(symbol)
        if not ls_hist or len(ls_hist) < 1:
            return 0.0

        long_ratio = ls_hist[-1]  # fraction of longs (0 to 1)

        if long_ratio > 0.65:
            # Overcrowded longs → bearish contrarian signal
            intensity = (long_ratio - 0.65) / 0.20  # 0 at 65%, 1 at 85%
            return float(-np.clip(intensity, 0.0, 1.0))

        elif long_ratio < 0.35:
            # Overcrowded shorts → bullish contrarian signal
            intensity = (0.35 - long_ratio) / 0.20  # 0 at 35%, 1 at 15%
            return float(np.clip(intensity, 0.0, 1.0))

        # Neutral zone: taper linearly to 0
        return 0.0
