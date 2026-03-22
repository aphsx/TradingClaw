"""
Execution Analytics — Issue #10
=================================
Tracks expected fill price vs actual fill price per order to measure
execution quality (slippage). Adapts the effective SLIPPAGE constant
used in position sizing / Sharpe calculation based on observed data.

Usage:
    analytics = ExecutionAnalytics()
    analytics.record(symbol, expected_price, actual_fill, side, quantity)
    slippage = analytics.get_effective_slippage(symbol)
"""
import math
from collections import deque
from datetime import datetime, timezone
from typing import Optional


class ExecutionAnalytics:
    """
    Tracks execution quality and provides a dynamic slippage estimate.

    For each executed order we record:
      - expected_price: signal entry_price (before order placement)
      - actual_fill:    fill_price from Binance order response
      - side:           BUY or SELL
      - symbol:         trading pair
      - quantity:       order size (for size-weighted statistics)

    Slippage is computed as:
      slippage_pct = |actual_fill - expected| / expected
      (sign: adverse fill → positive slippage cost)

    The module maintains a rolling window per symbol and provides:
      - get_effective_slippage(symbol): EMA-smoothed slippage (last 50 fills)
      - get_report(): summary dict for dashboard/logging
    """

    _DEFAULT_SLIPPAGE = 0.0005   # 0.05% — matches SLIPPAGE config default

    def __init__(self, window: int = 50):
        self._window = window
        # symbol → deque of {'slippage_pct', 'side', 'quantity', 'timestamp'}
        self._records: dict = {}
        # Dynamic slippage estimate per symbol (EMA-smoothed)
        self._ema_slippage: dict = {}
        self._ema_alpha = 0.1   # ~10-fill half-life

    def record(self, symbol: str, expected_price: float, actual_fill: float,
               side: str, quantity: float):
        """
        Record a single execution.
        Call this immediately after parsing the Binance order response.
        """
        if expected_price <= 0 or actual_fill <= 0:
            return

        # Compute adverse slippage (always positive = always a cost)
        raw_slip = (actual_fill - expected_price) / expected_price
        if side == "BUY":
            slippage_pct = raw_slip   # positive = paid more than expected (bad)
        else:
            slippage_pct = -raw_slip  # positive = received less than expected (bad)

        entry = {
            "slippage_pct": slippage_pct,
            "side":         side,
            "quantity":     quantity,
            "expected":     expected_price,
            "actual":       actual_fill,
            "timestamp":    datetime.now(timezone.utc).isoformat(),
        }

        if symbol not in self._records:
            self._records[symbol] = deque(maxlen=self._window)

        self._records[symbol].append(entry)

        # Update EMA slippage estimate
        abs_slip = abs(slippage_pct)
        if symbol not in self._ema_slippage:
            self._ema_slippage[symbol] = abs_slip
        else:
            self._ema_slippage[symbol] = (
                self._ema_alpha * abs_slip +
                (1 - self._ema_alpha) * self._ema_slippage[symbol]
            )

    def get_effective_slippage(self, symbol: str = None) -> float:
        """
        Return the current dynamic slippage estimate for position sizing.
        Falls back to DEFAULT_SLIPPAGE if not enough data.
        Uses the EMA estimate so recent fills have higher influence.
        """
        if symbol and symbol in self._ema_slippage:
            ema = self._ema_slippage[symbol]
            # Clamp: never lower than 0.02% (market microstructure floor)
            #        never higher than 0.5% (reject bad API conditions)
            return float(max(0.0002, min(0.005, ema)))

        # Aggregate across all symbols if no specific symbol
        if self._ema_slippage:
            avg = sum(self._ema_slippage.values()) / len(self._ema_slippage)
            return float(max(0.0002, min(0.005, avg)))

        return self._DEFAULT_SLIPPAGE

    def get_report(self, symbol: str = None) -> dict:
        """Return execution quality summary for dashboard/logging."""
        symbols = [symbol] if symbol else list(self._records.keys())
        report = {}

        for sym in symbols:
            recs = self._records.get(sym)
            if not recs:
                continue

            slippages = [r['slippage_pct'] for r in recs]
            abs_slips = [abs(s) for s in slippages]
            pos_slips  = [s for s in slippages if s > 0]   # adverse
            neg_slips  = [s for s in slippages if s <= 0]  # favorable

            report[sym] = {
                "fills":             len(recs),
                "avg_slippage_pct":  round(sum(abs_slips) / len(abs_slips) * 100, 4),
                "ema_slippage_pct":  round(self._ema_slippage.get(sym, self._DEFAULT_SLIPPAGE) * 100, 4),
                "adverse_rate":      round(len(pos_slips) / len(recs) * 100, 1),
                "max_slip_pct":      round(max(abs_slips) * 100, 4),
                "recent_fills":      [
                    {"expected": r["expected"], "actual": r["actual"],
                     "slip_pct": round(r["slippage_pct"] * 100, 4), "side": r["side"]}
                    for r in list(recs)[-5:]
                ],
            }

        return report
