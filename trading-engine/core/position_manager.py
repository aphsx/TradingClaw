"""
Position Manager — Scaled entry, partial exits, Chandelier trailing stop
=========================================================================
Handles multi-leg entry and partial TP management in the monitor thread.
"""
from __future__ import annotations

import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (
    PARTIAL_TP_FRACTIONS, PARTIAL_TP1_R, PARTIAL_TP2_R,
    TRAILING_STOP_ACTIVATION, TRAILING_STOP_DISTANCE,
    CHANDELIER_PERIOD, CHANDELIER_MULT,
    MAX_FUNDING_RATE,
    TRADE_HEALTH_MIN_HOURS, TRADE_HEALTH_R_THRESHOLD, TRADE_HEALTH_SL_TIGHTEN_PCT,
)
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from typing import Optional


class PositionManager:
    """
    Manages open position lifecycle:
    - Partial profit-taking at TP1 (1R) and TP2 (2R)
    - Trailing stop via Chandelier Exit
    - Trailing TP on the final leg
    - Time/funding-based exit
    """

    # ─── Partial TP checks ───
    def check_partial_tp(self, pos: dict, current_price: float) -> Optional[dict]:
        """
        Returns a dict with action info if a partial TP should be triggered.
        {'action': 'partial_close', 'fraction': 0.33, 'reason': 'TP1', 'price': ...}
        """
        entry = float(pos.get('entry_fill_price') or pos.get('entry_price', 0))
        if entry <= 0:
            return None

        direction = pos.get('direction', 'LONG')
        tp1 = float(pos.get('take_profit', 0))       # 1R TP from signal
        tp2 = float(pos.get('take_profit_2', 0))     # 2R TP

        tp1_hit = pos.get('tp1_hit', False)
        tp2_hit = pos.get('tp2_hit', False)

        if direction == 'LONG':
            if not tp1_hit and tp1 > 0 and current_price >= tp1:
                return {'action': 'partial_close', 'fraction': PARTIAL_TP_FRACTIONS[0],
                        'reason': 'TP1', 'price': current_price, 'tp_level': 1}
            if tp1_hit and not tp2_hit and tp2 > 0 and current_price >= tp2:
                return {'action': 'partial_close', 'fraction': PARTIAL_TP_FRACTIONS[1],
                        'reason': 'TP2', 'price': current_price, 'tp_level': 2}
        else:  # SHORT
            if not tp1_hit and tp1 > 0 and current_price <= tp1:
                return {'action': 'partial_close', 'fraction': PARTIAL_TP_FRACTIONS[0],
                        'reason': 'TP1', 'price': current_price, 'tp_level': 1}
            if tp1_hit and not tp2_hit and tp2 > 0 and current_price <= tp2:
                return {'action': 'partial_close', 'fraction': PARTIAL_TP_FRACTIONS[1],
                        'reason': 'TP2', 'price': current_price, 'tp_level': 2}

        return None

    # ─── Chandelier Trailing Stop ───
    def update_chandelier_stop(self, pos: dict, df: pd.DataFrame) -> float:
        """
        Chandelier Exit trailing stop.
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

        if direction == 'LONG':
            hh = float(df['high'].iloc[-CHANDELIER_PERIOD:].max())
            chandelier = hh - atr * CHANDELIER_MULT
            # Only activate after trade is 0.3% profitable
            current_price = float(df['close'].iloc[-1])
            if (current_price - entry) / entry < TRAILING_STOP_ACTIVATION:
                return current_sl
            return max(chandelier, current_sl)  # Only move up
        else:
            ll = float(df['low'].iloc[-CHANDELIER_PERIOD:].min())
            chandelier = ll + atr * CHANDELIER_MULT
            current_price = float(df['close'].iloc[-1])
            if (entry - current_price) / entry < TRAILING_STOP_ACTIVATION:
                return current_sl
            return min(chandelier, current_sl)  # Only move down

    # ─── Breakeven stop ───
    def move_to_breakeven(self, pos: dict) -> float:
        """Move SL to breakeven (entry price) after TP1 hit."""
        entry = float(pos.get('entry_fill_price') or pos.get('entry_price', 0))
        current_sl = float(pos.get('stop_loss', 0))
        direction = pos.get('direction', 'LONG')

        if direction == 'LONG':
            return max(current_sl, entry * 1.001)  # BE + tiny buffer
        else:
            return min(current_sl, entry * 0.999)

    # ─── Trailing TP (final leg) ───
    def update_trailing_tp(self, pos: dict, current_price: float) -> float:
        """Trail TP 1.5% behind price for the final position leg (after TP2 hit)."""
        current_tp = float(pos.get('take_profit', 0))
        direction = pos.get('direction', 'LONG')
        entry = float(pos.get('entry_fill_price') or pos.get('entry_price', 0))

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

    # ─── Classic trailing stop (fast) ───
    def update_trailing_stop(self, pos: dict, current_price: float) -> float:
        """Fast ATR-based trailing stop (used when df not available)."""
        entry = float(pos.get('entry_fill_price') or pos.get('entry_price', 0))
        current_sl = float(pos.get('stop_loss', 0))
        direction = pos.get('direction', 'LONG')

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

    # ─── Trade Health Monitoring ───
    def check_trade_health(self, pos: dict, current_price: float) -> Optional[dict]:
        """
        After TRADE_HEALTH_MIN_HOURS hours, check if the trade has moved adversely.
        If position is at TRADE_HEALTH_R_THRESHOLD (e.g. -0.35R) or worse,
        tighten the stop loss toward the entry to cut max loss.

        Only fires once (won't re-tighten), and never fires after TP1 is hit.
        """
        # Don't interfere once trade is partially profitable
        if pos.get('tp1_hit'):
            return None
        # Don't re-tighten if already health-tightened
        if pos.get('health_sl_tightened'):
            return None

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
            age_hours = (datetime.now(timezone.utc) - entry_time).total_seconds() / 3600
        except Exception:
            return None

        if age_hours < TRADE_HEALTH_MIN_HOURS:
            return None

        entry = float(pos.get('entry_fill_price') or pos.get('entry_price', 0))
        sl    = float(pos.get('stop_loss', 0))
        direction = pos.get('direction', 'LONG')

        if entry <= 0 or sl <= 0:
            return None

        risk = abs(entry - sl)
        if risk <= 0:
            return None

        # Current R-multiple
        if direction == 'LONG':
            current_r = (current_price - entry) / risk
        else:
            current_r = (entry - current_price) / risk

        if current_r >= TRADE_HEALTH_R_THRESHOLD:
            return None  # Trade is within acceptable range, no action needed

        # Tighten SL: move it TRADE_HEALTH_SL_TIGHTEN_PCT of the way toward entry
        if direction == 'LONG':
            new_sl = sl + (entry - sl) * TRADE_HEALTH_SL_TIGHTEN_PCT
            new_sl = max(new_sl, sl)   # Can only tighten (move up)
        else:
            new_sl = sl - (sl - entry) * TRADE_HEALTH_SL_TIGHTEN_PCT
            new_sl = min(new_sl, sl)   # Can only tighten (move down)

        return {
            'action':     'tighten_sl',
            'new_sl':     new_sl,
            'current_r':  round(current_r, 3),
            'age_hours':  round(age_hours, 1),
            'reason':     (f'Trade health: {current_r:+.2f}R after {age_hours:.1f}h '
                           f'→ SL tightened {sl:.2f} → {new_sl:.2f}'),
        }

    # ─── Time / funding exit ───
    def should_time_exit(self, pos: dict) -> bool:
        """Exit if funding costs exceed unrealized PnL or position is stuck."""
        entry_time_str = pos.get('entry_time')
        if not entry_time_str:
            return False
        try:
            if isinstance(entry_time_str, str):
                entry_time = datetime.fromisoformat(entry_time_str.replace('Z', '+00:00'))
            else:
                entry_time = entry_time_str
            if entry_time.tzinfo is None:
                entry_time = entry_time.replace(tzinfo=timezone.utc)

            age_hours = (datetime.now(timezone.utc) - entry_time).total_seconds() / 3600
            unrealized = float(pos.get('unrealized_pnl', 0))
            entry_val = (float(pos.get('quantity', 0)) *
                         float(pos.get('entry_fill_price') or pos.get('entry_price', 0)))
            est_funding = entry_val * MAX_FUNDING_RATE
            cum_funding = est_funding * (age_hours / 8)

            if age_hours > 4 and unrealized < -(cum_funding * 2):
                return True
            if age_hours > 72 and unrealized <= 0:
                return True
            return False
        except Exception:
            return False
