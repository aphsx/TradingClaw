"""
Signal Engine v3 — Three Clean Strategies
==========================================
Replaces 5-factor composite soup with 3 discrete strategies
that each have clear, testable edge.

STRATEGY 1 — TREND_FOLLOW (active in Trending regimes)
  Entry: EMA alignment + ADX strength + MACD momentum + volume
  Edge:  Trend persistence in crypto (momentum effect)

STRATEGY 2 — VOL_BREAKOUT (active in any regime, strongest in Volatile/Trending)
  Entry: Donchian breakout after BB squeeze + volume surge + ATR expansion
  Edge:  Post-compression breakouts have strong momentum in crypto

STRATEGY 3 — MEAN_REVERSION (only in Ranging, very tight conditions)
  Entry: Extreme BB %B + very oversold RSI + volume exhaustion + reversal candle
  Edge:  Price reversion to mean in true ranging markets
  NOTE:  Fewer trades but much higher quality — replaces old MR that was losing pre-fee

Exit Management:
  - TREND + BREAKOUT: Pure Chandelier trailing stop (no partial TPs — let winners run)
  - MEAN_REV: Single fixed TP at BB midband (EMA21) — mean reversion has a clear target
  - All:       Time stop (stale trades) + hard stop loss
"""
from __future__ import annotations

import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import Optional, List, Dict

import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (
    TAKER_FEE, SLIPPAGE, FEE_MULTIPLIER,
    CHANDELIER_PERIOD, CHANDELIER_MULT, SWING_LOOKBACK,
    TREND_ADX_MIN, TREND_EMA_ALIGN_REQUIRED,
    BREAKOUT_DONCHIAN_PERIOD, BREAKOUT_VOLUME_MULT, BREAKOUT_ATR_EXPAND,
    MR_BB_PCT_MAX, MR_RSI_MAX, MR_ADX_MAX, MR_CONFIDENCE_MIN,
    REGIME_CONFIDENCE_MIN,
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
    """Trade signal."""
    timestamp: pd.Timestamp
    direction: str           # "LONG" or "SHORT"
    entry_price: float
    stop_loss: float
    take_profit: float       # Primary TP
    take_profit_2: float     # Secondary TP
    atr: float
    regime: int
    strategy: str            # "TrendFollow", "VolBreakout", "MeanRev"
    confidence: float        # 0-1
    expected_profit_pct: float
    composite_score: float   # Approximate score in [-1, 1]
    vol_size_mult: float = 1.0

    @property
    def risk_reward(self) -> float:
        risk   = abs(self.entry_price - self.stop_loss)
        reward = abs(self.take_profit - self.entry_price)
        return reward / risk if risk > 0 else 0


class SignalEngine:
    """Generates trade signals using 3 discrete strategies."""

    def __init__(self, taker_fee=None, maker_fee=None):
        tf = taker_fee if taker_fee is not None else TAKER_FEE
        self._total_fees = (tf * 2) + SLIPPAGE
        self._min_profit = self._total_fees * FEE_MULTIPLIER * 100  # pct

    # ── Compatibility shims ──
    @property
    def volume_flow(self):
        return self
    @property
    def open_interest(self):
        return self
    def update_cache(self, *a, **kw):
        pass

    # ─── Main entry point ─────────────────────────────────────────

    def generate_signals(
        self,
        df: pd.DataFrame,
        df_4h: pd.DataFrame = None,
        regime: int = -1,
        symbol: str = None,
        btc_composite: float = 0.0,
        regime_confidence: float = 0.5,
    ) -> List[Signal]:
        """Generate at most one trade signal for the latest bar."""
        if len(df) < 60:
            return []

        last  = df.iloc[-1]
        close = float(last['close'])
        atr   = float(last.get('atr_14', close * 0.01) or (close * 0.01))
        if atr <= 0:
            return []

        # Regime confidence gate
        if regime_confidence < REGIME_CONFIDENCE_MIN:
            return []

        signals = []

        # Strategy 1: Trend Follow — Trending regimes only
        if regime in (TRENDING_UP, TRENDING_DOWN):
            sig = self._trend_follow(df, regime, atr, close)
            if sig:
                signals.append(sig)

        # Strategy 2: Volatility Breakout — any regime except Ranging
        if regime != RANGING:
            sig = self._vol_breakout(df, regime, atr, close)
            if sig:
                signals.append(sig)

        # Strategy 3: Mean Reversion — Ranging only, very strict
        if regime == RANGING and regime_confidence >= MR_CONFIDENCE_MIN:
            sig = self._mean_reversion(df, regime, atr, close)
            if sig:
                signals.append(sig)

        if not signals:
            return []
        best = max(signals, key=lambda s: s.confidence)
        return [best]

    # ─── Strategy 1: Trend Follow ─────────────────────────────────

    def _trend_follow(self, df: pd.DataFrame, regime: int,
                       atr: float, close: float) -> Optional[Signal]:
        """EMA alignment + ADX + MACD momentum + volume."""
        last = df.iloc[-1]

        cols_needed = ['ema_9', 'ema_21', 'ema_50', 'ema_200',
                        'adx', 'macd_hist', 'macd_hist_slope',
                        'volume', 'volume_ma_20', 'rsi_14']
        if not all(c in df.columns for c in cols_needed):
            return None

        adx        = float(last['adx'] or 0)
        ema9       = float(last['ema_9'])
        ema21      = float(last['ema_21'])
        ema50      = float(last['ema_50'])
        ema200     = float(last['ema_200'])
        macd_hist  = float(last['macd_hist'] or 0)
        macd_slope = float(last.get('macd_hist_slope', 0) or 0)
        vol        = float(last['volume'] or 0)
        vol_ma     = float(last.get('volume_ma_20', vol) or vol)
        rsi        = float(last.get('rsi_14', 50) or 50)
        vol_ratio  = float(last.get('volatility_ratio', 1.0) or 1.0)

        if adx < TREND_ADX_MIN:
            return None
        if vol_ratio > 2.0:
            return None

        volume_ok = (vol_ma <= 0) or (vol >= vol_ma * 0.85)

        if regime == TRENDING_UP:
            direction  = "LONG"
            # Priority: fast EMA alignment (9>21, 21>50); EMA200 optional (too slow on 5m)
            ema_checks = [ema9 > ema21, ema21 > ema50, ema50 > ema200]
            if sum(ema_checks) < TREND_EMA_ALIGN_REQUIRED:
                return None
            # Allow price slightly under ema50 — 5m can dip and recover fast
            if close < ema50 * 0.995:
                return None
            if macd_hist <= 0:
                return None
            # Wider RSI: 5m sees RSI extremes more often, 40-82 still filters chasing
            if not (40 <= rsi <= 82):
                return None
            # Softer slope check: only reject if MACD is aggressively rolling over (>1x)
            if macd_slope < -abs(macd_hist) * 1.0:
                return None

        elif regime == TRENDING_DOWN:
            direction  = "SHORT"
            ema_checks = [ema9 < ema21, ema21 < ema50, ema50 < ema200]
            if sum(ema_checks) < TREND_EMA_ALIGN_REQUIRED:
                return None
            if close > ema50 * 1.005:
                return None
            if macd_hist >= 0:
                return None
            # Wider RSI for short: 18-60 (from 22-55)
            if not (18 <= rsi <= 60):
                return None
            if macd_slope > abs(macd_hist) * 1.0:
                return None
        else:
            return None

        if not volume_ok:
            return None

        ema_aligned  = sum(ema_checks)
        ema_strength = ema_aligned / 3.0
        adx_strength = min((adx - TREND_ADX_MIN) / 15.0, 1.0)
        macd_strength = min(abs(macd_hist) / (atr * 0.1 + 1e-8), 1.0)
        score      = ema_strength * 0.40 + adx_strength * 0.35 + macd_strength * 0.25
        confidence = 0.50 + score * 0.45

        sl = self._chandelier_sl(df, direction, atr)
        if sl <= 0:
            return None
        risk = abs(close - sl)
        if risk < close * 0.003:
            return None

        # Pure trailing — set TP far away, actual exit via trailing stop
        tp1 = close + risk * 3.0 if direction == "LONG" else close - risk * 3.0
        tp2 = tp1

        expected_pct = abs(tp1 - close) / close * 100
        if expected_pct < self._min_profit:
            return None

        composite = score if direction == "LONG" else -score
        return Signal(
            timestamp=df.index[-1], direction=direction,
            entry_price=close, stop_loss=sl, take_profit=tp1, take_profit_2=tp2,
            atr=atr, regime=regime, strategy="TrendFollow",
            confidence=min(confidence, 0.98),
            expected_profit_pct=expected_pct, composite_score=composite,
            vol_size_mult=self._vol_size_mult(df),
        )

    # ─── Strategy 2: Volatility Breakout ──────────────────────────

    def _vol_breakout(self, df: pd.DataFrame, regime: int,
                       atr: float, close: float) -> Optional[Signal]:
        """Donchian breakout after BB squeeze + volume surge + ATR expansion."""
        last = df.iloc[-1]
        N    = BREAKOUT_DONCHIAN_PERIOD

        cols_needed = ['high', 'low', 'volume', 'volume_ma_20',
                        'bb_inside_keltner', 'atr_14']
        if not all(c in df.columns for c in cols_needed):
            return None
        if len(df) < N + 10:
            return None

        lookback = df.iloc[-(N + 1):-1]
        don_high = float(lookback['high'].max())
        don_low  = float(lookback['low'].min())

        vol       = float(last['volume'] or 0)
        vol_ma    = float(last.get('volume_ma_20', vol) or vol)
        vol_ratio = vol / vol_ma if vol_ma > 0 else 1.0

        atr_recent   = float(last['atr_14'] or atr)
        atr_prev     = float(df['atr_14'].iloc[-4:-1].mean() or atr)
        atr_expanding = atr_recent > atr_prev * BREAKOUT_ATR_EXPAND

        squeeze_window = df['bb_inside_keltner'].iloc[-15:-1]
        had_squeeze    = bool(squeeze_window.sum() >= 3)

        if vol_ratio < BREAKOUT_VOLUME_MULT:
            return None

        prev_close      = float(df['close'].iloc[-2])
        bullish_breakout = close > don_high and prev_close <= don_high
        bearish_breakout = close < don_low  and prev_close >= don_low

        if not bullish_breakout and not bearish_breakout:
            return None
        # On 5m: ATR expanding alone is sufficient — squeezes take many bars to form
        # On 15m+ had_squeeze was more common; on 5m allow ATR expansion without prior squeeze
        if not atr_expanding and not had_squeeze and vol_ratio < BREAKOUT_VOLUME_MULT * 1.5:
            # Only reject if ATR flat AND no squeeze AND volume only barely above threshold
            return None

        direction     = "LONG" if bullish_breakout else "SHORT"
        vol_score     = min((vol_ratio - BREAKOUT_VOLUME_MULT) / 2.0, 1.0)
        squeeze_bonus = 0.15 if had_squeeze else 0.0
        atr_bonus     = 0.10 if atr_expanding else 0.0
        confidence    = min(0.55 + vol_score * 0.25 + squeeze_bonus + atr_bonus, 0.95)

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

        tp1 = close + risk * 3.0 if direction == "LONG" else close - risk * 3.0
        tp2 = tp1

        expected_pct = abs(tp1 - close) / close * 100
        if expected_pct < self._min_profit:
            return None

        composite = confidence if direction == "LONG" else -confidence
        return Signal(
            timestamp=df.index[-1], direction=direction,
            entry_price=close, stop_loss=sl, take_profit=tp1, take_profit_2=tp2,
            atr=atr, regime=regime, strategy="VolBreakout",
            confidence=confidence, expected_profit_pct=expected_pct,
            composite_score=composite, vol_size_mult=self._vol_size_mult(df),
        )

    # ─── Strategy 3: Mean Reversion ───────────────────────────────

    def _mean_reversion(self, df: pd.DataFrame, regime: int,
                         atr: float, close: float) -> Optional[Signal]:
        """EXTREME BB + very oversold RSI + volume exhaustion + reversal candle."""
        last  = df.iloc[-1]
        last2 = df.iloc[-2] if len(df) >= 2 else last

        cols_needed = ['bb_pct', 'rsi_14', 'adx', 'volume', 'volume_ma_20',
                        'ema_21', 'close', 'open']
        if not all(c in df.columns for c in cols_needed):
            return None

        bb_pct  = float(last['bb_pct'] or 0.5)
        rsi     = float(last.get('rsi_14', 50) or 50)
        adx     = float(last.get('adx', 25) or 25)
        vol     = float(last['volume'] or 0)
        vol_ma  = float(last.get('volume_ma_20', vol) or vol)
        ema21   = float(last.get('ema_21', close) or close)
        vol_ratio = vol / vol_ma if vol_ma > 0 else 1.0

        if adx > MR_ADX_MAX:
            return None

        curr_close = float(last['close'])
        curr_open  = float(last['open'])
        prev_close = float(last2['close']) if last2 is not last else curr_close

        # Bullish MR
        if bb_pct <= MR_BB_PCT_MAX and rsi <= MR_RSI_MAX:
            direction    = "LONG"
            vol_3bar     = df['volume'].iloc[-3:].values
            # 5m: vol declining OR just not surging (ratio < 1.5) — exhaustion confirmed either way
            vol_declining = (
                (vol_3bar[-1] < vol_3bar[-2]) or
                (vol_ma > 0 and vol_ratio < 1.5)
            )
            # Reversal: current close above open (bullish candle) — don't require beating prev close
            # on 5m the bar is too short; candle color is sufficient
            reversal = (curr_close > curr_open)
            if not vol_declining or not reversal:
                return None

        # Bearish MR
        elif bb_pct >= (1.0 - MR_BB_PCT_MAX) and rsi >= (100 - MR_RSI_MAX):
            direction    = "SHORT"
            vol_3bar     = df['volume'].iloc[-3:].values
            vol_declining = (
                (vol_3bar[-1] < vol_3bar[-2]) or
                (vol_ma > 0 and vol_ratio < 1.5)
            )
            reversal = (curr_close < curr_open)
            if not vol_declining or not reversal:
                return None
        else:
            return None

        if direction == "LONG":
            bb_extreme  = max(0, (MR_BB_PCT_MAX - bb_pct) / MR_BB_PCT_MAX)
            rsi_extreme = max(0, (MR_RSI_MAX - rsi) / MR_RSI_MAX)
        else:
            bb_extreme  = max(0, (bb_pct - (1 - MR_BB_PCT_MAX)) / MR_BB_PCT_MAX)
            rsi_extreme = max(0, (rsi - (100 - MR_RSI_MAX)) / MR_RSI_MAX)

        confidence = min(0.50 + bb_extreme * 0.25 + rsi_extreme * 0.25, 0.88)

        lookback = min(SWING_LOOKBACK, len(df) - 1)
        if direction == "LONG":
            swing = float(df['low'].iloc[-lookback:].min())
            sl    = min(swing * 0.997, close - atr * 1.5)
        else:
            swing = float(df['high'].iloc[-lookback:].max())
            sl    = max(swing * 1.003, close + atr * 1.5)

        sl   = self._safety_sl(sl, direction, close)
        if sl <= 0:
            return None
        risk = abs(close - sl)
        if risk < close * 0.003:
            return None

        # TP = BB midband (EMA21)
        mean_target = ema21
        if direction == "LONG":
            if mean_target <= close:
                return None
            tp1 = mean_target
            tp2 = mean_target + (mean_target - close) * 0.3
        else:
            if mean_target >= close:
                return None
            tp1 = mean_target
            tp2 = mean_target - (close - mean_target) * 0.3

        expected_pct = abs(tp1 - close) / close * 100
        if expected_pct < self._min_profit:
            return None
        if risk > 0 and (abs(tp1 - close) / risk) < 1.2:
            return None

        composite = confidence if direction == "LONG" else -confidence
        return Signal(
            timestamp=df.index[-1], direction=direction,
            entry_price=close, stop_loss=sl, take_profit=tp1, take_profit_2=tp2,
            atr=atr, regime=regime, strategy="MeanRev",
            confidence=confidence, expected_profit_pct=expected_pct,
            composite_score=composite, vol_size_mult=self._vol_size_mult(df),
        )

    # ─── Helpers ──────────────────────────────────────────────────

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
        if 'volatility_ratio' not in df.columns:
            return 1.5
        vol_ratio = float(df['volatility_ratio'].iloc[-1] or 1.0)
        if vol_ratio > 2.0:
            return 2.5
        elif vol_ratio > 1.5:
            return 2.0
        return 1.5

    def _vol_size_mult(self, df: pd.DataFrame) -> float:
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

    def compute_composite(self, df: pd.DataFrame, df_4h=None,
                            regime: int = -1, symbol: str = None,
                            btc_composite: float = 0.0) -> pd.DataFrame:
        """Backward-compatible stub for any reporting code."""
        return pd.DataFrame({
            'trend': 0.0, 'mean_rev': 0.0, 'momentum': 0.0, 'volume': 0.0,
            'open_interest': 0.0, 'breakout': 0.0, 'volatility': 1.0, 'composite': 0.0,
        }, index=df.index)


def check_exit_signals(position: dict, current_price: float,
                        df: pd.DataFrame = None) -> dict:
    result    = {'exit': False, 'reason': None}
    sl        = float(position.get('stop_loss', 0))
    tp        = float(position.get('take_profit', 0))
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
