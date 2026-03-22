"""
Market Structure Factor — Issue #9
=====================================
Detects key horizontal support/resistance levels using fractal pivot points,
then returns a confidence multiplier when the entry price is near a level.

"Near" is defined as within ±0.5 ATR from the nearest key level.
Entries near a level → higher conviction (we're at a meaningful price).
Entries between levels → neutral (no structural context).

Usage:
    ms = MarketStructureFactor()
    score = ms.confidence_multiplier(df)  # pd.Series of [0.8, 1.5] multipliers
"""
import numpy as np
import pandas as pd


class MarketStructureFactor:
    """
    Pivot-based support/resistance with ATR-proximity confidence boost.

    Pivot detection uses Williams fractals:
      - Pivot High: high[i] > high[i±n] for all n in [1..lookback]
      - Pivot Low:  low[i]  < low[i±n]  for all n in [1..lookback]

    Levels are collected for the last `max_levels` pivots.
    When entry price is near a level, confidence is multiplied up.
    When entry is exactly between two levels (no context), slightly penalised.
    """

    def __init__(self, lookback: int = 5, max_levels: int = 10,
                 proximity_atr_mult: float = 0.5):
        self.lookback = lookback
        self.max_levels = max_levels
        self.proximity_atr_mult = proximity_atr_mult

    def get_key_levels(self, df: pd.DataFrame) -> dict:
        """
        Identify pivot highs and lows in the last `max_levels * 2` bars.
        Returns {'resistance': [price, ...], 'support': [price, ...]}.
        """
        n = self.lookback
        look_bars = min(len(df), self.max_levels * 10 + n)
        sub = df.iloc[-look_bars:]

        highs = sub['high'].values
        lows  = sub['low'].values
        closes = sub['close'].values

        resistances = []
        supports    = []

        for i in range(n, len(highs) - n):
            # Pivot high: strict maximum in [i-n .. i+n]
            if highs[i] == max(highs[i - n: i + n + 1]):
                resistances.append(float(highs[i]))
            # Pivot low: strict minimum in [i-n .. i+n]
            if lows[i] == min(lows[i - n: i + n + 1]):
                supports.append(float(lows[i]))

        # Keep the most recent (most relevant) levels
        resistances = list(dict.fromkeys(resistances[-self.max_levels:]))
        supports    = list(dict.fromkeys(supports[-self.max_levels:]))

        return {'resistance': resistances, 'support': supports}

    def confidence_multiplier(self, df: pd.DataFrame) -> pd.Series:
        """
        Return per-bar confidence multiplier based on proximity to key levels.

        Multiplier logic:
          - At/near support   (within 0.5 ATR below): +30% for LONG  (bullish context)
          - At/near resistance (within 0.5 ATR above): +30% for SHORT (bearish context)
          - Far from all levels:                       ×1.0 (neutral)

        Since direction isn't known at compute time, we return a directional score:
          +1.0 = near support  (bullish context)
          -1.0 = near resistance (bearish context)
           0.0 = no structural context

        The signal engine multiplies |score| × weight to boost confidence.
        """
        score = pd.Series(0.0, index=df.index)

        if len(df) < self.lookback * 2 + 5:
            return score

        try:
            levels = self.get_key_levels(df)
            supports    = levels['support']
            resistances = levels['resistance']

            if not supports and not resistances:
                return score

            close  = df['close']
            atr    = df.get('atr_14', df.get('atr', close * 0.01))

            proximity_band = atr * self.proximity_atr_mult

            for i in df.index:
                try:
                    c = float(close[i])
                    band = float(proximity_band[i]) if hasattr(proximity_band, '__getitem__') else float(proximity_band)

                    # Distance to nearest support (bullish if near support from above)
                    if supports:
                        nearest_sup = min(supports, key=lambda s: abs(c - s))
                        dist_sup = c - nearest_sup  # positive = price above support
                        if 0 <= dist_sup <= band:
                            score[i] = 1.0  # Near support: bullish structural context
                            continue

                    # Distance to nearest resistance (bearish if near resistance from below)
                    if resistances:
                        nearest_res = min(resistances, key=lambda r: abs(c - r))
                        dist_res = nearest_res - c  # positive = price below resistance
                        if 0 <= dist_res <= band:
                            score[i] = -1.0  # Near resistance: bearish structural context
                            continue

                except Exception:
                    continue

        except Exception:
            pass

        return score

    def apply_confidence_boost(self, base_confidence: float,
                                ms_score: float, direction: str) -> float:
        """
        Apply market structure boost to signal confidence.
        Returns adjusted confidence in [0.0, 1.0].

        ms_score > 0 (near support) + LONG  = bullish alignment → boost
        ms_score < 0 (near resistance) + SHORT = bearish alignment → boost
        Misalignment = slight penalty.
        """
        alignment = (ms_score > 0 and direction == 'LONG') or \
                    (ms_score < 0 and direction == 'SHORT')
        misalign  = (ms_score > 0 and direction == 'SHORT') or \
                    (ms_score < 0 and direction == 'LONG')

        if alignment:
            return min(1.0, base_confidence * 1.20)  # +20% boost
        elif misalign:
            return max(0.0, base_confidence * 0.85)  # -15% penalty
        return base_confidence
