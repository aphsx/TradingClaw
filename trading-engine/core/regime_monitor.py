"""
Regime Monitor + Trade Health Monitor v2
=========================================
Two concerns in one module:

A) REGIME MONITOR — Per-regime circuit breakers
   Tracks trade outcomes per regime.
   Disables a regime after too many consecutive losses.
   Reduces size when a regime is underperforming.

B) TRADE HEALTH MONITOR — Per-trade monitoring
   Monitors open positions every N bars.
   Actions when a trade goes against us:
     1. After TRADE_HEALTH_MIN_HOURS: if unrealized < -0.35R → tighten SL
     2. Regime flip (Trending-Up → Trending-Down): exit signal
     3. Time stop: if trade age > MAX_POSITION_AGE_HOURS and still losing → exit

This is what the user asked for:
  "ระบบมีการ monitor หรือยัง เช่นมันไปผิดทางกับที่คาดการณ์ เราก็ต้องตัดทิ้ง"
  Translation: "Does the system monitor? If it goes wrong vs expectation, cut it."
"""
from __future__ import annotations

import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collections import deque
from typing import Optional
from config import (
    REGIME_MIN_CONFIDENCE,
    REGIME_REDUCE_AFTER_LOSSES,
    REGIME_DISABLE_AFTER_LOSSES,
    REGIME_COOLDOWN_BARS,
    REGIME_CIRCUIT_R_THRESHOLD,
    TRADE_HEALTH_MIN_HOURS,
    TRADE_HEALTH_R_THRESHOLD,
    TRADE_HEALTH_SL_TIGHTEN_PCT,
    MAX_POSITION_AGE_HOURS,
)

TRENDING_UP   = 0
RANGING       = 1
VOLATILE      = 2
TRENDING_DOWN = 3

REGIME_NAMES = {
    TRENDING_UP:   "Trending-Up",
    RANGING:       "Ranging",
    VOLATILE:      "Volatile",
    TRENDING_DOWN: "Trending-Down",
}

_OPPOSITE = {
    TRENDING_UP:   TRENDING_DOWN,
    TRENDING_DOWN: TRENDING_UP,
}


# ══════════════════════════════════════════════════════════════
#  A. REGIME STATS
# ══════════════════════════════════════════════════════════════

class _RegimeStats:
    """Per-regime rolling statistics and circuit breaker state."""

    def __init__(self, name: str):
        self.name               = name
        self.recent_r: deque    = deque(maxlen=20)
        self.consecutive_losses = 0
        self.total_trades       = 0
        self.total_wins         = 0
        self.disabled_until_bar = 0

    def add_result(self, r_multiple: float, current_bar: int = 0):
        self.recent_r.append(r_multiple)
        self.total_trades += 1
        if r_multiple > 0:
            self.total_wins += 1
            self.consecutive_losses = 0
        else:
            self.consecutive_losses += 1
            if self.consecutive_losses >= REGIME_DISABLE_AFTER_LOSSES:
                self.disabled_until_bar = current_bar + REGIME_COOLDOWN_BARS
                print(f"[REGIME-MON] ⛔ {self.name} DISABLED for {REGIME_COOLDOWN_BARS} bars "
                      f"({self.consecutive_losses} consecutive losses)")
            elif len(self.recent_r) >= 5:
                cum_r = sum(self.recent_r)
                if cum_r < REGIME_CIRCUIT_R_THRESHOLD:
                    self.disabled_until_bar = current_bar + REGIME_COOLDOWN_BARS
                    print(f"[REGIME-MON] ⛔ {self.name} DISABLED — cumulative R={cum_r:.2f} "
                          f"< threshold {REGIME_CIRCUIT_R_THRESHOLD}")

    @property
    def win_rate(self) -> float:
        return self.total_wins / max(self.total_trades, 1)

    @property
    def avg_r(self) -> float:
        return float(sum(self.recent_r) / max(len(self.recent_r), 1))

    def is_disabled(self, current_bar: int) -> bool:
        return current_bar < self.disabled_until_bar

    def size_multiplier(self) -> float:
        if self.consecutive_losses >= REGIME_REDUCE_AFTER_LOSSES:
            return 0.5
        if len(self.recent_r) >= 5 and self.avg_r < -0.5:
            return 0.75
        return 1.0

    def to_dict(self) -> dict:
        return {
            "name":               self.name,
            "total_trades":       self.total_trades,
            "win_rate":           f"{self.win_rate:.0%}",
            "avg_r_recent":       round(self.avg_r, 3),
            "consecutive_losses": self.consecutive_losses,
            "size_multiplier":    self.size_multiplier(),
            "disabled_until_bar": self.disabled_until_bar,
        }


# ══════════════════════════════════════════════════════════════
#  B. TRADE HEALTH ACTIONS
# ══════════════════════════════════════════════════════════════

class TradeHealthAction:
    """Result of a trade health check."""
    def __init__(self, action: str, reason: str, new_sl: float = None):
        self.action  = action   # "hold", "tighten_sl", "exit"
        self.reason  = reason
        self.new_sl  = new_sl   # Only set when action == "tighten_sl"

    def __repr__(self):
        return f"TradeHealthAction({self.action}, {self.reason}, new_sl={self.new_sl})"


# ══════════════════════════════════════════════════════════════
#  C. REGIME MONITOR (main class)
# ══════════════════════════════════════════════════════════════

class RegimeMonitor:
    """
    Central monitor for regime circuit breakers + trade health.

    Usage pattern in main.py / backtest:
        monitor = RegimeMonitor()
        monitor.tick()                        # once per bar
        ok, reason = monitor.can_trade(regime, confidence)
        mult = monitor.get_size_multiplier(regime)
        ...after close...
        monitor.record_outcome(regime, r_multiple)

        ...during open position...
        action = monitor.check_trade_health(position, current_price, current_regime)
        if action.action == "exit":
            force_close(position)
        elif action.action == "tighten_sl":
            position.stop_loss = action.new_sl
    """

    def __init__(self):
        self._stats: dict[int, _RegimeStats] = {
            TRENDING_UP:   _RegimeStats("Trending-Up"),
            RANGING:       _RegimeStats("Ranging"),
            VOLATILE:      _RegimeStats("Volatile"),
            TRENDING_DOWN: _RegimeStats("Trending-Down"),
        }
        self._bar_counter: int = 0

    # ── Bar tick ──────────────────────────────────────────────

    def tick(self):
        """Call once per bar (main loop iteration)."""
        self._bar_counter += 1

    # ── Entry gates ───────────────────────────────────────────

    def can_trade(self, regime: int, confidence: float) -> tuple[bool, str]:
        """
        Gate check before opening a new position.
        Returns (allowed: bool, reason: str).
        """
        if confidence < REGIME_MIN_CONFIDENCE:
            return False, (f"Regime confidence too low ({confidence:.0%} < "
                           f"{REGIME_MIN_CONFIDENCE:.0%})")

        stats = self._stats.get(regime)
        if stats and stats.is_disabled(self._bar_counter):
            bars_left = stats.disabled_until_bar - self._bar_counter
            return False, (f"{stats.name} circuit breaker — "
                           f"{bars_left} bars remaining")
        return True, "OK"

    def get_size_multiplier(self, regime: int) -> float:
        """Size penalty for underperforming regime. 1.0 = full, 0.5 = half."""
        stats = self._stats.get(regime)
        if not stats:
            return 1.0
        mult = stats.size_multiplier()
        if mult < 1.0:
            print(f"[REGIME-MON] ⚠️  {stats.name} size → {mult:.0%} "
                  f"(consec_loss={stats.consecutive_losses}, avg_R={stats.avg_r:+.2f})")
        return mult

    # ── Outcome recording ─────────────────────────────────────

    def record_outcome(self, regime: int, r_multiple: float):
        """
        Record a closed trade's outcome.
        Call after each position close.
        """
        stats = self._stats.get(regime)
        if stats:
            stats.add_result(r_multiple, self._bar_counter)
            print(f"[REGIME-MON] Record {stats.name}: R={r_multiple:+.2f} "
                  f"| consec_loss={stats.consecutive_losses} "
                  f"| avg_R={stats.avg_r:+.2f}")

    # ── Trade health monitoring ───────────────────────────────

    def check_trade_health(
        self,
        position: dict,
        current_price: float,
        current_regime: int,
        age_hours: float = 0.0,
    ) -> TradeHealthAction:
        """
        Monitor an open position and decide what to do.

        Called every bar for each open position.

        Returns TradeHealthAction with one of:
          "hold"        — no action needed
          "tighten_sl"  — move SL closer (new_sl provided)
          "exit"        — exit this position now

        Decision tree:
          1. REGIME FLIP: entered Trending-Up but now Trending-Down (or vice versa)
             → EXIT immediately (market went against original thesis)
          2. STALE + LOSING: position age > MAX_POSITION_AGE_HOURS with no profit
             → EXIT (capital tied up, opportunity cost)
          3. EARLY WARNING: age > TRADE_HEALTH_MIN_HOURS AND unrealized < -0.35R
             → TIGHTEN SL to reduce max loss
          4. Otherwise: HOLD
        """
        entry      = float(position.get('entry_fill_price') or position.get('entry_price', 0))
        sl         = float(position.get('stop_loss', 0))
        direction  = position.get('direction', 'LONG')
        entry_regime = position.get('regime', -1)

        if entry <= 0 or sl <= 0:
            return TradeHealthAction("hold", "Insufficient position data")

        risk = abs(entry - sl)
        if risk <= 0:
            return TradeHealthAction("hold", "Zero risk — cannot compute R")

        # Unrealized PnL in R-multiples
        if direction == "LONG":
            unrealized_r = (current_price - entry) / risk
        else:
            unrealized_r = (entry - current_price) / risk

        # ── Check 1: Regime flip ──
        if self._is_regime_flip(direction, entry_regime, current_regime):
            return TradeHealthAction(
                "exit",
                f"Regime flipped: entered {REGIME_NAMES.get(entry_regime, '?')} "
                f"→ now {REGIME_NAMES.get(current_regime, '?')}"
            )

        # ── Check 2: Stale + losing (time stop) ──
        if age_hours >= MAX_POSITION_AGE_HOURS and unrealized_r <= 0:
            return TradeHealthAction(
                "exit",
                f"Stale trade: {age_hours:.1f}h old, still at {unrealized_r:+.2f}R"
            )

        # ── Check 3: Early warning — tighten SL ──
        if age_hours >= TRADE_HEALTH_MIN_HOURS and unrealized_r < TRADE_HEALTH_R_THRESHOLD:
            new_sl = self._tighten_sl(entry, sl, direction, TRADE_HEALTH_SL_TIGHTEN_PCT)
            return TradeHealthAction(
                "tighten_sl",
                f"Early warning: {age_hours:.1f}h at {unrealized_r:+.2f}R — tightening SL",
                new_sl=new_sl,
            )

        return TradeHealthAction("hold", "Position healthy")

    # ── Helpers ───────────────────────────────────────────────

    def _is_regime_flip(self, direction: str, entry_regime: int,
                         current_regime: int) -> bool:
        """Return True if regime has flipped against the position."""
        if entry_regime == current_regime:
            return False
        if entry_regime in (TRENDING_UP, TRENDING_DOWN):
            opposite = _OPPOSITE.get(entry_regime)
            if opposite is not None and current_regime == opposite:
                return True
        return False

    def _tighten_sl(self, entry: float, current_sl: float,
                     direction: str, fraction: float) -> float:
        """Move SL fraction of the way from current SL toward entry."""
        new_sl = current_sl + (entry - current_sl) * fraction
        if direction == "LONG":
            # SL moves up (closer to entry)
            return max(current_sl, min(new_sl, entry * 0.999))
        else:
            # SL moves down (closer to entry)
            return min(current_sl, max(new_sl, entry * 1.001))

    def estimate_r_multiple(self, position: dict, exit_price: float) -> float:
        """Compute R-multiple for a closed position."""
        entry     = float(position.get('entry_fill_price') or position.get('entry_price', 0))
        sl        = float(position.get('stop_loss', 0))
        direction = position.get('direction', 'LONG')
        risk      = abs(entry - sl)
        if entry <= 0 or risk <= 0:
            return 0.0
        if direction == 'LONG':
            return round((exit_price - entry) / risk, 3)
        return round((entry - exit_price) / risk, 3)

    def should_exit_on_regime_flip(
        self,
        position_direction: str,
        entry_regime: int,
        current_regime: int,
    ) -> bool:
        """Backward-compatible wrapper for regime flip check."""
        return self._is_regime_flip(position_direction, entry_regime, current_regime)

    def get_health_report(self) -> dict:
        """Return per-regime stats for logging / dashboard."""
        return {
            "bar_counter": self._bar_counter,
            "regimes":     {r: self._stats[r].to_dict() for r in self._stats},
        }
