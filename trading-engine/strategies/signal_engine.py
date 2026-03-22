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
    COMPOSITE_THRESHOLD_BY_REGIME,                 # Issue #4
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
from strategies.factors.open_interest import OpenInterestFactor    # Issue #5
from strategies.factors.market_structure import MarketStructureFactor  # Issue #9


# ─── Regime weights ───
# Keys: 0=Trending-Up, 1=Ranging, 2=Volatile, 3=Trending-Down (HMM states)
#
# Issue #2: Trending-Down now has separate weights from Trending-Up.
# Downtrend crypto dynamics differ: higher funding bleed for longs, liquidation
# cascades, short-squeeze bounces → mean_rev and volume need more weight.
#
# Issue #8: Volatile regime now includes 'breakout' weight for VolatilityFactor.
# Each row except Volatile sums to 1.0; Volatile sums to 1.0 with breakout included.
REGIME_WEIGHTS: Dict[int, Dict[str, float]] = {
    0: dict(trend=0.40, mean_rev=0.10, momentum=0.28, volume=0.22, breakout=0.00),  # Trending-Up
    1: dict(trend=0.12, mean_rev=0.40, momentum=0.18, volume=0.30, breakout=0.00),  # Ranging
    2: dict(trend=0.15, mean_rev=0.15, momentum=0.28, volume=0.17, breakout=0.25),  # Volatile (Issue #8)
    3: dict(trend=0.35, mean_rev=0.18, momentum=0.22, volume=0.25, breakout=0.00),  # Trending-Down (Issue #2)
}
# Auto-normalise DEFAULT_WEIGHTS so they always sum to 1.0 even if config values change.
# (FACTOR_WEIGHT_VOLATILITY is intentionally excluded from default — size multiplier only.)
_dw_raw = dict(trend=FACTOR_WEIGHT_TREND, mean_rev=FACTOR_WEIGHT_MEAN_REV,
               momentum=FACTOR_WEIGHT_MOMENTUM, volume=FACTOR_WEIGHT_VOLUME)
_dw_total = sum(_dw_raw.values()) or 1.0
DEFAULT_WEIGHTS = {k: v / _dw_total for k, v in _dw_raw.items()}
DEFAULT_WEIGHTS['breakout'] = 0.00  # No breakout in unknown-regime default

# ─── Rolling percentile normalisation window (Issue #7) ───
_PERCENTILE_WINDOW = 200


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
    vol_size_mult: float = 1.0  # Volatility-based position size multiplier (high vol → <1.0)

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
        self.oi_factor = OpenInterestFactor()       # Issue #5
        self.ms_factor = MarketStructureFactor()    # Issue #9

        self._total_fees = (TAKER_FEE * 2) + SLIPPAGE
        self._min_profit_pct = self._total_fees * FEE_MULTIPLIER * 100

    @property
    def volume_flow(self) -> VolumeFlowFactor:
        """Expose volume_flow factor for external cache updates."""
        return self.vol_flow_factor

    @property
    def open_interest(self) -> OpenInterestFactor:
        """Expose OI factor for external cache updates (Issue #5)."""
        return self.oi_factor

    @staticmethod
    def _percentile_normalize(series: pd.Series, window: int = _PERCENTILE_WINDOW) -> pd.Series:
        """
        Issue #7 — Rolling percentile normalization.

        Converts each factor's raw score to a value in [-1, 1] based on its
        percentile rank within its own recent history (last `window` bars).
        This ensures all factors have equal distributional weight in the composite,
        regardless of whether one factor naturally produces larger magnitudes.

        Method:
          - Compute rolling rank of |score| within [0, 1]  (magnitude percentile)
          - Preserve the original sign
          - Result: sign(score) × rank_pct  ∈ [-1, 1]
        """
        if len(series) < 2:
            return series
        abs_series  = series.abs()
        rank_pct    = abs_series.rolling(window, min_periods=10).rank(pct=True).fillna(0.5)
        return series.map(lambda x: 1.0 if x > 0 else (-1.0 if x < 0 else 0.0)) * rank_pct

    def compute_composite(self, df: pd.DataFrame, df_4h: pd.DataFrame = None,
                           regime: int = -1, symbol: str = None,
                           btc_composite: float = 0.0) -> pd.DataFrame:
        """
        Compute per-bar composite scores.

        Issue #6: btc_composite — if this symbol is NOT BTC, a small portion of BTC's
        composite is blended in (10%) so BTC acts as a leading indicator.
        Issue #7: Each factor is normalized to rolling percentile rank before weighting.
        Issue #8: VolatilityFactor (breakout direction score) blended into composite
                  when regime == Volatile (2) using the 'breakout' weight key.

        Returns DataFrame with factor scores, raw_composite, composite, direction.
        """
        weights = REGIME_WEIGHTS.get(regime, DEFAULT_WEIGHTS)

        # ── Raw factor scores ──
        t_raw  = self.trend_factor.score(df, df_4h)
        mr_raw = self.mr_factor.score(df, df_4h)
        mom_raw = self.mom_factor.score(df, df_4h)
        vf_raw  = self.vol_flow_factor.score(df, df_4h, symbol=symbol)
        oi_raw  = self.oi_factor.score(df, symbol=symbol)
        # Issue #8: VolatilityFactor directional score for Volatile regime
        vol_dir = self.volatility_factor.score(df, df_4h)
        # Position size multiplier (separate from composite directional scoring)
        vol_size = self.volatility_factor.position_size_multiplier(df)

        # ── Issue #7: Percentile-normalize each factor ──
        t_scores   = self._percentile_normalize(t_raw)
        mr_scores  = self._percentile_normalize(mr_raw)
        mom_scores = self._percentile_normalize(mom_raw)
        vf_scores  = self._percentile_normalize(vf_raw)
        oi_scores  = self._percentile_normalize(oi_raw)
        vol_dir_n  = self._percentile_normalize(vol_dir)

        # ── Weighted composite ──
        vol_w      = weights['volume']
        breakout_w = weights.get('breakout', 0.0)
        composite  = (
            t_scores   * weights['trend'] +
            mr_scores  * weights['mean_rev'] +
            mom_scores * weights['momentum'] +
            vf_scores  * (vol_w * 0.90) +
            oi_scores  * (vol_w * 0.10) +
            vol_dir_n  * breakout_w          # Issue #8: breakout in Volatile regime
        )

        # ── Issue #6: BTC cross-symbol bias ──
        # Blend BTC's composite (as a scalar from the last bar) into this symbol's
        # composite with 10% weight. BTC acts as a macro filter for the crypto market.
        if abs(btc_composite) > 0.05:  # Only blend if BTC signal is meaningful
            composite = composite * 0.90 + btc_composite * 0.10

        result = pd.DataFrame({
            'trend':         t_raw,
            'mean_rev':      mr_raw,
            'momentum':      mom_raw,
            'volume':        vf_raw,
            'open_interest': oi_raw,
            'breakout':      vol_dir,
            'volatility':    vol_size,        # NOT in composite; size multiplier only
            'composite':     composite,
        }, index=df.index)

        return result

    def generate_signals(self, df: pd.DataFrame, df_4h: pd.DataFrame = None,
                          regime: int = -1, symbol: str = None,
                          btc_composite: float = 0.0) -> List[Signal]:
        """
        Generate trade signals for the latest bar.

        Issue #4: Entry threshold is now regime-specific (COMPOSITE_THRESHOLD_BY_REGIME).
        Issue #5: Normal signals require 2 consecutive bars above threshold.
                  Strong signals (≥ COMPOSITE_STRONG_THRESHOLD) fire immediately.
        Issue #6: btc_composite blended into composite inside compute_composite().

        Returns list (usually 0 or 1 signal).
        """
        if len(df) < 60:
            return []

        scores_df = self.compute_composite(df, df_4h, regime, symbol, btc_composite)
        last = df.iloc[-1]
        last_idx = df.index[-1]
        last_scores = scores_df.iloc[-1]

        composite = float(last_scores['composite'])

        # ── Issue #4: Regime-specific entry threshold ──
        entry_threshold = COMPOSITE_THRESHOLD_BY_REGIME.get(regime, COMPOSITE_ENTRY_THRESHOLD)

        if abs(composite) < entry_threshold:
            return []

        is_strong = abs(composite) >= COMPOSITE_STRONG_THRESHOLD

        # ── Issue #5: Bar confirmation logic ──
        # Strong signal (≥ COMPOSITE_STRONG_THRESHOLD): fire immediately, no wait needed.
        # Normal signal: require composite to have been above the threshold on the PREVIOUS
        #   bar too (same direction) — i.e., 2 consecutive bars confirming the move.
        # Trending-aligned re-entry: allowed when in a trend regime to stay in the move.
        if len(scores_df) >= 2 and not is_strong:
            prev_composite = float(scores_df['composite'].iloc[-2])
            just_crossed = abs(prev_composite) < entry_threshold
            score_surge  = abs(composite) - abs(prev_composite) > entry_threshold * 0.5

            # 2-bar confirmation: both bars must be above threshold AND same direction
            prev_same_direction = (prev_composite > 0) == (composite > 0)
            two_bar_confirm = (abs(prev_composite) >= entry_threshold) and prev_same_direction

            # Trending regime continuous re-entry (trend-following benefit)
            trending_regime = regime in (0, 3)
            trend_aligned = (regime == 0 and composite > 0) or (regime == 3 and composite < 0)

            if not just_crossed and not score_surge and not two_bar_confirm \
                    and not (trending_regime and trend_aligned):
                return []  # Signal is stale or not yet confirmed

        direction = "LONG" if composite > 0 else "SHORT"
        base_confidence = min(abs(composite) / COMPOSITE_STRONG_THRESHOLD, 1.0)

        # ── Issue #9: Market structure confidence boost ──
        ms_scores = self.ms_factor.confidence_multiplier(df)
        ms_last   = float(ms_scores.iloc[-1]) if len(ms_scores) > 0 else 0.0
        confidence = self.ms_factor.apply_confidence_boost(base_confidence, ms_last, direction)

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

        # ─── Volatility size multiplier (from VolatilityFactor) ───
        vol_size_mult = float(self.volatility_factor.position_size_multiplier(df).iloc[-1])

        # ─── Build strategy name from dominant factors ───
        factor_labels = ['Trend', 'MeanRev', 'Momentum', 'Volume']
        factor_values = [last_scores['trend'], last_scores['mean_rev'],
                         last_scores['momentum'], last_scores['volume']]
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
            vol_size_mult=round(vol_size_mult, 3),
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
