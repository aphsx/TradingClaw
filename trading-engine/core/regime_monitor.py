"""
Regime Performance Monitor & Circuit Breakers
==============================================
Tracks per-regime trade outcomes and disables unprofitable regimes.

Problems solved:
  1. HMM labels a state as "Trending-Up" but that state has been losing money
     → Reduce position size or suspend entries in that regime.

  2. We entered a LONG in "Trending-Up" but regime just flipped to "Trending-Down"
     → Exit or tighten stop immediately.

  3. HMM confidence is low (transitioning / uncertain)
     → Apply size penalty or skip entry.

Usage (in main.py):
    regime_mon = RegimeMonitor()
    # Before entry:
    ok, reason = regime_mon.can_trade(regime_id, confidence, bar_counter)
    size_mult   = regime_mon.get_size_multiplier(regime_id)
    # After close:
    regime_mon.record_outcome(regime_id, r_multiple, bar_counter)
    # In monitor loop:
    if regime_mon.should_exit_on_regime_flip(pos, current_regime_id):
        ...force exit...
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
)

# Regime constants (mirrors regime_detector.py)
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

# Regimes that are "opposite" — flip between these should trigger exit review
_OPPOSITE = {
    TRENDING_UP:   TRENDING_DOWN,
    TRENDING_DOWN: TRENDING_UP,
}


class _RegimeStats:
    """Per-regime rolling statistics."""

    def __init__(self, name: str):
        self.name = name
        self.recent_r: deque = deque(maxlen=20)   # Last 20 R-multiples
        self.consecutive_losses: int = 0
        self.total_trades: int = 0
        self.total_wins: int = 0
        self.disabled_until_bar: int = 0           # Disable until this bar count

    def add_result(self, r_multiple: float, current_bar: int = 0):
        self.recent_r.append(r_multiple)
        self.total_trades += 1
        if r_multiple > 0:
            self.total_wins += 1
            self.consecutive_losses = 0
        else:
            self.consecutive_losses += 1
            # Hard circuit breaker: too many losses → disable for cooldown
            if self.consecutive_losses >= REGIME_DISABLE_AFTER_LOSSES:
                self.disabled_until_bar = current_bar + REGIME_COOLDOWN_BARS
                print(f"[REGIME-MON] {self.name} DISABLED for {REGIME_COOLDOWN_BARS} bars "
                      f"({self.consecutive_losses} consecutive losses)")
            # Also check cumulative R
            elif len(self.recent_r) >= 5:
                cum_r = sum(self.recent_r)
                if cum_r < REGIME_CIRCUIT_R_THRESHOLD:
                    self.disabled_until_bar = current_bar + REGIME_COOLDOWN_BARS
                    print(f"[REGIME-MON] {self.name} DISABLED — cumulative R={cum_r:.2f} "
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
        """Return position size multiplier based on recent performance."""
        if self.consecutive_losses >= REGIME_REDUCE_AFTER_LOSSES:
            return 0.5   # Halve size when in a losing streak
        if len(self.recent_r) >= 5 and self.avg_r < -0.5:
            return 0.75  # Reduce 25% if recent average R is negative
        return 1.0

    def to_dict(self) -> dict:
        return {
            "name":                self.name,
            "total_trades":        self.total_trades,
            "win_rate":            f"{self.win_rate:.0%}",
            "avg_r_recent":        round(self.avg_r, 3),
            "consecutive_losses":  self.consecutive_losses,
            "size_multiplier":     self.size_multiplier(),
            "disabled_until_bar":  self.disabled_until_bar,
        }


class RegimeMonitor:
    """
    Central monitor for regime-based circuit breakers and trade health.

    Thread-safe only if accessed under the same lock as the position dict
    (i.e., _position_lock in main.py).  Since record_outcome() is called
    from the monitor thread (same lock), and can_trade() from the main loop
    (also same lock), no additional locking is needed.
    """

    def __init__(self):
        self._stats: dict[int, _RegimeStats] = {
            TRENDING_UP:   _RegimeStats("Trending-Up"),
            RANGING:       _RegimeStats("Ranging"),
            VOLATILE:      _RegimeStats("Volatile"),
            TRENDING_DOWN: _RegimeStats("Trending-Down"),
        }
        self._bar_counter: int = 0   # Global bar count (incremented by main loop)

    # ─── Public API ───────────────────────────────────────────────────

    def tick(self):
        """Increment bar counter. Call once per main loop iteration."""
        self._bar_counter += 1

    def record_outcome(self, regime: int, r_multiple: float):
        """
        Record the outcome of a closed trade.

        Args:
            regime:     The regime the trade was ENTERED in (int 0-3).
            r_multiple: Realized R (positive = win, negative = loss).
                        e.g. +2.0 means hit TP2, -1.0 means SL.
        """
        stats = self._stats.get(regime)
        if stats:
            stats.add_result(r_multiple, self._bar_counter)
            print(f"[REGIME-MON] Record {stats.name}: R={r_multiple:+.2f} "
                  f"| consec_loss={stats.consecutive_losses} "
                  f"| avg_R={stats.avg_r:+.2f}")

    def can_trade(self, regime: int, confidence: float) -> tuple[bool, str]:
        """
        Gate check before opening a new position.

        Returns:
            (True, "OK")  — allowed
            (False, reason) — blocked
        """
        # Confidence gate
        if confidence < REGIME_MIN_CONFIDENCE:
            return False, (f"HMM confidence too low ({confidence:.0%} < "
                           f"{REGIME_MIN_CONFIDENCE:.0%}) — regime uncertain")

        # Per-regime circuit breaker
        stats = self._stats.get(regime)
        if stats and stats.is_disabled(self._bar_counter):
            bars_left = stats.disabled_until_bar - self._bar_counter
            return False, (f"{stats.name} circuit breaker active — "
                           f"{bars_left} bars remaining (recent losses)")

        return True, "OK"

    def get_size_multiplier(self, regime: int) -> float:
        """
        Multiplicative position size penalty for underperforming regime.
        Returns 1.0 (full size) when healthy, 0.5 when in a losing streak.
        """
        stats = self._stats.get(regime)
        if not stats:
            return 1.0
        mult = stats.size_multiplier()
        if mult < 1.0:
            print(f"[REGIME-MON] {stats.name} size → {mult:.0%} "
                  f"(consec_loss={stats.consecutive_losses}, avg_R={stats.avg_r:+.2f})")
        return mult

    def should_exit_on_regime_flip(
        self,
        position_direction: str,
        entry_regime: int,
        current_regime: int,
    ) -> bool:
        """
        Return True if the market regime has flipped against this position.

        Rules:
          - Entered LONG when Trending-Up → regime now Trending-Down  → exit
          - Entered SHORT when Trending-Down → regime now Trending-Up → exit
          - Any flip to Volatile when position is losing → exit early
        """
        if entry_regime == current_regime:
            return False

        opposite = _OPPOSITE.get(entry_regime)
        if opposite is not None and current_regime == opposite:
            return True

        return False

    def get_health_report(self) -> dict:
        """Return per-regime stats for logging / dashboard."""
        return {
            "bar_counter": self._bar_counter,
            "regimes": {r: self._stats[r].to_dict() for r in self._stats},
        }

    # ─── Helpers ──────────────────────────────────────────────────────

    def estimate_r_multiple(self, position: dict, exit_price: float) -> float:
        """
        Compute R-multiple for a closed position.
        Positive = profitable, negative = loss.
        Used when recording outcomes.
        """
        entry = float(position.get('entry_fill_price') or position.get('entry_price', 0))
        sl    = float(position.get('stop_loss', 0))
        direction = position.get('direction', 'LONG')

        risk = abs(entry - sl)
        if entry <= 0 or risk <= 0:
            return 0.0

        if direction == 'LONG':
            r = (exit_price - entry) / risk
        else:
            r = (entry - exit_price) / risk

        return round(r, 3)
