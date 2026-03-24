"""
Market Structure Factor - structure-aware confidence modifier.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


class MarketStructureFactor:
    """
    Produces a confidence multiplier from market structure context:
    - healthy trend structure -> boost confidence
    - choppy/unclear structure -> reduce confidence
    """

    def confidence_multiplier(self, df: pd.DataFrame) -> pd.Series:
        idx = df.index
        mult = pd.Series(1.0, index=idx)
        if len(df) == 0:
            return mult

        score = pd.Series(0.0, index=idx)

        if "higher_highs" in df.columns and "lower_lows" in df.columns:
            hh = df["higher_highs"].fillna(0)
            ll = df["lower_lows"].fillna(0)
            balance = (hh - ll).clip(-10, 10) / 10.0
            score += balance * 0.45

        if "price_position_in_range" in df.columns:
            pos = df["price_position_in_range"].fillna(0.5)
            # Extremes imply stronger directional intent than middle of range.
            extreme = (abs(pos - 0.5) * 2.0).clip(0, 1)
            score += (extreme - 0.5) * 0.35

        if "swing_high_distance" in df.columns and "swing_low_distance" in df.columns:
            sh = df["swing_high_distance"].fillna(20)
            sl = df["swing_low_distance"].fillna(20)
            freshness = 1.0 - ((sh + sl) / 40.0).clip(0, 1)
            score += (freshness - 0.5) * 0.20

        # Map structure score [-1, 1] to multiplier [0.85, 1.25]
        mult = 1.0 + score.clip(-1, 1) * 0.25
        return mult.clip(0.85, 1.25)

    def apply_confidence_boost(self, base_confidence: float, structure_multiplier: float, direction: str | None = None) -> float:
        boosted = float(base_confidence) * float(structure_multiplier)
        return float(np.clip(boosted, 0.0, 1.0))
