"""
Open Interest Factor - futures positioning pressure from OI + long/short ratio.
Returns float in [-1.0, +1.0].
"""
from __future__ import annotations

import numpy as np
import pandas as pd


class OpenInterestFactor:
    """
    Components:
    1. OI trend: rising OI -> stronger positioning pressure.
    2. Long/short crowding: long-heavy is contrarian bearish, short-heavy bullish.
    3. Price-momentum agreement/divergence with OI trend.
    """

    def __init__(self):
        self._oi_cache: dict[str, list[float]] = {}
        self._long_ratio_cache: dict[str, list[float]] = {}

    def update_oi(self, symbol: str, oi: float):
        if symbol not in self._oi_cache:
            self._oi_cache[symbol] = []
        self._oi_cache[symbol].append(float(oi))
        if len(self._oi_cache[symbol]) > 30:
            self._oi_cache[symbol].pop(0)

    def update_long_short_ratio(self, symbol: str, long_ratio: float):
        if symbol not in self._long_ratio_cache:
            self._long_ratio_cache[symbol] = []
        self._long_ratio_cache[symbol].append(float(long_ratio))
        if len(self._long_ratio_cache[symbol]) > 30:
            self._long_ratio_cache[symbol].pop(0)

    def score(self, df: pd.DataFrame, symbol: str | None = None) -> pd.Series:
        scores = pd.Series(0.0, index=df.index)
        if len(df) == 0:
            return scores

        oi_trend = self._oi_trend_score(symbol)
        crowding = self._crowding_score(symbol)
        price_div = self._price_divergence_score(df, symbol)

        # Only use latest value from cache-driven components.
        # Older bars remain 0 because we don't have historical OI snapshots per bar.
        latest = float(np.clip(oi_trend * 0.45 + crowding * 0.35 + price_div * 0.20, -1.0, 1.0))
        scores.iloc[-1] = latest
        return scores

    def _oi_trend_score(self, symbol: str | None) -> float:
        if symbol is None or symbol not in self._oi_cache or len(self._oi_cache[symbol]) < 3:
            return 0.0
        vals = self._oi_cache[symbol]
        first = vals[max(0, len(vals) - 10)]
        last = vals[-1]
        if first <= 0:
            return 0.0
        pct = (last - first) / first
        return float(np.clip(pct / 0.08, -1.0, 1.0))  # 8% OI move ~= full scale

    def _crowding_score(self, symbol: str | None) -> float:
        if symbol is None or symbol not in self._long_ratio_cache or len(self._long_ratio_cache[symbol]) == 0:
            return 0.0
        long_ratio = self._long_ratio_cache[symbol][-1]
        # 0.5 neutral; long crowding (>0.5) is contrarian bearish.
        return float(np.clip(-(long_ratio - 0.5) / 0.25, -1.0, 1.0))

    def _price_divergence_score(self, df: pd.DataFrame, symbol: str | None) -> float:
        if len(df) < 5:
            return 0.0
        if symbol is None or symbol not in self._oi_cache or len(self._oi_cache[symbol]) < 3:
            return 0.0

        price_ret = (float(df["close"].iloc[-1]) - float(df["close"].iloc[-5])) / (float(df["close"].iloc[-5]) + 1e-10)
        price_sign = np.sign(price_ret)
        oi_sign = np.sign(self._oi_trend_score(symbol))
        if oi_sign == 0:
            return 0.0

        # Price and OI in same direction => trend participation (positive).
        # Opposite direction => potential squeeze/weak move (negative).
        return float(0.5 if price_sign == oi_sign else -0.5)
