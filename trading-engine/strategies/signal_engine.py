"""
Multi-Factor Signal Engine — TradingClaw v5
============================================
Replaces the old 3-strategy + STRATEGY_MAP approach.
Each bar is scored by 5 factor groups. Composite score drives entry/size.

Factor weights are dynamically adjusted based on HMM regime:
  Regime Trending-Up/Down: favor Trend + Momentum factors
  Regime Ranging:          favor MeanReversion + Volume factors
  Regime Volatile:         favor Momentum + Volatility factors
"""
from __future__ import annotations

import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import Optional, List, Dict

import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (
    COMPOSITE_ENTRY_THRESHOLD, COMPOSITE_STRONG_THRESHOLD,
    FACTOR_WEIGHT_TREND, FACTOR_WEIGHT_MEAN_REV,
    FACTOR_WEIGHT_MOMENTUM, FACTOR_WEIGHT_VOLUME, FACTOR_WEIGHT_VOLATILITY,
    TAKER_FEE, SLIPPAGE, FEE_MULTIPLIER,
    CHANDELIER_PERIOD, CHANDELIER_MULT, SWING_LOOKBACK,
    PARTIAL_TP1_R, PARTIAL_TP2_R,
)

from strategies.factors.trend import TrendFactor
from strategies.factors.mean_reversion import MeanReversionFactor
from strategies.factors.momentum import MomentumFactor
from strategies.factors.volume_flow import VolumeFlowFactor
from strategies.factors.volatility import VolatilityFactor


# ─── Regime weights ───
# Keys: 0=Trending-Up, 1=Ranging, 2=Volatile, 3=Trending-Down (HMM states)
REGIME_WEIGHTS: Dict[int, Dict[str, float]] = {
    0: dict(trend=0.35, mean_rev=0.10, momentum=0.25, volume=0.20, volatility=0.10),  # Trending-Up
    1: dict(trend=0.10, mean_rev=0.35, momentum=0.15, volume=0.25, volatility=0.15),  # Ranging
    2: dict(trend=0.15, mean_rev=0.15, momentum=0.25, volume=0.20, volatility=0.25),  # Volatile
    3: dict(trend=0.35, mean_rev=0.10, momentum=0.25, volume=0.20, volatility=0.10),  # Trending-Down
}
DEFAULT_WEIGHTS = dict(trend=FACTOR_WEIGHT_TREND, mean_rev=FACTOR_WEIGHT_MEAN_REV,
                       momentum=FACTOR_WEIGHT_MOMENTUM, volume=FACTOR_WEIGHT_VOLUME,
                       volatility=FACTOR_WEIGHT_VOLATILITY)


@dataclass
class Signal:
    """Trade signal from composite scoring."""
    timestamp: pd.Timestamp
    direction: str           # "LONG" or "SHORT"
    entry_price: float
    stop_loss: float
    take_profit: float       # Primary TP (1R)
    take_profit_2: float     # 2R TP
    atr: float
    regime: int
    strategy: str            # Factor combination description
    confidence: float        # 0-1 (derived from |composite_score|)
    expected_profit_pct: float
    composite_score: float   # Raw composite in [-1, 1]

    @property
    def risk_reward(self) -> float:
        risk = abs(self.entry_price - self.stop_loss)
        reward = abs(self.take_profit - self.entry_price)
        return reward / risk if risk > 0 else 0


class SignalEngine:
    """
    Orchestrates 5 factor groups into composite signals.
    Replaces generate_all_signals() / TrendStrategy / RangeStrategy / VolatileStrategy.
    """

    def __init__(self):
        self.trend_factor = TrendFactor()
        self.mr_factor = MeanReversionFactor()
        self.mom_factor = MomentumFactor()
        self.vol_flow_factor = VolumeFlowFactor()
        self.volatility_factor = VolatilityFactor()

        self._total_fees = (TAKER_FEE * 2) + SLIPPAGE
        self._min_profit_pct = self._total_fees * FEE_MULTIPLIER * 100

    @property
    def volume_flow(self) -> VolumeFlowFactor:
        """Expose volume_flow factor for external cache updates."""
        return self.vol_flow_factor

    def compute_composite(self, df: pd.DataFrame, df_4h: pd.DataFrame = None,
                           regime: int = -1, symbol: str = None) -> pd.DataFrame:
        """
        Compute per-bar composite scores.
        Returns DataFrame with columns: trend, mean_rev, momentum, volume, volatility, composite, direction.
        """
        weights = REGIME_WEIGHTS.get(regime, DEFAULT_WEIGHTS)

        t_scores = self.trend_factor.score(df, df_4h)
        mr_scores = self.mr_factor.score(df, df_4h)
        mom_scores = self.mom_factor.score(df, df_4h)
        vf_raw = self.vol_flow_factor.score(df, df_4h, symbol=symbol)
        vol_scores = self.volatility_factor.score(df, df_4h)

        composite = (
            t_scores * weights['trend'] +
            mr_scores * weights['mean_rev'] +
            mom_scores * weights['momentum'] +
            vf_raw * weights['volume'] +
            vol_scores * weights['volatility']
        )

        result = pd.DataFrame({
            'trend': t_scores,
            'mean_rev': mr_scores,
            'momentum': mom_scores,
            'volume': vf_raw,
            'volatility': vol_scores,
            'composite': composite,
        }, index=df.index)

        return result

    def generate_signals(self, df: pd.DataFrame, df_4h: pd.DataFrame = None,
                          regime: int = -1, symbol: str = None) -> List[Signal]:
        """
        Generate trade signals for the latest bar.
        Entry when |composite| crosses COMPOSITE_ENTRY_THRESHOLD on the most recent candle.
        Returns list (usually 0 or 1 signal).
        """
        if len(df) < 60:
            return []

        scores_df = self.compute_composite(df, df_4h, regime, symbol)
        last = df.iloc[-1]
        last_idx = df.index[-1]
        last_scores = scores_df.iloc[-1]

        composite = float(last_scores['composite'])
        if abs(composite) < COMPOSITE_ENTRY_THRESHOLD:
            return []

        # ─── Signal confirmation: composite must CROSS threshold (not just be above it) ───
        # Prevents entering mid-trend on a signal that's been above threshold for many bars.
        # Require a crossover: prev bar was below threshold, current bar is above.
        if len(scores_df) >= 2:
            prev_composite = float(scores_df['composite'].iloc[-2])
            just_crossed = abs(prev_composite) < COMPOSITE_ENTRY_THRESHOLD
            # Allow entry if this is a fresh cross OR if score strengthened significantly
            score_surge = abs(composite) - abs(prev_composite) > COMPOSITE_ENTRY_THRESHOLD * 0.5
            if not just_crossed and not score_surge:
                return []  # Signal is stale (already above threshold for multiple bars)

        direction = "LONG" if composite > 0 else "SHORT"
        confidence = min(abs(composite) / COMPOSITE_STRONG_THRESHOLD, 1.0)

        atr = float(last.get('atr_14', last['close'] * 0.01))
        close = float(last['close'])

        if atr <= 0:
            return []

        # ─── Stop Loss: structure-based (swing) ───
        sl = self._calculate_sl(df, direction, atr)
        if sl <= 0:
            return []

        risk = abs(close - sl)
        if risk < close * 0.001:  # Min 0.1% risk
            return []

        # ─── Take Profits: 1R and 2R ───
        if direction == "LONG":
            tp1 = close + risk * PARTIAL_TP1_R
            tp2 = close + risk * PARTIAL_TP2_R
        else:
            tp1 = close - risk * PARTIAL_TP1_R
            tp2 = close - risk * PARTIAL_TP2_R

        expected_profit_pct = abs(tp1 - close) / close * 100

        # ─── Fee filter: must be profitable after fees ───
        if expected_profit_pct < self._min_profit_pct:
            return []

        # ─── Build strategy name from dominant factors ───
        factor_labels = ['Trend', 'MeanRev', 'Momentum', 'Volume', 'Volatility']
        factor_values = [last_scores['trend'], last_scores['mean_rev'],
                         last_scores['momentum'], last_scores['volume'], last_scores['volatility']]
        dominant_idx = int(np.argmax([abs(v) for v in factor_values]))
        strategy_name = f"MultiF_{factor_labels[dominant_idx]}"

        return [Signal(
            timestamp=last_idx,
            direction=direction,
            entry_price=close,
            stop_loss=sl,
            take_profit=tp1,
            take_profit_2=tp2,
            atr=atr,
            regime=regime,
            strategy=strategy_name,
            confidence=confidence,
            expected_profit_pct=expected_profit_pct,
            composite_score=composite,
        )]

    def _calculate_sl(self, df: pd.DataFrame, direction: str, atr: float) -> float:
        """
        Structure-based SL: below recent swing low (LONG) or above swing high (SHORT).
        Falls back to Chandelier Exit, then ATR-based.
        """
        close = float(df['close'].iloc[-1])
        lookback = min(SWING_LOOKBACK, len(df) - 1)

        # Volatility-adjusted ATR multiplier
        vol_mult = float(self.volatility_factor.atr_multiplier(df).iloc[-1])

        try:
            if direction == "LONG":
                # Swing low = local minimum
                recent_lows = df['low'].iloc[-lookback:]
                swing_low = float(recent_lows.min())
                sl_atr = close - atr * vol_mult
                sl = max(swing_low * 0.998, sl_atr)  # Just below swing low

                # Chandelier: highest_high - ATR * mult
                if len(df) >= CHANDELIER_PERIOD:
                    chandelier = float(df['high'].iloc[-CHANDELIER_PERIOD:].max()) - atr * CHANDELIER_MULT
                    sl = max(sl, chandelier * 0.995)

            else:  # SHORT
                recent_highs = df['high'].iloc[-lookback:]
                swing_high = float(recent_highs.max())
                sl_atr = close + atr * vol_mult
                sl = min(swing_high * 1.002, sl_atr)

                if len(df) >= CHANDELIER_PERIOD:
                    chandelier = float(df['low'].iloc[-CHANDELIER_PERIOD:].min()) + atr * CHANDELIER_MULT
                    sl = min(sl, chandelier * 1.005)

            # Safety: SL must be at least 0.5% from entry
            min_dist = close * 0.005
            if direction == "LONG":
                sl = min(sl, close - min_dist)
            else:
                sl = max(sl, close + min_dist)

        except Exception:
            sl = (close - atr * vol_mult) if direction == "LONG" else (close + atr * vol_mult)

        return sl


def check_exit_signals(position: dict, current_price: float, df: pd.DataFrame = None) -> dict:
    """Check if any exit signal is triggered for an open position."""
    result = {'exit': False, 'reason': None}
    entry = float(position.get('entry_fill_price') or position.get('entry_price', 0))
    sl = float(position.get('stop_loss', 0))
    tp = float(position.get('take_profit', 0))
    direction = position.get('direction', 'LONG')

    if direction == 'LONG':
        if sl > 0 and current_price <= sl:
            result = {'exit': True, 'reason': 'Stop Loss'}
        elif tp > 0 and current_price >= tp:
            result = {'exit': True, 'reason': 'Take Profit'}
    else:
        if sl > 0 and current_price >= sl:
            result = {'exit': True, 'reason': 'Stop Loss'}
        elif tp > 0 and current_price <= tp:
            result = {'exit': True, 'reason': 'Take Profit'}
    return result
