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

    # ── Feedback Loop Methods (NEW) ─────────────────────────────────────────

    def get_sizing_penalty(self, symbol: str = None) -> float:
        """
        Return a 0.0–1.0 multiplier to scale down position size when
        execution quality is poor.

        1.0 = no penalty (normal sizing)
        0.5 = half size (slippage consistently high)
        0.0 = no trading (extreme slippage)

        Thresholds (all in % of notional):
          < 0.05% slippage → no penalty
          0.05–0.10%       → linear penalty down to 0.7
          0.10–0.20%       → penalty 0.7 → 0.5
          > 0.20%          → penalty 0.5 → 0.25 (exchange issues likely)
        """
        eff_slip = self.get_effective_slippage(symbol)  # as fraction, e.g. 0.0005

        if eff_slip < 0.0005:
            return 1.0
        elif eff_slip < 0.0010:
            # Linear 1.0 → 0.70
            t = (eff_slip - 0.0005) / (0.0010 - 0.0005)
            return round(1.0 - t * 0.30, 3)
        elif eff_slip < 0.0020:
            # Linear 0.70 → 0.50
            t = (eff_slip - 0.0010) / (0.0020 - 0.0010)
            return round(0.70 - t * 0.20, 3)
        else:
            # Linear 0.50 → 0.25 for extreme slippage
            t = min((eff_slip - 0.0020) / 0.0030, 1.0)
            return round(0.50 - t * 0.25, 3)

    def get_adjusted_fee_multiplier(self, base_multiplier: float = 3.0,
                                    symbol: str = None) -> float:
        """
        Adjust FeeFilter multiplier dynamically based on observed slippage.
        Higher slippage → higher fee multiplier → fewer but better trades.

        E.g.:
          Normal slippage (0.03%) → 3.0x (base)
          High slippage   (0.10%) → 3.5x (filter more aggressively)
          Extreme         (0.20%) → 4.0x
        """
        eff_slip = self.get_effective_slippage(symbol)

        if eff_slip < 0.0005:
            return base_multiplier
        elif eff_slip < 0.0010:
            extra = (eff_slip - 0.0005) / 0.0005 * 0.5
            return round(base_multiplier + extra, 2)
        elif eff_slip < 0.0020:
            extra = 0.5 + (eff_slip - 0.0010) / 0.0010 * 0.5
            return round(base_multiplier + extra, 2)
        else:
            return round(base_multiplier + 1.0, 2)  # cap at +1.0x

    def should_pause_trading(self, symbol: str = None,
                              adverse_rate_threshold: float = 0.80,
                              min_fills: int = 10) -> tuple:
        """
        Circuit breaker: should we pause live trading due to bad execution?

        Returns: (should_pause: bool, reason: str)

        Triggers:
        - Adverse fill rate > 80% (last 10 fills mostly bad)
        - EMA slippage > 0.30% (extreme market conditions)
        """
        syms = [symbol] if symbol else list(self._records.keys())
        for sym in syms:
            recs = self._records.get(sym)
            if not recs or len(recs) < min_fills:
                continue

            slippages = [r['slippage_pct'] for r in list(recs)[-min_fills:]]
            adverse_rate = sum(1 for s in slippages if s > 0.001) / len(slippages)

            if adverse_rate >= adverse_rate_threshold:
                return True, (f"{sym}: {adverse_rate*100:.0f}% adverse fills "
                              f"in last {min_fills} trades — execution degraded")

            eff_slip = self._ema_slippage.get(sym, 0)
            if eff_slip > 0.0030:
                return True, (f"{sym}: EMA slippage {eff_slip*100:.3f}% "
                              f"— extreme market microstructure")

        return False, "OK"

    def get_fill_quality_score(self, symbol: str = None) -> float:
        """
        0.0 = terrible execution, 1.0 = perfect execution.
        Used as a feature for ML filter.
        """
        penalty = self.get_sizing_penalty(symbol)
        # Penalty of 1.0 → quality 1.0, penalty of 0.25 → quality 0.25
        return round(penalty, 3)

    def get_dashboard_metrics(self) -> dict:
        """Richer metrics for dashboard — includes all symbols + quality summary."""
        report = self.get_report()
        overall_quality = 1.0
        if self._ema_slippage:
            avg_slip = sum(self._ema_slippage.values()) / len(self._ema_slippage)
            overall_quality = self.get_sizing_penalty()

        pause, pause_reason = self.should_pause_trading()
        return {
            "per_symbol":      report,
            "overall_quality": round(overall_quality, 3),
            "pause_trading":   pause,
            "pause_reason":    pause_reason,
            "sizing_penalty":  self.get_sizing_penalty(),
            "n_symbols":       len(self._records),
        }
