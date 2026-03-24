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
    MR_BB_PCT_MAX, MR_RSI_MAX, MR_ADX_MAX, MR_CONFIDENCE_MIN, MR_MIN_RR,
    REGIME_CONFIDENCE_MIN,
    # v4 config constants
    MTF_ENABLED, MTF_MIN_ALIGNMENT, MTF_TREND_WEIGHT, MTF_CONFIRM_WEIGHT,
    MTF_BYPASS_IF_NO_HTF,
    SESSION_FILTER_ENABLED, ASIAN_SESSION, EUROPE_SESSION, US_SESSION, DEAD_ZONE_HOURS,
    # v5 new strategy constants
    PULLBACK_ADX_MIN, PULLBACK_EMA_ZONE, PULLBACK_RSI_MIN, PULLBACK_RSI_MAX,
    PULLBACK_VOL_DECLINE_BARS, PULLBACK_TP_R,
    SESSION_OPEN_LOOKBACK_BARS, SESSION_OPEN_VOLUME_MIN, SESSION_OPEN_TP_RANGE_MULT,
    LONDON_OPEN_HOURS, NY_OPEN_HOURS,
    RSI_DIV_ADX_MAX, RSI_DIV_TP_R,
)
from core.regime_detector import TRENDING_UP, TRENDING_DOWN, RANGING, VOLATILE, REGIME_NAMES


# ─── Regime weights (for compatibility / reporting) ────────────
REGIME_WEIGHTS: Dict[int, Dict[str, float]] = {
    TRENDING_UP:   dict(trend=0.35, breakout=0.15, mean_rev=0.00, momentum=0.10, pullback=0.30, session=0.10),
    TRENDING_DOWN: dict(trend=0.35, breakout=0.15, mean_rev=0.00, momentum=0.10, pullback=0.30, session=0.10),
    RANGING:       dict(trend=0.05, breakout=0.10, mean_rev=0.40, momentum=0.15, pullback=0.05, session=0.10, rsi_div=0.15),
    VOLATILE:      dict(trend=0.10, breakout=0.45, mean_rev=0.00, momentum=0.20, pullback=0.05, session=0.20),
}
DEFAULT_WEIGHTS = dict(trend=0.20, breakout=0.25, mean_rev=0.10, momentum=0.15, pullback=0.15, session=0.10, rsi_div=0.05)


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
        if self._mtf_enabled and htf_data is not None and (not isinstance(htf_data, dict) or htf_data):
            mtf_score, mtf_aligned = self._compute_mtf_confluence(df, htf_data, regime)
            # FIX #1: Hard gate only wenn HTF data exists AND alignment is below minimum
            # If no HTF data → bypass (don't penalize signal)
            if mtf_aligned < MTF_MIN_ALIGNMENT:
                return []
        elif self._mtf_enabled and not htf_data:
            # FIX #1: No HTF data at all → bypass MTF gate entirely
            # MTF_BYPASS_IF_NO_HTF=True: treat as neutral (score=0.5, aligned=1)
            if MTF_BYPASS_IF_NO_HTF:
                mtf_score = 0.5
                mtf_aligned = MTF_MIN_ALIGNMENT  # satisfy gate

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

        # Strategy 3: Mean Reversion — Ranging only, strict
        if regime == RANGING and regime_confidence >= MR_CONFIDENCE_MIN:
            sig = self._mean_reversion(
                df, regime, atr, close, mtf_score, mtf_aligned, session_bonus
            )
            if sig:
                signals.append(sig)

        # Strategy 4: Pullback in Trend — Trending regimes (institutional-style entry)
        if regime in (TRENDING_UP, TRENDING_DOWN):
            sig = self._pullback_trend(
                df, regime, atr, close, mtf_score, mtf_aligned, session_bonus
            )
            if sig:
                signals.append(sig)

        # Strategy 5: Session Open Breakout — London/NY opens only
        if self._session_enabled:
            sig = self._session_open_breakout(
                df, regime, atr, close, mtf_score, mtf_aligned, session_bonus
            )
            if sig:
                signals.append(sig)

        # Strategy 6: RSI Divergence — any regime, strongest when ADX < 30
        sig = self._rsi_divergence_entry(
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
            squeeze_genuine = bb_width_percentile < 15  # v5: <20 → <15, only genuine squeeze
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

        # v5: Hard reject failed breakouts — negative expectancy, no point entering
        if failed_breakout_risk:
            return None
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

        # v5: Volume climax = likely fake breakout, hard reject
        if is_climax:
            return None

        # Score calculation
        vol_score = min((vol_ratio - BREAKOUT_VOLUME_MULT) / 2.0, 1.0)
        squeeze_bonus = 0.15 if squeeze_genuine else 0.0
        atr_bonus = 0.10 if atr_expanding else 0.0
        mtf_bonus = mtf_score * 0.15 if mtf_aligned >= MTF_MIN_ALIGNMENT else 0.0

        # v5: Retest confirmation bonus — breakout happened recently and price retested level
        retest_bonus = 0.0
        if len(df) >= 5:
            for i in range(2, 5):
                bar = df.iloc[-i]
                if direction == "LONG":
                    if float(bar['low']) <= don_high <= float(bar['high']):
                        retest_bonus = 0.10  # Price tested breakout level and held
                        break
                else:
                    if float(bar['low']) <= don_low <= float(bar['high']):
                        retest_bonus = 0.10
                        break

        confidence = min(
            0.55 + vol_score * 0.25 + squeeze_bonus + atr_bonus + mtf_bonus + retest_bonus,
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

        # ─── Compute gate variables ────
        bb_extreme_bullish = bb_pct <= MR_BB_PCT_MAX
        bb_extreme_bearish = bb_pct >= (1.0 - MR_BB_PCT_MAX)
        rsi_extreme_bullish = rsi <= MR_RSI_MAX
        rsi_extreme_bearish = rsi >= (100 - MR_RSI_MAX)

        # VWAP extreme: price at least 0.2% away from VWAP
        vwap_dist = abs(close - vwap) / vwap if vwap > 0 else 0.0
        vwap_extreme = vwap_dist > 0.002
        vwap_bullish = close < vwap
        vwap_bearish = close > vwap

        # Stochastic RSI confirmation (use stoch_rsi_k if available)
        stoch_rsi_ok = True
        for col in ('stoch_rsi_k', 'stoch_rsi'):
            if col in df.columns:
                stoch_val = float(df[col].iloc[-1] or 50)
                stoch_rsi_ok = (rsi <= MR_RSI_MAX and stoch_val < 25) or \
                               (rsi >= (100 - MR_RSI_MAX) and stoch_val > 75)
                break

        # ─── v5: Determine direction from hard gates (BB + RSI) ────
        if bb_extreme_bullish and rsi_extreme_bullish:
            direction = "LONG"
        elif bb_extreme_bearish and rsi_extreme_bearish:
            direction = "SHORT"
        else:
            return None

        # ─── v5: Score 4 bonus conditions (need >= 2 to proceed) ────
        # Required: BB extreme + RSI extreme (above)
        # Scored:   VWAP, StochRSI, Volume exhaustion, Reversal candle
        vol_3bar = df['volume'].iloc[-3:].values
        vol_exhaustion = False
        if len(vol_3bar) >= 3:
            vol_declining_count = sum(
                vol_3bar[i] < vol_3bar[i - 1] for i in range(1, len(vol_3bar))
            )
            vol_exhaustion = vol_declining_count >= 2 or (vol_ma > 0 and vol_ratio < 1.5)
        else:
            vol_exhaustion = vol_ma > 0 and vol_ratio < 1.5

        reversal = (curr_close > curr_open) if direction == "LONG" else (curr_close < curr_open)

        bonus_score = 0
        if direction == "LONG":
            if vwap_bullish and vwap_extreme:  bonus_score += 1
            if stoch_rsi_ok:                   bonus_score += 1
            if vol_exhaustion:                 bonus_score += 1
            if reversal:                       bonus_score += 1
        else:
            if vwap_bearish and vwap_extreme:  bonus_score += 1
            if stoch_rsi_ok:                   bonus_score += 1
            if vol_exhaustion:                 bonus_score += 1
            if reversal:                       bonus_score += 1

        if bonus_score < 2:  # Need at least 2 of 4 bonus conditions
            return None

        # Confidence from confluence strength + bonus score
        if direction == "LONG":
            bb_extreme_score = max(0.0, (MR_BB_PCT_MAX - bb_pct) / MR_BB_PCT_MAX)
            rsi_extreme_score = max(0.0, (MR_RSI_MAX - rsi) / MR_RSI_MAX)
        else:
            bb_extreme_score = max(0.0, (bb_pct - (1 - MR_BB_PCT_MAX)) / MR_BB_PCT_MAX)
            rsi_extreme_score = max(0.0, (rsi - (100 - MR_RSI_MAX)) / MR_RSI_MAX)

        vwap_score = min(vwap_dist / 0.01, 1.0)  # Normalized to 1% threshold
        bonus_contribution = (bonus_score / 4.0) * 0.15  # up to 15% from bonus conditions
        mtf_bonus = mtf_score * 0.15 if mtf_aligned >= MTF_MIN_ALIGNMENT else 0.0

        confidence = min(
            0.50 +
            bb_extreme_score * 0.20 +
            rsi_extreme_score * 0.20 +
            vwap_score * 0.10 +
            bonus_contribution +
            mtf_bonus,
            0.88
        )
        confidence += session_bonus
        confidence = max(confidence, 0.40)

        # FIX #4: MeanRev SL — use BB band as stop instead of swing low
        # BB band = natural volatility boundary; price that breaks this invalidates the MR signal
        lookback = min(SWING_LOOKBACK, len(df) - 1)
        if direction == "LONG":
            # SL = BB lower band (if available) else ATR-based
            if 'bb_lower' in df.columns:
                bb_lower = float(df['bb_lower'].iloc[-1] or (close - atr * 2.0))
                sl = min(bb_lower * 0.998, close - atr * 2.0)  # whichever is tighter (further from close)
            else:
                swing = float(df['low'].iloc[-lookback:].min())
                sl = min(swing * 0.997, close - atr * 2.0)
        else:
            if 'bb_upper' in df.columns:
                bb_upper = float(df['bb_upper'].iloc[-1] or (close + atr * 2.0))
                sl = max(bb_upper * 1.002, close + atr * 2.0)
            else:
                swing = float(df['high'].iloc[-lookback:].max())
                sl = max(swing * 1.003, close + atr * 2.0)

        sl = self._safety_sl(sl, direction, close)
        if sl <= 0:
            return None

        risk = abs(close - sl)
        if risk < close * 0.003:
            return None

        # v5: Dynamic TP — use whichever target (EMA21 or VWAP20) is closer and reachable
        ema21_target = ema21
        vwap_20_val = float(last.get('vwap_20', ema21) or ema21)

        if direction == "LONG":
            # Closest target ABOVE current price
            candidates = [t for t in [ema21_target, vwap_20_val] if t > close]
            mean_target = min(candidates) if candidates else ema21_target
            if mean_target <= close:
                return None
        else:
            # Closest target BELOW current price
            candidates = [t for t in [ema21_target, vwap_20_val] if t < close]
            mean_target = max(candidates) if candidates else ema21_target
            if mean_target >= close:
                return None

        tp1 = mean_target
        # Secondary TP: Fibonacci extension
        if direction == "LONG":
            tp2 = mean_target + (mean_target - close) * 0.382
        else:
            tp2 = mean_target - (close - mean_target) * 0.382

        # FIX #2: enforce R:R ≥ MR_MIN_RR (2.0) for MeanRev
        rr = abs(tp1 - close) / risk if risk > 0 else 0
        if rr < MR_MIN_RR:
            # Adjust TP to meet minimum MR_MIN_RR
            tp1 = close + (risk * MR_MIN_RR) if direction == "LONG" else close - (risk * MR_MIN_RR)
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

    # ─── Strategy 4: Pullback in Trend ───────────────────────────────────────

    def _pullback_trend(
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
        Pullback in Trend — institutional-style entry on mean-reversion within trending markets.

        Catches the "dip buy / rally sell" pattern used by professional traders.
        Superior R:R vs raw breakout entries. Only active in confirmed TRENDING regimes.

        Conditions:
        - ADX > PULLBACK_ADX_MIN (trend confirmed)
        - EMA9/21/50 aligned with regime direction
        - Price within PULLBACK_EMA_ZONE of EMA21 (or within 1% of EMA50)
        - RSI in neutral zone PULLBACK_RSI_MIN–PULLBACK_RSI_MAX (not overbought at entry)
        - Volume declining 2+ bars (pullback losing steam = exhaustion confirmed)
        - MACD histogram still positive (LONG) / negative (SHORT) — trend intact

        Exit: SL = swing L/H + 0.3 ATR, TP = PULLBACK_TP_R (3.0) x risk
        """
        last = df.iloc[-1]
        cols_needed = ['ema_9', 'ema_21', 'ema_50', 'adx', 'macd_hist', 'rsi_14', 'volume', 'volume_ma_20']
        if not all(c in df.columns for c in cols_needed):
            return None
        if len(df) < 30:
            return None

        adx      = float(last.get('adx', 0) or 0)
        ema9     = float(last['ema_9'])
        ema21    = float(last['ema_21'])
        ema50    = float(last['ema_50'])
        macd_h   = float(last.get('macd_hist', 0) or 0)
        rsi      = float(last.get('rsi_14', 50) or 50)
        vol      = float(last.get('volume', 0) or 0)
        vol_ma   = float(last.get('volume_ma_20', vol) or vol)

        if adx < PULLBACK_ADX_MIN:
            return None

        if regime == TRENDING_UP:
            direction = "LONG"
            if not (ema9 > ema21 and ema21 > ema50):  # Bull EMA alignment required
                return None
            ema21_dist = abs(close - ema21) / close
            ema50_dist = abs(close - ema50) / close
            if ema21_dist > PULLBACK_EMA_ZONE and ema50_dist > PULLBACK_EMA_ZONE * 2:
                return None  # Price not near EMA21 or EMA50
            if not (PULLBACK_RSI_MIN <= rsi <= PULLBACK_RSI_MAX):
                return None
            if macd_h <= 0:
                return None  # Trend must still be intact

        elif regime == TRENDING_DOWN:
            direction = "SHORT"
            if not (ema9 < ema21 and ema21 < ema50):  # Bear EMA alignment required
                return None
            ema21_dist = abs(close - ema21) / close
            ema50_dist = abs(close - ema50) / close
            if ema21_dist > PULLBACK_EMA_ZONE and ema50_dist > PULLBACK_EMA_ZONE * 2:
                return None
            if not (PULLBACK_RSI_MIN <= rsi <= PULLBACK_RSI_MAX):
                return None
            if macd_h >= 0:
                return None
        else:
            return None

        # Volume declining — pullback losing steam (exhaustion)
        vol_declining = False
        if len(df) >= 4 and vol_ma > 0:
            recent_vols = df['volume'].iloc[-4:].values
            dec_count = sum(recent_vols[i] < recent_vols[i - 1] for i in range(1, len(recent_vols)))
            vol_declining = dec_count >= PULLBACK_VOL_DECLINE_BARS

        # Score-based confidence
        adx_strength    = min((adx - PULLBACK_ADX_MIN) / 15.0, 1.0)
        ema21_closeness = max(0.0, 1.0 - (abs(close - ema21) / close / max(PULLBACK_EMA_ZONE, 1e-9)))
        rsi_centrality  = 1.0 - abs(rsi - 50) / 50.0  # RSI closer to 50 = better pullback
        vol_bonus       = 0.10 if vol_declining else 0.0
        mtf_bonus       = mtf_score * 0.15 if mtf_aligned >= MTF_MIN_ALIGNMENT else 0.0

        score = (adx_strength * 0.30 + ema21_closeness * 0.30 +
                 rsi_centrality * 0.20 + vol_bonus + mtf_bonus)

        confidence = min(0.52 + score * 0.35 + session_bonus, 0.92)
        confidence = max(confidence, 0.45)

        # SL: swing low/high + small ATR buffer
        lookback = min(SWING_LOOKBACK, len(df) - 1)
        if direction == "LONG":
            sl = float(df['low'].iloc[-lookback:].min()) - atr * 0.3
        else:
            sl = float(df['high'].iloc[-lookback:].max()) + atr * 0.3

        sl = self._safety_sl(sl, direction, close)
        if sl <= 0:
            return None

        risk = abs(close - sl)
        if risk < close * 0.003:
            return None

        tp1 = (close + risk * PULLBACK_TP_R) if direction == "LONG" else (close - risk * PULLBACK_TP_R)
        tp2 = tp1
        expected_pct = abs(tp1 - close) / close * 100
        if expected_pct < self._min_profit:
            return None

        composite = score if direction == "LONG" else -score
        return Signal(
            timestamp=df.index[-1], direction=direction,
            entry_price=close, stop_loss=sl, take_profit=tp1, take_profit_2=tp2,
            atr=atr, regime=regime, strategy="PullbackTrend",
            confidence=confidence, expected_profit_pct=expected_pct,
            composite_score=composite, vol_size_mult=self._vol_size_mult(df),
            mtf_score=mtf_score, mtf_aligned=mtf_aligned, session_bonus=session_bonus,
        )

    # ─── Strategy 5: Session Open Breakout ───────────────────────────────────

    def _session_open_breakout(
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
        Session Open Breakout — directional momentum at London/NY market opens.

        Crypto follows traditional FX session patterns. London (08-10 UTC) and
        NY (13-15 UTC) opens create strong directional moves as new capital enters.

        Entry: Break of Asian session high/low with volume surge.
        Stop:  Opposite Asian session boundary.
        TP:    SESSION_OPEN_TP_RANGE_MULT x Asian session range.
        """
        if not self._session_enabled:
            return None
        if not isinstance(df.index, pd.DatetimeIndex):
            return None
        if len(df) < SESSION_OPEN_LOOKBACK_BARS + 5:
            return None

        current_hour = df.index[-1].hour
        london_open = LONDON_OPEN_HOURS[0] <= current_hour <= LONDON_OPEN_HOURS[1]
        ny_open     = NY_OPEN_HOURS[0]     <= current_hour <= NY_OPEN_HOURS[1]
        if not london_open and not ny_open:
            return None

        last    = df.iloc[-1]
        lookback_n  = min(SESSION_OPEN_LOOKBACK_BARS, len(df) - 1)
        asian_data  = df.iloc[-(lookback_n + 1):-1]
        asian_high  = float(asian_data['high'].max())
        asian_low   = float(asian_data['low'].min())
        asian_range = asian_high - asian_low
        if asian_range < atr * 0.5:
            return None

        vol    = float(last.get('volume', 0) or 0)
        vol_ma = float(last.get('volume_ma_20', vol) or vol)
        vol_ratio = vol / vol_ma if vol_ma > 0 else 1.0
        if vol_ratio < SESSION_OPEN_VOLUME_MIN:
            return None

        prev_close      = float(df['close'].iloc[-2])
        bullish_break   = close > asian_high and prev_close <= asian_high
        bearish_break   = close < asian_low  and prev_close >= asian_low
        if not bullish_break and not bearish_break:
            return None

        direction = "LONG" if bullish_break else "SHORT"

        vol_score           = min((vol_ratio - SESSION_OPEN_VOLUME_MIN) / 2.0, 1.0)
        range_score         = min(asian_range / (atr * 3.0), 1.0)
        session_type_bonus  = 0.08 if ny_open else 0.05
        mtf_bonus           = mtf_score * 0.10 if mtf_aligned >= MTF_MIN_ALIGNMENT else 0.0

        confidence = min(
            0.55 + vol_score * 0.20 + range_score * 0.10 + session_type_bonus + mtf_bonus, 0.90
        )
        confidence = max(confidence, 0.45)

        if direction == "LONG":
            sl = asian_low  - atr * 0.2
        else:
            sl = asian_high + atr * 0.2
        sl = self._safety_sl(sl, direction, close)
        if sl <= 0:
            return None

        risk = abs(close - sl)
        if risk < close * 0.003:
            return None

        if direction == "LONG":
            tp1 = close + asian_range * SESSION_OPEN_TP_RANGE_MULT
        else:
            tp1 = close - asian_range * SESSION_OPEN_TP_RANGE_MULT

        rr = abs(tp1 - close) / risk if risk > 0 else 0
        if rr < 1.5:
            tp1 = (close + risk * 1.5) if direction == "LONG" else (close - risk * 1.5)
        tp2 = tp1

        expected_pct = abs(tp1 - close) / close * 100
        if expected_pct < self._min_profit:
            return None

        composite = confidence if direction == "LONG" else -confidence
        return Signal(
            timestamp=df.index[-1], direction=direction,
            entry_price=close, stop_loss=sl, take_profit=tp1, take_profit_2=tp2,
            atr=atr, regime=regime, strategy="SessionOpen",
            confidence=confidence, expected_profit_pct=expected_pct,
            composite_score=composite, vol_size_mult=self._vol_size_mult(df),
            mtf_score=mtf_score, mtf_aligned=mtf_aligned, session_bonus=session_bonus,
        )

    # ─── Strategy 6: RSI Divergence Entry ────────────────────────────────────

    def _rsi_divergence_entry(
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
        RSI Divergence Entry — uses the rsi_divergence column computed in features.py.

        RSI divergence (price makes new extreme but RSI doesn't follow) is one of the
        strongest counter-trend reversal signals. The feature was calculated but never
        consumed by any strategy — this closes that gap.

        Conditions:
        - rsi_divergence != 0 (detected in last 3 bars)
        - ADX < RSI_DIV_ADX_MAX (divergences fail in strong trends)
        - Confirming reversal candle
        - Volume not in climax (< 3x MA)

        Exit: SL = 1.5 ATR, TP = RSI_DIV_TP_R (2.5) x risk
        """
        if 'rsi_divergence' not in df.columns:
            return None
        if len(df) < 20:
            return None

        last = df.iloc[-1]
        # Check last 3 bars for a divergence signal (signal can persist briefly)
        rsi_div = 0.0
        for i in range(1, min(4, len(df))):
            v = float(df['rsi_divergence'].iloc[-i] or 0)
            if v != 0:
                rsi_div = v
                break

        if rsi_div == 0:
            return None

        adx       = float(last.get('adx', 25) or 25)
        rsi       = float(last.get('rsi_14', 50) or 50)
        vol       = float(last.get('volume', 0) or 0)
        vol_ma    = float(last.get('volume_ma_20', vol) or vol)
        vol_ratio = vol / vol_ma if vol_ma > 0 else 1.0
        curr_open = float(last['open'])
        curr_close = float(last['close'])

        if adx > RSI_DIV_ADX_MAX:
            return None  # Divergences unreliable in strong trends
        if vol_ratio > 3.0:
            return None  # Climax volume = dangerous

        if rsi_div > 0:  # Bullish divergence — expect bounce up
            direction = "LONG"
            if rsi > 60:  # RSI too high for bullish divergence
                return None
            if curr_close <= curr_open:  # Need bullish candle to confirm
                return None
        elif rsi_div < 0:  # Bearish divergence — expect drop
            direction = "SHORT"
            if rsi < 40:  # RSI too low for bearish divergence
                return None
            if curr_close >= curr_open:  # Need bearish candle to confirm
                return None
        else:
            return None

        rsi_extreme_score = abs(rsi - 50) / 50.0
        adx_range_score   = max(0.0, (RSI_DIV_ADX_MAX - adx) / RSI_DIV_ADX_MAX)
        vol_confirm       = min(vol_ratio / 2.0, 1.0)
        mtf_bonus         = mtf_score * 0.10 if mtf_aligned >= MTF_MIN_ALIGNMENT else 0.0

        confidence = min(
            0.50 + rsi_extreme_score * 0.20 + adx_range_score * 0.15 +
            vol_confirm * 0.10 + mtf_bonus + session_bonus,
            0.85
        )
        confidence = max(confidence, 0.40)

        sl = (close - atr * 1.5) if direction == "LONG" else (close + atr * 1.5)
        sl = self._safety_sl(sl, direction, close)
        if sl <= 0:
            return None

        risk = abs(close - sl)
        if risk < close * 0.003:
            return None

        tp1 = (close + risk * RSI_DIV_TP_R) if direction == "LONG" else (close - risk * RSI_DIV_TP_R)
        tp2 = tp1
        expected_pct = abs(tp1 - close) / close * 100
        if expected_pct < self._min_profit:
            return None

        composite = confidence if direction == "LONG" else -confidence
        return Signal(
            timestamp=df.index[-1], direction=direction,
            entry_price=close, stop_loss=sl, take_profit=tp1, take_profit_2=tp2,
            atr=atr, regime=regime, strategy="RSIDivergence",
            confidence=confidence, expected_profit_pct=expected_pct,
            composite_score=composite, vol_size_mult=self._vol_size_mult(df),
            mtf_score=mtf_score, mtf_aligned=mtf_aligned, session_bonus=session_bonus,
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
        Calculate trend take profit using risk-based minimum with S/R stretch.

        FIX #3: Old code used swing highs from recent 50 bars — these are often
        the same bars already tested, giving a very narrow TP. Now:
        - Baseline: 4.0x risk (strong R:R floor)
        - If a significant S/R level is FURTHER than baseline → use that
        - If S/R is closer than baseline → stay with baseline (don't clip winners)

        Returns:
            Take profit price level
        """
        try:
            # FIX #3: use 4.0R as floor — trade must have room to run
            risk_based_tp = close + risk * 4.0 if direction == "LONG" else close - risk * 4.0

            lookback = 50
            if len(df) < lookback:
                return risk_based_tp

            if direction == "LONG":
                # Find swing high ABOVE risk_based_tp (a further target)
                recent_data = df.tail(lookback)
                highs_stretch = recent_data[recent_data['high'] > risk_based_tp]['high']
                if len(highs_stretch) > 0:
                    # Use the nearest major resistance above the floor
                    return highs_stretch.min()
                return risk_based_tp

            else:
                # Find swing low BELOW risk_based_tp
                recent_data = df.tail(lookback)
                lows_stretch = recent_data[recent_data['low'] < risk_based_tp]['low']
                if len(lows_stretch) > 0:
                    return lows_stretch.max()
                return risk_based_tp

        except Exception:
            return close + risk * 4.0 if direction == "LONG" else close - risk * 4.0

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
