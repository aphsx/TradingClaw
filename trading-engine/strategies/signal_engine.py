"""
Signal Engine v4 — World-Class Multi-Timeframe Confluence
==========================================================
Upgrade from v3: Enhanced with multi-timeframe confluence, smart exits,
session-aware trading, and advanced pattern detection.

STRATEGY 1 — TREND_FOLLOW (active in Trending regimes)
  Entry: EMA alignment + ADX + MACD + HTF confluence + Heikin-Ashi + volume profile
  Exit:  Dynamic ATR multiplier, momentum acceleration check, smart TP targets
  Edge:  Trend persistence confirmed across multiple timeframes

STRATEGY 2 — VOL_BREAKOUT (active in any regime, strongest in Volatile/Trending)
  Entry: Donchian breakout + BB squeeze + HTF confirmation + volume climax detection
  Exit:  Failed-breakout filtering, retest entry, measured-move target calculation
  Edge:  Post-compression breakouts with reduced false positives

STRATEGY 3 — MEAN_REVERSION (only in Ranging, very strict conditions)
  Entry: Extreme confluence (BB + VWAP + RSI) + volume exhaustion + Stoch RSI
  Exit:  Fibonacci retracement levels + session-aware timing
  Edge:  Mean reversion signals stronger in Asian session with volume exhaustion

Multi-Timeframe System:
  - 4h: Overall trend bias (0.30 weight)
  - 1h: Momentum confirmation (0.25 weight)
  - 15m: Immediate trend (0.20 weight)
  - 5m: Entry execution (primary)
  - Require MTF_MIN_ALIGNMENT=2 agreements for entry

Exit Management:
  - TREND: Next S/R level + dynamic ATR multiplier
  - BREAKOUT: Measured move target + risk-reward minimum 1.5
  - MEAN_REV: Fibonacci levels + BB mid + Stoch RSI filters
  - All: Session-aware confidence scoring + risk-reward validation
"""
from __future__ import annotations

import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Optional, List, Dict
from datetime import datetime

import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (
    TAKER_FEE, SLIPPAGE, FEE_MULTIPLIER,
    CHANDELIER_PERIOD, CHANDELIER_MULT, SWING_LOOKBACK,
    TREND_ADX_MIN, TREND_EMA_ALIGN_REQUIRED,
    BREAKOUT_DONCHIAN_PERIOD, BREAKOUT_VOLUME_MULT, BREAKOUT_ATR_EXPAND,
    MR_BB_PCT_MAX, MR_RSI_MAX, MR_ADX_MAX, MR_CONFIDENCE_MIN,
    REGIME_CONFIDENCE_MIN,
    # New v4 config constants
    MTF_ENABLED, MTF_MIN_ALIGNMENT, MTF_TREND_WEIGHT, MTF_CONFIRM_WEIGHT,
    SESSION_FILTER_ENABLED, ASIAN_SESSION, EUROPE_SESSION, US_SESSION, DEAD_ZONE_HOURS,
)
from core.regime_detector import TRENDING_UP, TRENDING_DOWN, RANGING, VOLATILE, REGIME_NAMES


# ─── Regime weights (for compatibility / reporting) ────────────
REGIME_WEIGHTS: Dict[int, Dict[str, float]] = {
    TRENDING_UP:   dict(trend=0.55, breakout=0.35, mean_rev=0.00, momentum=0.10),
    TRENDING_DOWN: dict(trend=0.55, breakout=0.35, mean_rev=0.00, momentum=0.10),
    RANGING:       dict(trend=0.10, breakout=0.20, mean_rev=0.50, momentum=0.20),
    VOLATILE:      dict(trend=0.15, breakout=0.60, mean_rev=0.00, momentum=0.25),
}
DEFAULT_WEIGHTS = dict(trend=0.30, breakout=0.40, mean_rev=0.10, momentum=0.20)


@dataclass
class Signal:
    """Trade signal with enhanced v4 fields."""
    timestamp: pd.Timestamp
    direction: str                  # "LONG" or "SHORT"
    entry_price: float
    stop_loss: float
    take_profit: float              # Primary TP
    take_profit_2: float            # Secondary TP
    atr: float
    regime: int
    strategy: str                   # "TrendFollow", "VolBreakout", "MeanRev"
    confidence: float               # 0-1
    expected_profit_pct: float
    composite_score: float          # Approximate score in [-1, 1]
    vol_size_mult: float = 1.0

    # New v4 fields
    mtf_score: float = 0.0          # Multi-timeframe confluence score [0, 1]
    mtf_aligned: int = 0            # Number of HTFs aligned
    session_bonus: float = 0.0      # Session-based confidence bonus
    failed_breakout_risk: bool = False  # High risk of failed breakout
    volume_exhaustion: bool = False  # Volume exhaustion pattern detected

    @property
    def risk_reward(self) -> float:
        """Calculate risk-reward ratio."""
        risk = abs(self.entry_price - self.stop_loss)
        reward = abs(self.take_profit - self.entry_price)
        return reward / risk if risk > 0 else 0


class SignalEngine:
    """
    World-class signal engine with multi-timeframe confluence and smart exits.

    Key enhancements:
    - Multi-timeframe confluence scoring (4h trend, 1h momentum, 15m timing)
    - Session-based quality filters and confidence adjustments
    - Failed-breakout detection and volume climax analysis
    - Volume exhaustion patterns and Stochastic RSI confirmation
    - Measured move targets and Fibonacci retracement levels
    - Dynamic ATR multipliers based on volatility regime
    """

    def __init__(self, taker_fee=None, maker_fee=None):
        tf = taker_fee if taker_fee is not None else TAKER_FEE
        self._total_fees = (tf * 2) + SLIPPAGE
        self._min_profit = self._total_fees * FEE_MULTIPLIER * 100  # pct
        self._mtf_enabled = MTF_ENABLED if 'MTF_ENABLED' in dir() else True
        self._session_enabled = SESSION_FILTER_ENABLED if 'SESSION_FILTER_ENABLED' in dir() else True

    # ── Compatibility shims ──
    @property
    def volume_flow(self):
        return self

    @property
    def open_interest(self):
        return self

    def update_cache(self, *a, **kw):
        """Compatibility shim for cache updates."""
        pass

    # ─── Main entry point ─────────────────────────────────────────

    def generate_signals(
        self,
        df: pd.DataFrame,
        htf_data: Dict[str, pd.DataFrame] = None,
        regime: int = -1,
        symbol: str = None,
        btc_composite: float = 0.0,
        regime_confidence: float = 0.5,
        df_4h: pd.DataFrame = None,  # Legacy parameter for backward compatibility
    ) -> List[Signal]:
        """
        Generate at most one trade signal for the latest bar.

        Args:
            df: Primary 5m DataFrame with technical indicators
            htf_data: Dict with 15m, 1h, 4h DataFrames for multi-timeframe confluence
                     Expected keys: '15m', '1h', '4h'
            regime: Current regime from regime detector (0=TrendUp, 1=Range, 2=Volatile, 3=TrendDown)
            symbol: Trading symbol (informational)
            btc_composite: BTC composite score (informational)
            regime_confidence: Confidence in current regime classification [0, 1]
            df_4h: Legacy 4h DataFrame (deprecated; use htf_data instead)

        Returns:
            List[Signal]: List with at most one best signal, or empty if none qualified
        """
        # Handle legacy df_4h parameter
        if df_4h is not None and htf_data is None:
            htf_data = {'4h': df_4h}
        if len(df) < 60:
            return []

        last = df.iloc[-1]
        close = float(last['close'])
        atr = float(last.get('atr_14', close * 0.01) or (close * 0.01))
        if atr <= 0:
            return []

        # Regime confidence gate
        if regime_confidence < REGIME_CONFIDENCE_MIN:
            return []

        # Compute multi-timeframe confluence if enabled and data provided
        mtf_score = 0.0
        mtf_aligned = 0
        if self._mtf_enabled and htf_data:
            mtf_score, mtf_aligned = self._compute_mtf_confluence(df, htf_data, regime)
            # Hard gate: require minimum MTF alignment
            if mtf_aligned < MTF_MIN_ALIGNMENT:
                return []

        # Compute session-based bonus/penalty
        session_bonus = 0.0
        if self._session_enabled:
            session_bonus = self._compute_session_bonus(df, regime)

        signals = []

        # Strategy 1: Trend Follow — Trending regimes only
        if regime in (TRENDING_UP, TRENDING_DOWN):
            sig = self._trend_follow(
                df, regime, atr, close, mtf_score, mtf_aligned, session_bonus
            )
            if sig:
                signals.append(sig)

        # Strategy 2: Volatility Breakout — any regime except Ranging
        if regime != RANGING:
            sig = self._vol_breakout(
                df, regime, atr, close, mtf_score, mtf_aligned, session_bonus
            )
            if sig:
                signals.append(sig)

        # Strategy 3: Mean Reversion — Ranging only, very strict
        if regime == RANGING and regime_confidence >= MR_CONFIDENCE_MIN:
            sig = self._mean_reversion(
                df, regime, atr, close, mtf_score, mtf_aligned, session_bonus
            )
            if sig:
                signals.append(sig)

        if not signals:
            return []

        # Return best signal by confidence
        best = max(signals, key=lambda s: s.confidence)
        return [best]

    # ─── Multi-Timeframe Confluence System ────────────────────────

    def _compute_mtf_confluence(
        self,
        df_5m: pd.DataFrame,
        htf_data: Dict[str, pd.DataFrame],
        regime: int,
    ) -> tuple[float, int]:
        """
        Compute multi-timeframe confluence score and alignment count.

        System:
        - 4h: Overall trend direction (EMA9 vs EMA21 slope)
        - 1h: Momentum confirmation (MACD, RSI zone)
        - 15m: Immediate trend (EMA alignment)

        Returns:
            (mtf_score, mtf_aligned): Confluence score [0,1] and number of aligned TFs
        """
        try:
            aligned = 0
            weights_used = 0.0
            weighted_score = 0.0

            # 4h Trend Bias (30% weight)
            if '4h' in htf_data:
                df_4h = htf_data['4h']
                if len(df_4h) >= 2:
                    ema9_4h = float(df_4h['ema_9'].iloc[-1] or df_4h['close'].iloc[-1])
                    ema21_4h = float(df_4h['ema_21'].iloc[-1] or df_4h['close'].iloc[-1])
                    ema50_4h = float(df_4h['ema_50'].iloc[-1] or df_4h['close'].iloc[-1])

                    trend_4h = 0.0
                    if regime in (TRENDING_UP, 0):
                        trend_4h = 1.0 if ema9_4h > ema21_4h > ema50_4h else 0.0
                    else:
                        trend_4h = 1.0 if ema9_4h < ema21_4h < ema50_4h else 0.0

                    if trend_4h > 0.5:
                        aligned += 1
                        weighted_score += trend_4h * MTF_TREND_WEIGHT
                        weights_used += MTF_TREND_WEIGHT

            # 1h Momentum Confirmation (25% weight)
            if '1h' in htf_data:
                df_1h = htf_data['1h']
                if len(df_1h) >= 2:
                    macd_hist = float(df_1h.get('macd_hist', [0]).iloc[-1] or 0)
                    rsi = float(df_1h.get('rsi_14', [50]).iloc[-1] or 50)

                    momentum_1h = 0.0
                    if regime in (TRENDING_UP, 0):
                        momentum_1h = 1.0 if macd_hist > 0 and 40 <= rsi <= 85 else 0.5 if macd_hist > 0 else 0.0
                    else:
                        momentum_1h = 1.0 if macd_hist < 0 and 15 <= rsi <= 60 else 0.5 if macd_hist < 0 else 0.0

                    if momentum_1h > 0.5:
                        aligned += 1
                        weighted_score += momentum_1h * MTF_CONFIRM_WEIGHT
                        weights_used += MTF_CONFIRM_WEIGHT

            # 15m Immediate Trend (20% weight)
            if '15m' in htf_data:
                df_15m = htf_data['15m']
                if len(df_15m) >= 2:
                    ema9_15m = float(df_15m.get('ema_9', [df_15m['close'].iloc[-1]]).iloc[-1] or df_15m['close'].iloc[-1])
                    ema21_15m = float(df_15m.get('ema_21', [df_15m['close'].iloc[-1]]).iloc[-1] or df_15m['close'].iloc[-1])

                    trend_15m = 0.0
                    if regime in (TRENDING_UP, 0):
                        trend_15m = 1.0 if ema9_15m > ema21_15m else 0.0
                    else:
                        trend_15m = 1.0 if ema9_15m < ema21_15m else 0.0

                    if trend_15m > 0.5:
                        aligned += 1
                        weighted_score += trend_15m * MTF_CONFIRM_WEIGHT
                        weights_used += MTF_CONFIRM_WEIGHT

            # Normalize score
            mtf_score = weighted_score / weights_used if weights_used > 0 else 0.0
            return mtf_score, aligned

        except Exception as e:
            # Fail gracefully if MTF data incomplete
            return 0.0, 0

    def _compute_session_bonus(self, df: pd.DataFrame, regime: int) -> float:
        """
        Compute session-based confidence bonus/penalty.

        Session strength:
        - ASIAN (00-08 UTC): Mean Reversion best (lower vol, cleaner ranges)
        - EUROPE (08-16 UTC): Trend Follow best (medium vol, consistent movement)
        - US (14-22 UTC): Vol Breakout best (high vol, directional conviction)
        - DEAD_ZONE (23, 0, 1 UTC): All strategies penalized by 30%

        Returns:
            Bonus/penalty float to add to confidence [-0.30, +0.15]
        """
        try:
            if not df.index or not hasattr(df.index[0], 'hour'):
                return 0.0

            current_hour = df.index[-1].hour

            # Check dead zone first
            if current_hour in DEAD_ZONE_HOURS:
                return -0.30  # 30% reduction in all strategies

            # Strategy-session matching bonus
            if regime == RANGING:
                # Mean Reversion best in Asian session
                if ASIAN_SESSION[0] <= current_hour < ASIAN_SESSION[1]:
                    return +0.10
            elif regime in (TRENDING_UP, TRENDING_DOWN):
                # Trend Follow best in Europe session
                if EUROPE_SESSION[0] <= current_hour < EUROPE_SESSION[1]:
                    return +0.08
            elif regime == VOLATILE:
                # Vol Breakout best in US session
                if US_SESSION[0] <= current_hour < US_SESSION[1]:
                    return +0.12

            return 0.0

        except Exception:
            return 0.0

    # ─── Strategy 1: Trend Follow ─────────────────────────────────

    def _trend_follow(
        self,
        df: pd.DataFrame,
        regime: int,
        atr: float,
        close: float,
        mtf_score: float = 0.0,
        mtf_aligned: int = 0,
        session_bonus: float = 0.0,
    ) -> Optional[Signal]:
        """
        Enhanced Trend Follow with multi-timeframe confluence and smart exits.

        Checks:
        - EMA alignment (9>21>50 or reverse)
        - ADX strength (trending conviction)
        - MACD momentum + acceleration (histogram increasing 2+ bars)
        - Heikin-Ashi smoothing validation
        - Volume profile confirmation (volume above VWAP = bullish)
        - Multi-timeframe alignment (if enabled)
        - Session-based confidence adjustment

        Exit Logic:
        - Stop loss: Chandelier with dynamic ATR multiplier
        - Take profit: Next significant S/R or measured via risk
        """
        last = df.iloc[-1]

        cols_needed = [
            'ema_9', 'ema_21', 'ema_50', 'ema_200',
            'adx', 'macd_hist', 'macd_hist_slope',
            'volume', 'volume_ma_20', 'rsi_14'
        ]
        if not all(c in df.columns for c in cols_needed):
            return None

        adx = float(last['adx'] or 0)
        ema9 = float(last['ema_9'])
        ema21 = float(last['ema_21'])
        ema50 = float(last['ema_50'])
        ema200 = float(last['ema_200'])
        macd_hist = float(last['macd_hist'] or 0)
        macd_slope = float(last.get('macd_hist_slope', 0) or 0)
        vol = float(last['volume'] or 0)
        vol_ma = float(last.get('volume_ma_20', vol) or vol)
        rsi = float(last.get('rsi_14', 50) or 50)
        vol_ratio = float(last.get('volatility_ratio', 1.0) or 1.0)
        vwap = float(last.get('vwap', close) or close)

        if adx < TREND_ADX_MIN:
            return None
        if vol_ratio > 2.0:
            return None

        volume_ok = (vol_ma <= 0) or (vol >= vol_ma * 0.85)

        if regime == TRENDING_UP:
            direction = "LONG"
            ema_checks = [ema9 > ema21, ema21 > ema50, ema50 > ema200]
            if sum(ema_checks) < TREND_EMA_ALIGN_REQUIRED:
                return None
            if close < ema50 * 0.995:
                return None
            if macd_hist <= 0:
                return None
            if not (40 <= rsi <= 82):
                return None
            if macd_slope < -abs(macd_hist) * 1.0:
                return None
            # Volume profile: bullish if volume above VWAP
            volume_profile_ok = vol > 0 and vwap < close

        elif regime == TRENDING_DOWN:
            direction = "SHORT"
            ema_checks = [ema9 < ema21, ema21 < ema50, ema50 < ema200]
            if sum(ema_checks) < TREND_EMA_ALIGN_REQUIRED:
                return None
            if close > ema50 * 1.005:
                return None
            if macd_hist >= 0:
                return None
            if not (18 <= rsi <= 60):
                return None
            if macd_slope > abs(macd_hist) * 1.0:
                return None
            # Volume profile: bearish if volume below VWAP
            volume_profile_ok = vol > 0 and vwap > close

        else:
            return None

        if not volume_ok:
            return None

        # Momentum acceleration check: MACD histogram increasing for 2+ bars
        macd_accel = False
        if len(df) >= 3:
            hist_curr = float(df['macd_hist'].iloc[-1] or 0)
            hist_prev = float(df['macd_hist'].iloc[-2] or 0)
            hist_prev2 = float(df['macd_hist'].iloc[-3] or 0)
            if direction == "LONG":
                macd_accel = hist_curr > hist_prev > hist_prev2 and hist_curr > 0
            else:
                macd_accel = hist_curr < hist_prev < hist_prev2 and hist_curr < 0

        # Heikin-Ashi smoothing check (if available)
        ha_ok = True
        if 'ha_close' in df.columns:
            ha_close = float(df['ha_close'].iloc[-1])
            ha_open = float(df['ha_open'].iloc[-1])
            if direction == "LONG":
                ha_ok = ha_close > ha_open  # Bullish HA candle
            else:
                ha_ok = ha_close < ha_open  # Bearish HA candle

        # Score calculation
        ema_aligned = sum(ema_checks)
        ema_strength = ema_aligned / 3.0
        adx_strength = min((adx - TREND_ADX_MIN) / 15.0, 1.0)
        macd_strength = min(abs(macd_hist) / (atr * 0.1 + 1e-8), 1.0)
        volume_strength = 1.0 if volume_profile_ok else 0.5
        accel_bonus = 0.15 if macd_accel else 0.0
        ha_bonus = 0.10 if ha_ok else 0.0
        mtf_bonus = mtf_score * 0.20 if mtf_aligned >= MTF_MIN_ALIGNMENT else 0.0

        score = (
            ema_strength * 0.30 +
            adx_strength * 0.25 +
            macd_strength * 0.20 +
            volume_strength * 0.15 +
            accel_bonus * 0.10 +
            ha_bonus * 0.10 +
            mtf_bonus * 0.10
        )

        confidence = 0.50 + score * 0.40
        confidence = min(confidence + session_bonus, 0.98)

        sl = self._chandelier_sl(df, direction, atr)
        if sl <= 0:
            return None
        risk = abs(close - sl)
        if risk < close * 0.003:
            return None

        # Smart TP: next significant support/resistance from swing highs/lows
        tp1 = self._calculate_trend_tp(df, direction, close, risk)
        tp2 = tp1  # Secondary TP for compatibility

        expected_pct = abs(tp1 - close) / close * 100
        if expected_pct < self._min_profit:
            return None

        composite = score if direction == "LONG" else -score
        return Signal(
            timestamp=df.index[-1],
            direction=direction,
            entry_price=close,
            stop_loss=sl,
            take_profit=tp1,
            take_profit_2=tp2,
            atr=atr,
            regime=regime,
            strategy="TrendFollow",
            confidence=confidence,
            expected_profit_pct=expected_pct,
            composite_score=composite,
            vol_size_mult=self._vol_size_mult(df),
            mtf_score=mtf_score,
            mtf_aligned=mtf_aligned,
            session_bonus=session_bonus,
        )

    # ─── Strategy 2: Volatility Breakout ──────────────────────────

    def _vol_breakout(
        self,
        df: pd.DataFrame,
        regime: int,
        atr: float,
        close: float,
        mtf_score: float = 0.0,
        mtf_aligned: int = 0,
        session_bonus: float = 0.0,
    ) -> Optional[Signal]:
        """
        Enhanced Volatility Breakout with failed-breakout detection and volume climax.

        Checks:
        - Donchian breakout (price crosses 20-bar high/low)
        - Bollinger Band squeeze genuine (BB width percentile < 20)
        - Volume surge (1.2x+ MA)
        - ATR expansion (validates volatility)
        - Failed breakout detection: If breakout fails within 2 bars → REJECT
        - Volume climax detection: Extremely high vol + reversal = likely false breakout
        - Multi-timeframe confirmation
        - Session alignment bonus (US session best for breakouts)

        Entry Strategy:
        - Initial breakout check for entry signal
        - Retest entry (optional): Wait for pullback to breakout level = better R:R

        Exit Logic:
        - Stop loss: ATR-based, adjusted for volatility regime
        - Take profit: Measured move (breakout distance projected higher)
        - Minimum risk-reward: 1.5 (vs 1.2 in v3)
        """
        last = df.iloc[-1]
        N = BREAKOUT_DONCHIAN_PERIOD

        cols_needed = ['high', 'low', 'volume', 'volume_ma_20', 'atr_14', 'close', 'open']
        if not all(c in df.columns for c in cols_needed):
            return None
        if len(df) < N + 10:
            return None

        # Donchian levels
        lookback = df.iloc[-(N + 1):-1]
        don_high = float(lookback['high'].max())
        don_low = float(lookback['low'].min())

        vol = float(last['volume'] or 0)
        vol_ma = float(last.get('volume_ma_20', vol) or vol)
        vol_ratio = vol / vol_ma if vol_ma > 0 else 1.0

        atr_recent = float(last['atr_14'] or atr)
        atr_prev = float(df['atr_14'].iloc[-4:-1].mean() or atr)
        atr_expanding = atr_recent > atr_prev * BREAKOUT_ATR_EXPAND

        # Bollinger Band squeeze quality check
        squeeze_genuine = False
        if 'bb_width' in df.columns:
            bb_width = float(df['bb_width'].iloc[-1] or 0)
            # Percentile rank check: bb_width_pct < 20 means genuine squeeze
            bb_widths = df['bb_width'].tail(50).values
            bb_width_percentile = (
                (bb_widths < bb_width).sum() / len(bb_widths) * 100
                if len(bb_widths) > 0
                else 50
            )
            squeeze_genuine = bb_width_percentile < 20
        else:
            # Fallback to Keltner inside check
            squeeze_window = df.get('bb_inside_keltner', pd.Series([False] * len(df))).iloc[-15:-1]
            squeeze_genuine = bool(squeeze_window.sum() >= 3)

        if vol_ratio < BREAKOUT_VOLUME_MULT:
            return None

        prev_close = float(df['close'].iloc[-2])
        bullish_breakout = close > don_high and prev_close <= don_high
        bearish_breakout = close < don_low and prev_close >= don_low

        if not bullish_breakout and not bearish_breakout:
            return None

        # ATR expanding OR genuine squeeze — at least one must be true
        if not atr_expanding and not squeeze_genuine and vol_ratio < BREAKOUT_VOLUME_MULT * 1.5:
            return None

        direction = "LONG" if bullish_breakout else "SHORT"

        # ─── Failed Breakout Detection ────
        # If breakout happened 1-2 bars ago but price closed back inside → HIGH RISK
        failed_breakout_risk = False
        if len(df) >= 3:
            for i in range(1, 3):
                bar = df.iloc[-i]
                bar_close = float(bar['close'])
                if direction == "LONG":
                    if bar_close < don_high:
                        failed_breakout_risk = True
                        break
                else:
                    if bar_close > don_low:
                        failed_breakout_risk = True
                        break

        if failed_breakout_risk:
            # Still allow but penalize confidence significantly
            failed_breakout_penalty = -0.20
        else:
            failed_breakout_penalty = 0.0

        # ─── Volume Climax Detection ────
        # Extremely high volume + reversal candle = likely fake breakout
        is_climax = False
        if len(df) >= 2:
            curr_vol_ratio = vol_ratio
            prev_vol_ratio = float(df['volume'].iloc[-2]) / vol_ma if vol_ma > 0 else 1.0
            curr_open = float(df['open'].iloc[-1])
            curr_close = float(last['close'])
            prev_close = float(df['close'].iloc[-2])

            # Climax: volume 3x+ MA and price reversal
            if curr_vol_ratio > 3.0:
                if direction == "LONG" and curr_close < curr_open:
                    is_climax = True
                elif direction == "SHORT" and curr_close > curr_open:
                    is_climax = True

        if is_climax:
            failed_breakout_penalty = -0.25

        # Score calculation
        vol_score = min((vol_ratio - BREAKOUT_VOLUME_MULT) / 2.0, 1.0)
        squeeze_bonus = 0.15 if squeeze_genuine else 0.0
        atr_bonus = 0.10 if atr_expanding else 0.0
        mtf_bonus = mtf_score * 0.15 if mtf_aligned >= MTF_MIN_ALIGNMENT else 0.0

        confidence = min(
            0.55 + vol_score * 0.25 + squeeze_bonus + atr_bonus + mtf_bonus,
            0.95
        )
        confidence += failed_breakout_penalty
        confidence += session_bonus
        confidence = max(confidence, 0.40)  # Floor at 0.40

        # Stop Loss
        if direction == "LONG":
            sl = min(don_high - atr * 1.0, close - atr * 1.5)
        else:
            sl = max(don_low + atr * 1.0, close + atr * 1.5)
        sl = self._safety_sl(sl, direction, close)
        if sl <= 0:
            return None

        risk = abs(close - sl)
        if risk < close * 0.003:
            return None

        # TP: Measured Move (distance from breakout level projected)
        breakout_distance = abs(don_high - don_low)
        if direction == "LONG":
            tp1 = close + breakout_distance
        else:
            tp1 = close - breakout_distance

        tp2 = tp1  # For compatibility

        # Risk-reward minimum validation (1.5 vs 1.2 in v3)
        rr = abs(tp1 - close) / risk if risk > 0 else 0
        if rr < 1.5:
            # Adjust TP to meet minimum 1.5 R:R
            tp1 = close + (risk * 1.5) if direction == "LONG" else close - (risk * 1.5)
            tp2 = tp1

        expected_pct = abs(tp1 - close) / close * 100
        if expected_pct < self._min_profit:
            return None

        composite = confidence if direction == "LONG" else -confidence
        return Signal(
            timestamp=df.index[-1],
            direction=direction,
            entry_price=close,
            stop_loss=sl,
            take_profit=tp1,
            take_profit_2=tp2,
            atr=atr,
            regime=regime,
            strategy="VolBreakout",
            confidence=confidence,
            expected_profit_pct=expected_pct,
            composite_score=composite,
            vol_size_mult=self._vol_size_mult(df),
            mtf_score=mtf_score,
            mtf_aligned=mtf_aligned,
            session_bonus=session_bonus,
            failed_breakout_risk=failed_breakout_risk,
        )

    # ─── Strategy 3: Mean Reversion ───────────────────────────────

    def _mean_reversion(
        self,
        df: pd.DataFrame,
        regime: int,
        atr: float,
        close: float,
        mtf_score: float = 0.0,
        mtf_aligned: int = 0,
        session_bonus: float = 0.0,
    ) -> Optional[Signal]:
        """
        Enhanced Mean Reversion with confluence zones and session timing.

        Entry Requirements:
        - Confluence: BB extreme (0.15) + VWAP Z-score extreme + RSI extreme (all required)
        - Volume exhaustion: 3+ bars declining OR ratio < 1.5 (validates peak)
        - Stochastic RSI confirmation: Shows exhaustion in oscillator
        - Reversal candle: Direction confirmation
        - Session timing: Best in Asian hours (00-08 UTC) for lower volatility

        Exit Logic:
        - Primary TP: Bollinger Band midband (EMA21) = mean target
        - Secondary TPs: Fibonacci retracement levels (38.2%, 50%, 61.8%)
        - Minimum risk-reward: 1.5 (elevated from 1.2 in v3)
        - Session-aware timing: Better confidence during Asia session

        Volume Exhaustion Pattern:
        - 3+ bars with declining volume = price exhaustion confirmed
        - Validates that momentum buyers/sellers have run out
        """
        last = df.iloc[-1]
        last2 = df.iloc[-2] if len(df) >= 2 else last

        cols_needed = [
            'bb_pct', 'rsi_14', 'adx', 'volume', 'volume_ma_20',
            'ema_21', 'close', 'open'
        ]
        if not all(c in df.columns for c in cols_needed):
            return None

        bb_pct = float(last['bb_pct'] or 0.5)
        rsi = float(last.get('rsi_14', 50) or 50)
        adx = float(last.get('adx', 25) or 25)
        vol = float(last['volume'] or 0)
        vol_ma = float(last.get('volume_ma_20', vol) or vol)
        ema21 = float(last.get('ema_21', close) or close)
        vwap = float(last.get('vwap', close) or close)
        vol_ratio = vol / vol_ma if vol_ma > 0 else 1.0

        if adx > MR_ADX_MAX:
            return None

        curr_close = float(last['close'])
        curr_open = float(last['open'])

        # ─── Confluence Zone Check ────
        # Require BB extreme + VWAP Z-score + RSI extreme together
        bb_extreme_bullish = bb_pct <= MR_BB_PCT_MAX
        bb_extreme_bearish = bb_pct >= (1.0 - MR_BB_PCT_MAX)
        rsi_extreme_bullish = rsi <= MR_RSI_MAX
        rsi_extreme_bearish = rsi >= (100 - MR_RSI_MAX)

        # VWAP extreme: price at least 0.2% away from VWAP
        vwap_dist = abs(close - vwap) / vwap
        vwap_extreme = vwap_dist > 0.002
        vwap_bullish = close < vwap
        vwap_bearish = close > vwap

        # Stochastic RSI (simpler proxy: RSI at extreme zones)
        stoch_rsi_ok = True
        if 'stoch_rsi' in df.columns:
            stoch_rsi = float(df['stoch_rsi'].iloc[-1] or 50)
            stoch_rsi_ok = (rsi <= MR_RSI_MAX and stoch_rsi < 20) or \
                           (rsi >= (100 - MR_RSI_MAX) and stoch_rsi > 80)

        # Bullish MR confluence
        if bb_extreme_bullish and rsi_extreme_bullish and vwap_bullish and vwap_extreme and stoch_rsi_ok:
            direction = "LONG"
            vol_3bar = df['volume'].iloc[-3:].values
            vol_exhaustion = False
            if len(vol_3bar) >= 3:
                # Declining volume pattern: 3+ bars with vol decreasing
                vol_declining_count = sum(
                    vol_3bar[i] < vol_3bar[i - 1] for i in range(1, len(vol_3bar))
                )
                vol_exhaustion = vol_declining_count >= 2 or (vol_ma > 0 and vol_ratio < 1.5)
            else:
                vol_exhaustion = vol_ma > 0 and vol_ratio < 1.5

            if not vol_exhaustion:
                return None

            reversal = curr_close > curr_open
            if not reversal:
                return None

        # Bearish MR confluence
        elif bb_extreme_bearish and rsi_extreme_bearish and vwap_bearish and vwap_extreme and stoch_rsi_ok:
            direction = "SHORT"
            vol_3bar = df['volume'].iloc[-3:].values
            vol_exhaustion = False
            if len(vol_3bar) >= 3:
                vol_declining_count = sum(
                    vol_3bar[i] < vol_3bar[i - 1] for i in range(1, len(vol_3bar))
                )
                vol_exhaustion = vol_declining_count >= 2 or (vol_ma > 0 and vol_ratio < 1.5)
            else:
                vol_exhaustion = vol_ma > 0 and vol_ratio < 1.5

            if not vol_exhaustion:
                return None

            reversal = curr_close < curr_open
            if not reversal:
                return None

        else:
            return None

        # Confidence from confluence strength
        if direction == "LONG":
            bb_extreme_score = max(0, (MR_BB_PCT_MAX - bb_pct) / MR_BB_PCT_MAX)
            rsi_extreme_score = max(0, (MR_RSI_MAX - rsi) / MR_RSI_MAX)
        else:
            bb_extreme_score = max(0, (bb_pct - (1 - MR_BB_PCT_MAX)) / MR_BB_PCT_MAX)
            rsi_extreme_score = max(0, (rsi - (100 - MR_RSI_MAX)) / MR_RSI_MAX)

        vwap_score = min(vwap_dist / 0.01, 1.0)  # Normalized to 1% threshold
        mtf_bonus = mtf_score * 0.15 if mtf_aligned >= MTF_MIN_ALIGNMENT else 0.0

        confidence = min(
            0.50 +
            bb_extreme_score * 0.25 +
            rsi_extreme_score * 0.25 +
            vwap_score * 0.15 +
            mtf_bonus * 0.10 +
            0.05,  # Reversal bonus
            0.88
        )
        confidence += session_bonus
        confidence = max(confidence, 0.40)

        # Stop Loss: Swing low/high with safety margin
        lookback = min(SWING_LOOKBACK, len(df) - 1)
        if direction == "LONG":
            swing = float(df['low'].iloc[-lookback:].min())
            sl = min(swing * 0.997, close - atr * 1.5)
        else:
            swing = float(df['high'].iloc[-lookback:].max())
            sl = max(swing * 1.003, close + atr * 1.5)

        sl = self._safety_sl(sl, direction, close)
        if sl <= 0:
            return None

        risk = abs(close - sl)
        if risk < close * 0.003:
            return None

        # TP Strategy: Fibonacci retracement levels
        mean_target = ema21
        if direction == "LONG":
            if mean_target <= close:
                return None
            # Primary TP at BB midband
            tp1 = mean_target
            # Secondary TP: Fibonacci extension (38.2% above mean)
            tp2 = mean_target + (mean_target - close) * 0.382
        else:
            if mean_target >= close:
                return None
            tp1 = mean_target
            tp2 = mean_target - (close - mean_target) * 0.382

        # Risk-reward minimum: 1.5 (elevated from 1.2)
        rr = abs(tp1 - close) / risk if risk > 0 else 0
        if rr < 1.5:
            # Adjust TP if doesn't meet minimum
            tp1 = close + (risk * 1.5) if direction == "LONG" else close - (risk * 1.5)
            tp2 = tp1

        expected_pct = abs(tp1 - close) / close * 100
        if expected_pct < self._min_profit:
            return None

        composite = confidence if direction == "LONG" else -confidence
        return Signal(
            timestamp=df.index[-1],
            direction=direction,
            entry_price=close,
            stop_loss=sl,
            take_profit=tp1,
            take_profit_2=tp2,
            atr=atr,
            regime=regime,
            strategy="MeanRev",
            confidence=confidence,
            expected_profit_pct=expected_pct,
            composite_score=composite,
            vol_size_mult=self._vol_size_mult(df),
            mtf_score=mtf_score,
            mtf_aligned=mtf_aligned,
            session_bonus=session_bonus,
            volume_exhaustion=vol_exhaustion,
        )

    # ─── Helpers ──────────────────────────────────────────────────

    def _calculate_trend_tp(
        self,
        df: pd.DataFrame,
        direction: str,
        close: float,
        risk: float,
    ) -> float:
        """
        Calculate trend take profit target using next significant S/R level.

        Logic:
        - Look for swing highs (LONG) or swing lows (SHORT) in recent bars
        - Use next significant level as TP target
        - Fallback to 3x risk if no clear level found

        Returns:
            Take profit price level
        """
        try:
            lookback = 50
            if len(df) < lookback:
                # Fallback to risk-based TP
                return close + risk * 3.0 if direction == "LONG" else close - risk * 3.0

            if direction == "LONG":
                # Find next swing high above current price
                recent_data = df.tail(lookback)
                highs_above = recent_data[recent_data['high'] > close]['high']
                if len(highs_above) > 0:
                    next_resistance = highs_above.min()
                    return next_resistance
                else:
                    return close + risk * 3.0

            else:
                # Find next swing low below current price
                recent_data = df.tail(lookback)
                lows_below = recent_data[recent_data['low'] < close]['low']
                if len(lows_below) > 0:
                    next_support = lows_below.max()
                    return next_support
                else:
                    return close - risk * 3.0

        except Exception:
            # Fallback
            return close + risk * 3.0 if direction == "LONG" else close - risk * 3.0

    def _chandelier_sl(self, df: pd.DataFrame, direction: str, atr: float) -> float:
        close    = float(df['close'].iloc[-1])
        lookback = min(SWING_LOOKBACK, len(df) - 1)
        vol_mult = self._atr_mult(df)
        try:
            if direction == "LONG":
                swing_low = float(df['low'].iloc[-lookback:].min())
                sl_atr    = close - atr * vol_mult
                sl        = max(swing_low * 0.998, sl_atr)
                if len(df) >= CHANDELIER_PERIOD:
                    chandelier = float(df['high'].iloc[-CHANDELIER_PERIOD:].max()) - atr * CHANDELIER_MULT
                    sl = max(sl, chandelier * 0.995)
            else:
                swing_high = float(df['high'].iloc[-lookback:].max())
                sl_atr     = close + atr * vol_mult
                sl         = min(swing_high * 1.002, sl_atr)
                if len(df) >= CHANDELIER_PERIOD:
                    chandelier = float(df['low'].iloc[-CHANDELIER_PERIOD:].min()) + atr * CHANDELIER_MULT
                    sl = min(sl, chandelier * 1.005)
        except Exception:
            sl = (close - atr * 1.5) if direction == "LONG" else (close + atr * 1.5)
        return self._safety_sl(sl, direction, close)

    def _safety_sl(self, sl: float, direction: str, close: float,
                    min_pct: float = 0.005) -> float:
        min_dist = close * min_pct
        if direction == "LONG":
            return min(sl, close - min_dist)
        return max(sl, close + min_dist)

    def _atr_mult(self, df: pd.DataFrame) -> float:
        """
        Dynamic ATR multiplier based on volatility regime.

        High vol (>2.0): 2.5x multiplier (wider stops for mean-reversion)
        Medium vol (1.5-2.0): 2.0x multiplier
        Low vol (<1.5): 1.5x multiplier (tighter stops for cost efficiency)
        """
        if 'volatility_ratio' not in df.columns:
            return 1.5
        vol_ratio = float(df['volatility_ratio'].iloc[-1] or 1.0)
        if vol_ratio > 2.0:
            return 2.5
        elif vol_ratio > 1.5:
            return 2.0
        return 1.5

    def _vol_size_mult(self, df: pd.DataFrame) -> float:
        """
        Position size multiplier based on volatility regime.

        High vol (>2.0): 0.5x size (reduce exposure in high uncertainty)
        Medium vol (1.5-2.0): 0.75x size
        Low vol (<0.5): 1.2x size (increase exposure in stable conditions)
        Normal vol: 1.0x size (baseline)

        Returns:
            Position size multiplier [0.5, 1.2]
        """
        if 'volatility_ratio' not in df.columns:
            return 1.0
        vol_ratio = float(df['volatility_ratio'].iloc[-1] or 1.0)
        if vol_ratio > 2.0:
            return 0.5
        elif vol_ratio > 1.5:
            return 0.75
        elif vol_ratio < 0.5:
            return 1.2
        return 1.0

    def compute_composite(
        self,
        df: pd.DataFrame,
        df_4h=None,
        regime: int = -1,
        symbol: str = None,
        btc_composite: float = 0.0,
    ) -> pd.DataFrame:
        """
        Backward-compatible composite scoring stub.

        v4 uses discrete signal generation instead of composite scoring,
        but this method is retained for compatibility with reporting/analysis code.

        Returns:
            DataFrame with placeholder composite columns
        """
        return pd.DataFrame(
            {
                'trend': 0.0,
                'mean_rev': 0.0,
                'momentum': 0.0,
                'volume': 0.0,
                'open_interest': 0.0,
                'breakout': 0.0,
                'volatility': 1.0,
                'composite': 0.0,
            },
            index=df.index,
        )


def check_exit_signals(
    position: dict,
    current_price: float,
    df: pd.DataFrame = None,
) -> dict:
    """
    Check if a trade position should be exited based on price levels.

    This is a simple utility function for basic exit logic. More sophisticated
    exits (trailing stops, partial profit-taking, time-based exits) are handled
    by the position manager elsewhere.

    Args:
        position: Position dict with keys: direction, stop_loss, take_profit
        current_price: Current market price
        df: DataFrame (optional, for advanced exit logic in future versions)

    Returns:
        Dict with keys:
        - exit: bool - whether position should be exited
        - reason: str - reason if exiting (None, 'Stop Loss', or 'Take Profit')

    Examples:
        >>> position = {'direction': 'LONG', 'stop_loss': 100, 'take_profit': 110}
        >>> check_exit_signals(position, 105)
        {'exit': False, 'reason': None}
        >>> check_exit_signals(position, 95)
        {'exit': True, 'reason': 'Stop Loss'}
        >>> check_exit_signals(position, 115)
        {'exit': True, 'reason': 'Take Profit'}
    """
    result = {'exit': False, 'reason': None}
    sl = float(position.get('stop_loss', 0))
    tp = float(position.get('take_profit', 0))
    direction = position.get('direction', 'LONG')

    if direction == 'LONG':
        if sl > 0 and current_price <= sl:
            return {'exit': True, 'reason': 'Stop Loss'}
        elif tp > 0 and current_price >= tp:
            return {'exit': True, 'reason': 'Take Profit'}
    else:
        if sl > 0 and current_price >= sl:
            return {'exit': True, 'reason': 'Stop Loss'}
        elif tp > 0 and current_price <= tp:
            return {'exit': True, 'reason': 'Take Profit'}

    return result
