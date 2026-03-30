"""
Position Manager v2 — World-Class Position Lifecycle Management
================================================================
Handles:
- ATR-adaptive trailing stops (ratcheting based on profit levels)
- Smart partial profit-taking with momentum detection
- Enhanced trade health monitoring (RSI, volume, regime, time-weighted)
- Volatility-based position lifecycle adjustments
- Exit signal integration (RSI divergence, engulfing, volume spike)
- Funding cost tracking with position-size awareness
- Momentum exhaustion detection

PUBLIC API (backward compatible):
  - check_partial_tp(pos, current_price) -> Optional[dict]
  - update_chandelier_stop(pos, df) -> float
  - move_to_breakeven(pos, df) -> float
  - check_trade_health(pos, current_price, df) -> Optional[dict]
  - should_time_exit(pos) -> bool

NEW METHODS:
  - update_adaptive_trailing_stop(pos, df, current_price) -> float
  - check_smart_partial_tp(pos, current_price, strategy) -> Optional[dict]
  - get_volatility_stop_adjustment(df) -> float
  - should_exit_on_signal(pos, df, regime) -> Optional[dict]
  - _detect_momentum_exhaustion(df, direction) -> bool
  - _detect_rsi_divergence(pos, df, direction) -> bool
  - _detect_engulfing_reversal(df, direction) -> bool
  - _detect_volume_reversal(df, direction) -> bool
"""
from __future__ import annotations

import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import (
    # Legacy imports
    TRAILING_STOP_ACTIVATION, TRAILING_STOP_DISTANCE,
    CHANDELIER_PERIOD, CHANDELIER_MULT,
    MAX_FUNDING_RATE,
    TRADE_HEALTH_MIN_HOURS, TRADE_HEALTH_R_THRESHOLD, TRADE_HEALTH_SL_TIGHTEN_PCT,
    # New v2 config
    TRAILING_ATR_MULT_INITIAL,
    TRAILING_ATR_MULT_PROFIT,
    TRAILING_ATR_MULT_EXTENDED,
    TRAILING_RATCHET_ENABLED,
    TAKE_PROFIT_MODE,
    PARTIAL_TP_ENABLED,
    PARTIAL_TP_LEVEL_1_R,
    PARTIAL_TP_LEVEL_2_R,
    PARTIAL_TP_FRACTION_1,
    PARTIAL_TP_FRACTION_2,
    PARTIAL_TP_MEANREV_AT_TARGET,
)

import pandas as pd
from datetime import datetime, timezone
from typing import Optional


class PositionManager:
    """
    Manages open position lifecycle with world-class exit logic.

    Metrics tracked:
    - Adaptive trailing stops based on volatility and profit levels
    - Smart partial profit-taking at defined R-multiple levels
    - Multi-factor trade health monitoring
    - Momentum exhaustion and RSI divergence detection
    - Volatility-adjusted stop placement
    - Time-weighted urgency for losing trades
    """

    # ─── PARTIAL TP CHECKS (Backward Compatible + Enhanced) ───

    def check_partial_tp(self, pos: dict, current_price: float) -> Optional[dict]:
        """
        Legacy method: Returns dict if a partial TP should be triggered.
        Now delegates to check_smart_partial_tp for enhanced logic.

        Returns:
            {'action': 'partial_close', 'fraction': 0.33, 'reason': 'TP1', ...}
        """
        if TAKE_PROFIT_MODE == "single":
            return None
        strategy = pos.get('strategy', 'TREND')
        result = self.check_smart_partial_tp(pos, current_price, strategy)
        return result

    def check_smart_partial_tp(
        self, pos: dict, current_price: float, strategy: str = 'TREND'
    ) -> Optional[dict]:
        """
        Smart partial profit-taking at 1R and 2R levels.

        Logic:
        - At 1R profit: close PARTIAL_TP_FRACTION_1 (33%) of position
        - At 2R profit: close PARTIAL_TP_FRACTION_2 (33%) of position
        - Trail remaining with ATR-adaptive stop
        - For MeanRev: close PARTIAL_TP_MEANREV_AT_TARGET (70%) at BB mid, trail 30%

        Args:
            pos: Position dict
            current_price: Current market price
            strategy: Strategy type ('TREND', 'RANGE', 'VOLATILITY')

        Returns:
            Action dict or None
        """
        if TAKE_PROFIT_MODE == "single" or not PARTIAL_TP_ENABLED:
            return None

        entry = float(pos.get('entry_fill_price') or pos.get('entry_price', 0))
        if entry <= 0:
            return None

        direction = pos.get('direction', 'LONG')
        tp1 = float(pos.get('take_profit', 0))
        tp2 = float(pos.get('take_profit_2', 0))

        tp1_hit = pos.get('tp1_hit', False)
        tp2_hit = pos.get('tp2_hit', False)

        # Check TP1 (1R profit)
        if direction == 'LONG':
            current_r = (current_price - entry) / (entry * PARTIAL_TP_LEVEL_1_R) if entry > 0 else 0
        else:
            current_r = (entry - current_price) / (entry * PARTIAL_TP_LEVEL_1_R) if entry > 0 else 0

        # TP1 logic
        if not tp1_hit and tp1 > 0:
            if direction == 'LONG' and current_price >= tp1:
                return {
                    'action': 'partial_close',
                    'fraction': PARTIAL_TP_FRACTION_1,
                    'reason': 'TP1_SMART',
                    'price': current_price,
                    'tp_level': 1,
                    'r_multiple': round(current_r, 3),
                }
            elif direction == 'SHORT' and current_price <= tp1:
                return {
                    'action': 'partial_close',
                    'fraction': PARTIAL_TP_FRACTION_1,
                    'reason': 'TP1_SMART',
                    'price': current_price,
                    'tp_level': 1,
                    'r_multiple': round(current_r, 3),
                }

        # TP2 logic (2R profit)
        if tp1_hit and not tp2_hit and tp2 > 0:
            if direction == 'LONG':
                current_r = (current_price - entry) / (entry * PARTIAL_TP_LEVEL_2_R) if entry > 0 else 0
            else:
                current_r = (entry - current_price) / (entry * PARTIAL_TP_LEVEL_2_R) if entry > 0 else 0

            if direction == 'LONG' and current_price >= tp2:
                return {
                    'action': 'partial_close',
                    'fraction': PARTIAL_TP_FRACTION_2,
                    'reason': 'TP2_SMART',
                    'price': current_price,
                    'tp_level': 2,
                    'r_multiple': round(current_r, 3),
                }
            elif direction == 'SHORT' and current_price <= tp2:
                return {
                    'action': 'partial_close',
                    'fraction': PARTIAL_TP_FRACTION_2,
                    'reason': 'TP2_SMART',
                    'price': current_price,
                    'tp_level': 2,
                    'r_multiple': round(current_r, 3),
                }

        # MeanRev special logic: close at BB mid if strategy is RANGE
        if strategy == 'RANGE' and not tp2_hit and 'bb_mid' in pos:
            bb_mid = float(pos.get('bb_mid', 0))
            if bb_mid > 0:
                if direction == 'LONG' and current_price >= bb_mid:
                    return {
                        'action': 'partial_close',
                        'fraction': PARTIAL_TP_MEANREV_AT_TARGET,
                        'reason': 'MEANREV_BB_MID',
                        'price': current_price,
                        'bb_mid': bb_mid,
                    }
                elif direction == 'SHORT' and current_price <= bb_mid:
                    return {
                        'action': 'partial_close',
                        'fraction': PARTIAL_TP_MEANREV_AT_TARGET,
                        'reason': 'MEANREV_BB_MID',
                        'price': current_price,
                        'bb_mid': bb_mid,
                    }

        return None

    # ─── ADAPTIVE TRAILING STOPS ───

    def get_volatility_stop_adjustment(self, df: pd.DataFrame) -> float:
        """
        Get volatility-based stop adjustment multiplier.

        HIGH volatility (>1.5 ATR): widen stops by 20% (avoid whipsaws)
        LOW volatility (<0.5 ATR): tighten stops by 15% (market is calmer)

        Returns:
            Multiplier (e.g., 1.20 = 20% wider, 0.85 = 15% tighter)
        """
        if len(df) < 20 or 'atr_14' not in df.columns:
            return 1.0

        try:
            recent_atr = df['atr_14'].iloc[-20:].mean()
            avg_atr = df['atr_14'].iloc[-50:].mean()

            if avg_atr <= 0:
                return 1.0

            atr_ratio = recent_atr / avg_atr

            # HIGH volatility: widen by 20%
            if atr_ratio > 1.5:
                return 1.20
            # LOW volatility: tighten by 15%
            elif atr_ratio < 0.5:
                return 0.85
            else:
                return 1.0
        except Exception:
            return 1.0

    def update_adaptive_trailing_stop(
        self, pos: dict, df: pd.DataFrame, current_price: float
    ) -> float:
        """
        ATR-adaptive trailing stop with ratcheting.

        Logic:
        - Initial trail: ATR × TRAILING_ATR_MULT_INITIAL (2.5)
        - After 1R profit: tighten to ATR × TRAILING_ATR_MULT_PROFIT (1.8)
        - After 2R profit: tighten to ATR × TRAILING_ATR_MULT_EXTENDED (1.2)
        - Ratchet: never widens, only tightens as profit grows

        Args:
            pos: Position dict
            df: OHLCV dataframe with 'atr_14' column
            current_price: Current market price

        Returns:
            New stop loss price (only moves in favorable direction)
        """
        if not TRAILING_RATCHET_ENABLED:
            # Fall back to simple Chandelier stop
            return self.update_chandelier_stop(pos, df)

        current_sl = float(pos.get('stop_loss', 0))
        entry = float(pos.get('entry_fill_price') or pos.get('entry_price', 0))
        direction = pos.get('direction', 'LONG')

        if len(df) < 22 or 'atr_14' not in df.columns or entry <= 0:
            return current_sl

        atr = float(df['atr_14'].iloc[-1])
        if atr <= 0:
            return current_sl

        # Calculate current R-multiple (unrealized profit / risk)
        risk = abs(entry - current_sl) if current_sl > 0 else 0
        if risk <= 0:
            return current_sl

        if direction == 'LONG':
            current_r = (current_price - entry) / risk
        else:
            current_r = (entry - current_price) / risk

        # Choose ATR multiplier based on profit level
        if current_r < PARTIAL_TP_LEVEL_1_R:
            atr_mult = TRAILING_ATR_MULT_INITIAL
        elif current_r < PARTIAL_TP_LEVEL_2_R:
            atr_mult = TRAILING_ATR_MULT_PROFIT
        else:
            atr_mult = TRAILING_ATR_MULT_EXTENDED

        # Apply volatility adjustment
        vol_adjustment = self.get_volatility_stop_adjustment(df)
        atr_distance = atr * atr_mult * vol_adjustment

        # Calculate new SL based on direction
        if direction == 'LONG':
            new_sl = current_price - atr_distance
            # Only move SL up (more favorable), never down (ratchet)
            return max(new_sl, current_sl)
        else:
            new_sl = current_price + atr_distance
            # Only move SL down (more favorable), never up (ratchet)
            return min(new_sl, current_sl)

    def update_chandelier_stop(self, pos: dict, df: pd.DataFrame) -> float:
        """
        Classic Chandelier Exit trailing stop (fallback / hybrid mode).

        LONG:  highest_high(22) - ATR(22) * 3.0
        SHORT: lowest_low(22)   + ATR(22) * 3.0

        Returns new SL price (only moves in favorable direction).
        """
        current_sl = float(pos.get('stop_loss', 0))
        direction = pos.get('direction', 'LONG')
        entry = float(pos.get('entry_fill_price') or pos.get('entry_price', 0))

        if len(df) < CHANDELIER_PERIOD or 'atr_14' not in df.columns:
            return current_sl

        atr = float(df['atr_14'].iloc[-1])
        if atr <= 0:
            return current_sl

        current_price = float(df['close'].iloc[-1])

        # Activation check: only trail after 0.5% profit
        if direction == 'LONG':
            if (current_price - entry) / entry < TRAILING_STOP_ACTIVATION:
                return current_sl
            hh = float(df['high'].iloc[-CHANDELIER_PERIOD:].max())
            chandelier = hh - atr * CHANDELIER_MULT
            return max(chandelier, current_sl)  # Only move up
        else:
            if (entry - current_price) / entry < TRAILING_STOP_ACTIVATION:
                return current_sl
            ll = float(df['low'].iloc[-CHANDELIER_PERIOD:].min())
            chandelier = ll + atr * CHANDELIER_MULT
            return min(chandelier, current_sl)  # Only move down

    # ─── BREAKEVEN STOP ───

    def move_to_breakeven(self, pos: dict, df: Optional[pd.DataFrame] = None) -> float:
        """
        Smart breakeven stop (not tight entry * 1.001).

        Logic:
        - Standard: move SL to entry + 0.5 × ATR (breathing room)
        - Only activate after 1R profit is reached
        - For MeanRev: move to entry + 0.3 × ATR (tighter, since target is closer)

        Args:
            pos: Position dict
            df: Optional OHLCV dataframe for ATR-based calculation

        Returns:
            New stop loss price
        """
        entry = float(pos.get('entry_fill_price') or pos.get('entry_price', 0))
        current_sl = float(pos.get('stop_loss', 0))
        direction = pos.get('direction', 'LONG')
        strategy = pos.get('strategy', 'TREND')

        if entry <= 0:
            return current_sl

        # Only activate after 1R profit
        if not pos.get('tp1_hit'):
            return current_sl

        # Try to use ATR-based breakeven
        if df is not None and len(df) >= 22 and 'atr_14' in df.columns:
            atr = float(df['atr_14'].iloc[-1])
            if atr > 0:
                atr_mult = 0.3 if strategy == 'RANGE' else 0.5
                atr_buffer = atr * atr_mult

                if direction == 'LONG':
                    new_sl = entry + atr_buffer
                    return max(new_sl, current_sl)
                else:
                    new_sl = entry - atr_buffer
                    return min(new_sl, current_sl)

        # Fallback: simple breakeven with tiny buffer
        if direction == 'LONG':
            return max(current_sl, entry * 1.0015)
        else:
            return min(current_sl, entry * 0.9985)

    # ─── ENHANCED TRADE HEALTH MONITORING ───

    def check_trade_health(
        self, pos: dict, current_price: float, df: Optional[pd.DataFrame] = None
    ) -> Optional[dict]:
        """
        Multi-factor trade health monitoring.

        Checks:
        1. R-multiple threshold (existing)
        2. Momentum exhaustion: RSI crosses 70→below 65 (long) / 30→above 35 (short)
        3. Volume dry-up: volume drops below 50% of MA for 3+ bars while in profit
        4. Regime deterioration: confidence drops below 0.45
        5. Time-weighted urgency: losing trade tightens SL progressively
           - 6h: tighten 25%
           - 12h: tighten 50%
           - 18h: tighten 75%

        Args:
            pos: Position dict
            current_price: Current market price
            df: Optional OHLCV dataframe for advanced checks

        Returns:
            Action dict with tighten_sl instruction, or None
        """
        # Don't interfere once trade is profitable
        if pos.get('tp1_hit'):
            return None

        # Don't re-tighten if already health-tightened
        if pos.get('health_sl_tightened'):
            return None

        entry = float(pos.get('entry_fill_price') or pos.get('entry_price', 0))
        current_sl = float(pos.get('stop_loss', 0))
        direction = pos.get('direction', 'LONG')

        if entry <= 0 or current_sl <= 0:
            return None

        risk = abs(entry - current_sl)
        if risk <= 0:
            return None

        # Calculate current R-multiple
        if direction == 'LONG':
            current_r = (current_price - entry) / risk
        else:
            current_r = (entry - current_price) / risk

        # Parse entry time
        entry_time = self._parse_entry_time(pos)
        if not entry_time:
            return None

        age_hours = (datetime.now(timezone.utc) - entry_time).total_seconds() / 3600

        # ─── CHECK 1: R-MULTIPLE THRESHOLD ───
        if current_r >= TRADE_HEALTH_R_THRESHOLD:
            pass  # Trade is within acceptable range
        else:
            tighten_action = self._tighten_sl(
                current_sl, entry, risk, direction,
                reason=f'R-multiple {current_r:.2f}R < threshold {TRADE_HEALTH_R_THRESHOLD}'
            )
            if tighten_action:
                return tighten_action

        # Only proceed with advanced checks if age > min hours
        if age_hours < TRADE_HEALTH_MIN_HOURS:
            return None

        # ─── CHECK 2: MOMENTUM EXHAUSTION ───
        if df is not None:
            momentum_action = self._check_momentum_health(pos, df, current_price, direction)
            if momentum_action:
                return momentum_action

        # ─── CHECK 3: VOLUME DRY-UP ───
        if df is not None and current_r > 0:  # Only if in profit
            volume_action = self._check_volume_health(df, direction)
            if volume_action:
                return volume_action

        # ─── CHECK 4: TIME-WEIGHTED URGENCY ───
        urgency_action = self._check_time_weighted_urgency(
            age_hours, current_r, current_sl, entry, direction
        )
        if urgency_action:
            return urgency_action

        return None

    def _parse_entry_time(self, pos: dict) -> Optional[datetime]:
        """Helper: parse and validate entry time."""
        entry_time_str = pos.get('entry_time')
        if not entry_time_str:
            return None

        try:
            if isinstance(entry_time_str, str):
                entry_time = datetime.fromisoformat(entry_time_str.replace('Z', '+00:00'))
            else:
                entry_time = entry_time_str

            if entry_time.tzinfo is None:
                entry_time = entry_time.replace(tzinfo=timezone.utc)

            return entry_time
        except Exception:
            return None

    def _check_momentum_health(
        self, pos: dict, df: pd.DataFrame, current_price: float, direction: str
    ) -> Optional[dict]:
        """Check for momentum exhaustion (RSI crosses)."""
        if len(df) < 14 or 'rsi_14' not in df.columns:
            return None

        try:
            rsi_prev = float(df['rsi_14'].iloc[-2])
            rsi_curr = float(df['rsi_14'].iloc[-1])

            # LONG: RSI crosses from 70 down below 65 = exhaustion
            if direction == 'LONG' and rsi_prev > 70 and rsi_curr < 65:
                current_sl = float(pos.get('stop_loss', 0))
                entry = float(pos.get('entry_fill_price') or pos.get('entry_price', 0))
                risk = abs(entry - current_sl)
                return self._tighten_sl(
                    current_sl, entry, risk, direction,
                    reason=f'Momentum exhaustion: RSI {rsi_prev:.1f}→{rsi_curr:.1f} (bearish reversal)'
                )

            # SHORT: RSI crosses from 30 up above 35 = exhaustion
            if direction == 'SHORT' and rsi_prev < 30 and rsi_curr > 35:
                current_sl = float(pos.get('stop_loss', 0))
                entry = float(pos.get('entry_fill_price') or pos.get('entry_price', 0))
                risk = abs(entry - current_sl)
                return self._tighten_sl(
                    current_sl, entry, risk, direction,
                    reason=f'Momentum exhaustion: RSI {rsi_prev:.1f}→{rsi_curr:.1f} (bullish reversal)'
                )
        except Exception:
            pass

        return None

    def _check_volume_health(self, df: pd.DataFrame, direction: str) -> Optional[dict]:
        """Check for volume dry-up (< 50% MA for 3+ bars while in profit)."""
        if len(df) < 20 or 'volume' not in df.columns:
            return None

        try:
            vol_ma = df['volume'].rolling(20).mean().iloc[-1]
            if vol_ma <= 0:
                return None

            # Count bars with volume < 50% of MA in last 5 bars
            recent_vols = df['volume'].iloc[-5:].values
            dry_count = sum(1 for v in recent_vols if v < vol_ma * 0.5)

            if dry_count >= 3:
                return {
                    'action': 'tighten_sl',
                    'reason': f'Volume dry-up: {dry_count}/5 recent bars < 50% of MA',
                    'severity': 'warning',  # Softer tightening
                }
        except Exception:
            pass

        return None

    def _check_time_weighted_urgency(
        self, age_hours: float, current_r: float, current_sl: float,
        entry: float, direction: str
    ) -> Optional[dict]:
        """
        Time-weighted urgency for losing trades.

        After N hours with negative R: tighten SL progressively
        - 6h: tighten 25%
        - 12h: tighten 50%
        - 18h: tighten 75%
        """
        if current_r >= 0:
            return None  # Only for losing trades

        tighten_pct = 0.0
        if age_hours > 18:
            tighten_pct = 0.75
        elif age_hours > 12:
            tighten_pct = 0.50
        elif age_hours > 6:
            tighten_pct = 0.25
        else:
            return None

        risk = abs(entry - current_sl)
        return self._tighten_sl(
            current_sl, entry, risk, direction,
            reason=f'Time-weighted urgency: losing {current_r:.2f}R for {age_hours:.1f}h → tighten {tighten_pct*100:.0f}%',
            tighten_pct=tighten_pct
        )

    def _tighten_sl(
        self, current_sl: float, entry: float, risk: float, direction: str,
        reason: str, tighten_pct: float = TRADE_HEALTH_SL_TIGHTEN_PCT
    ) -> Optional[dict]:
        """Helper: calculate tightened SL."""
        if direction == 'LONG':
            new_sl = current_sl + risk * tighten_pct
            new_sl = max(new_sl, current_sl)  # Can only tighten (move up)
        else:
            new_sl = current_sl - risk * tighten_pct
            new_sl = min(new_sl, current_sl)  # Can only tighten (move down)

        return {
            'action': 'tighten_sl',
            'new_sl': new_sl,
            'old_sl': current_sl,
            'reason': reason,
        }

    # ─── EXIT SIGNAL INTEGRATION ───

    def should_exit_on_signal(
        self, pos: dict, df: pd.DataFrame, regime: dict
    ) -> Optional[dict]:
        """
        Check for exit signals based on counter-trend indicators.

        Signals:
        - RSI divergence against position direction
        - Engulfing candle against position direction
        - Volume spike against position direction

        Returns:
            {'action': 'exit_warning'/'exit_signal', 'reason': ..., 'strength': 'weak'/'strong'}
        """
        if len(df) < 14:
            return None

        direction = pos.get('direction', 'LONG')

        signals = []

        # Signal 1: RSI divergence
        rsi_signal = self._detect_rsi_divergence(pos, df, direction)
        if rsi_signal:
            signals.append(rsi_signal)

        # Signal 2: Engulfing candle
        engulf_signal = self._detect_engulfing_reversal(df, direction)
        if engulf_signal:
            signals.append(engulf_signal)

        # Signal 3: Volume spike
        vol_signal = self._detect_volume_reversal(df, direction)
        if vol_signal:
            signals.append(vol_signal)

        if not signals:
            return None

        # Aggregate signal strength
        strength_count = sum(1 for s in signals if s.get('strength') == 'strong')
        total_count = len(signals)

        # 2+ strong signals or 3/3 weak signals = exit
        if strength_count >= 2 or total_count >= 3:
            return {
                'action': 'exit_signal',
                'reason': f'{total_count} exit signals detected: {", ".join([s["reason"] for s in signals])}',
                'strength': 'strong',
                'signals': signals,
            }

        # 1 strong signal = warning
        if strength_count >= 1:
            return {
                'action': 'exit_warning',
                'reason': f'{strength_count} strong exit signal(s)',
                'strength': 'moderate',
                'signals': signals,
            }

        return {
            'action': 'exit_warning',
            'reason': f'{total_count} weak exit signal(s)',
            'strength': 'weak',
            'signals': signals,
        }

    def _detect_rsi_divergence(self, pos: dict, df: pd.DataFrame, direction: str) -> Optional[dict]:
        """Detect RSI divergence against position direction."""
        if len(df) < 14 or 'rsi_14' not in df.columns:
            return None

        try:
            # Get recent RSI and price data
            rsi_values = df['rsi_14'].iloc[-5:].values
            prices = df['close'].iloc[-5:].values

            if len(rsi_values) < 5 or len(prices) < 5:
                return None

            # LONG divergence: price makes new high but RSI doesn't
            if direction == 'LONG':
                if prices[-1] > prices[0] and rsi_values[-1] < rsi_values[0]:
                    return {
                        'reason': f'LONG bearish divergence: price {prices[0]:.2f}→{prices[-1]:.2f}, RSI {rsi_values[0]:.1f}→{rsi_values[-1]:.1f}',
                        'strength': 'strong' if rsi_values[-1] > 60 else 'weak',
                    }

            # SHORT divergence: price makes new low but RSI doesn't
            if direction == 'SHORT':
                if prices[-1] < prices[0] and rsi_values[-1] > rsi_values[0]:
                    return {
                        'reason': f'SHORT bullish divergence: price {prices[0]:.2f}→{prices[-1]:.2f}, RSI {rsi_values[0]:.1f}→{rsi_values[-1]:.1f}',
                        'strength': 'strong' if rsi_values[-1] < 40 else 'weak',
                    }
        except Exception:
            pass

        return None

    def _detect_engulfing_reversal(self, df: pd.DataFrame, direction: str) -> Optional[dict]:
        """Detect engulfing candle against position direction."""
        if len(df) < 2:
            return None

        try:
            prev_open = float(df['open'].iloc[-2])
            prev_close = float(df['close'].iloc[-2])
            curr_open = float(df['open'].iloc[-1])
            curr_close = float(df['close'].iloc[-1])

            # Bearish engulfing (against LONG)
            if direction == 'LONG':
                prev_body = abs(prev_close - prev_open)
                curr_body = abs(curr_close - curr_open)
                if (curr_open > prev_close and curr_close < prev_open and
                    curr_body > prev_body):
                    return {
                        'reason': 'Bearish engulfing candle detected',
                        'strength': 'strong' if curr_body > prev_body * 1.5 else 'weak',
                    }

            # Bullish engulfing (against SHORT)
            if direction == 'SHORT':
                prev_body = abs(prev_close - prev_open)
                curr_body = abs(curr_close - curr_open)
                if (curr_open < prev_close and curr_close > prev_open and
                    curr_body > prev_body):
                    return {
                        'reason': 'Bullish engulfing candle detected',
                        'strength': 'strong' if curr_body > prev_body * 1.5 else 'weak',
                    }
        except Exception:
            pass

        return None

    def _detect_volume_reversal(self, df: pd.DataFrame, direction: str) -> Optional[dict]:
        """Detect volume spike against position direction."""
        if len(df) < 20 or 'volume' not in df.columns:
            return None

        try:
            vol_ma = df['volume'].rolling(20).mean().iloc[-1]
            curr_vol = float(df['volume'].iloc[-1])

            if vol_ma <= 0:
                return None

            vol_ratio = curr_vol / vol_ma
            if vol_ratio < 1.5:
                return None

            curr_close = float(df['close'].iloc[-1])
            curr_open = float(df['open'].iloc[-1])

            # High volume against LONG = bearish
            if direction == 'LONG' and curr_close < curr_open:
                return {
                    'reason': f'High volume down: {vol_ratio:.2f}x MA with close < open',
                    'strength': 'strong' if vol_ratio > 2.5 else 'weak',
                }

            # High volume against SHORT = bullish
            if direction == 'SHORT' and curr_close > curr_open:
                return {
                    'reason': f'High volume up: {vol_ratio:.2f}x MA with close > open',
                    'strength': 'strong' if vol_ratio > 2.5 else 'weak',
                }
        except Exception:
            pass

        return None

    def _detect_momentum_exhaustion(self, df: pd.DataFrame, direction: str) -> bool:
        """Simple check: is momentum exhausting (RSI near extremes)."""
        if len(df) < 14 or 'rsi_14' not in df.columns:
            return False

        try:
            rsi = float(df['rsi_14'].iloc[-1])
            if direction == 'LONG' and rsi > 75:
                return True
            if direction == 'SHORT' and rsi < 25:
                return True
        except Exception:
            pass

        return False

    # ─── TIME / FUNDING EXIT ───

    def should_time_exit(self, pos: dict) -> bool:
        """
        Enhanced funding cost tracking.

        Logic:
        - Track actual cumulative funding (not just estimates)
        - Exit if cumulative funding > 60% of unrealized profit
        - For large positions (>$500 notional): lower threshold to 40%
        - Also exit if trade is stuck for 72+ hours
        """
        entry_time = self._parse_entry_time(pos)
        if not entry_time:
            return False

        try:
            age_hours = (datetime.now(timezone.utc) - entry_time).total_seconds() / 3600
            unrealized = float(pos.get('unrealized_pnl', 0))
            quantity = float(pos.get('quantity', 0))
            entry_price = float(pos.get('entry_fill_price') or pos.get('entry_price', 0))

            if quantity <= 0 or entry_price <= 0:
                return False

            notional = quantity * entry_price
            cumulative_funding = float(pos.get('cumulative_funding', 0))

            # If no actual funding tracked, estimate it
            if cumulative_funding <= 0:
                est_funding = notional * MAX_FUNDING_RATE
                cumulative_funding = est_funding * (age_hours / 8)

            # Determine funding threshold based on position size
            if notional > 500:
                funding_threshold = 0.40  # Large positions: stricter
            else:
                funding_threshold = 0.60  # Standard threshold

            # Exit if funding costs are too high relative to profit
            if age_hours > 4 and unrealized > 0:
                if cumulative_funding > unrealized * funding_threshold:
                    return True

            # Exit if stuck for 72+ hours with no profit
            if age_hours > 72 and unrealized <= 0:
                return True

            return False
        except Exception:
            return False

    # ─── TRAILING TP (Final Leg) ───

    def update_trailing_tp(self, pos: dict, current_price: float) -> float:
        """
        Trail TP 1.5% behind price for the final position leg (after TP2 hit).
        Fallback for non-adaptive mode.
        """
        current_tp = float(pos.get('take_profit', 0))
        direction = pos.get('direction', 'LONG')
        entry = float(pos.get('entry_fill_price') or pos.get('entry_price', 0))

        if entry <= 0:
            return current_tp

        if direction == 'LONG':
            profit_pct = (current_price - entry) / entry if entry > 0 else 0
            if profit_pct > 0.02:  # >2% profit on final leg
                new_tp = current_price * 0.985
                return max(new_tp, current_tp)
        else:
            profit_pct = (entry - current_price) / entry if entry > 0 else 0
            if profit_pct > 0.02:
                new_tp = current_price * 1.015
                return min(new_tp, current_tp)

        return current_tp

    # ─── CLASSIC TRAILING STOP (Fast, fallback) ───

    def update_trailing_stop(self, pos: dict, current_price: float) -> float:
        """
        Fast ATR-based trailing stop (used when df not available).
        Fallback for real-time monitoring.
        """
        entry = float(pos.get('entry_fill_price') or pos.get('entry_price', 0))
        current_sl = float(pos.get('stop_loss', 0))
        direction = pos.get('direction', 'LONG')

        if entry <= 0:
            return current_sl

        if direction == 'LONG':
            profit_pct = (current_price - entry) / entry if entry > 0 else 0
            if profit_pct < TRAILING_STOP_ACTIVATION:
                return current_sl
            new_sl = current_price * (1 - TRAILING_STOP_DISTANCE)
            return max(new_sl, current_sl)
        else:
            profit_pct = (entry - current_price) / entry if entry > 0 else 0
            if profit_pct < TRAILING_STOP_ACTIVATION:
                return current_sl
            new_sl = current_price * (1 + TRAILING_STOP_DISTANCE)
            return min(new_sl, current_sl)
