"""
Event-Driven Risk Module
========================
ตรวจจับ events ที่อาจทำให้ตลาด disrupted ก่อนที่จะ entry

Events ที่ monitor:
1. Funding Rate Spike — funding สูงผิดปกติ (ตลาด over-leveraged)
2. OI Divergence — OI เพิ่มขึ้นแต่ราคาไม่ยืนยัน (squeeze risk)
3. Funding Rate Direction Flip — funding เปลี่ยนทิศ = market rebalancing
4. Session Dead Zone — low-liquidity hours (ลด size หรือ skip)
5. Macro Blackout — ช่วง high-impact events (FOMC, CPI) — ใช้ hardcoded calendar
6. Funding Payment Windows — ±30 min รอบ funding payment → ตลาดผิดปกติ
7. Rapid Price Anomaly — sudden pump/dump ≥ 2% ใน 1 bar → skip entry

Usage:
    event_risk = EventRiskManager()

    # ทุก loop:
    event_risk.update_funding(symbol, rate, next_funding_timestamp)
    event_risk.update_oi(symbol, current_oi, prev_oi)
    event_risk.update_price(symbol, last_close, prev_closes)

    # ก่อน entry:
    decision = event_risk.should_skip_entry(symbol, signal_direction)
    if decision.skip:
        print(f"[SKIP] {decision.reason}")
        continue

    # ปรับ size ตาม event risk level:
    size_mult = event_risk.get_size_multiplier(symbol)
    position_size *= size_mult
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple


# ── Thresholds ──────────────────────────────────────────────────────────────
FUNDING_SPIKE_THRESHOLD    = 0.0008    # 0.08% per 8h = elevated (config MAX is 0.1%)
FUNDING_EXTREME_THRESHOLD  = 0.0015    # 0.15% = extreme
OI_SURGE_THRESHOLD         = 0.05      # 5% OI increase in last bar = surge
OI_DIVERGE_THRESHOLD       = 0.03      # 3% OI move opposite to price = divergence
PRICE_ANOMALY_PCT          = 0.02      # 2% single-bar move = anomaly
FUNDING_WINDOW_MINUTES     = 30        # ±30 min around funding payment
DEAD_ZONE_HOURS_UTC        = {0, 1, 23}  # UTC hours with low liquidity

# ── Macro event blackout calendar (UTC) ──────────────────────────────────────
# Format: (month, day, hour_start, hour_end, label)
# Update this annually or integrate with economic calendar API
MACRO_BLACKOUT_EVENTS: List[Tuple[int, int, int, int, str]] = [
    # FOMC meetings 2026 (approximate)
    (1, 28, 18, 22, "FOMC"),
    (3, 18, 18, 22, "FOMC"),
    (5, 6, 18, 22, "FOMC"),
    (6, 17, 18, 22, "FOMC"),
    (7, 29, 18, 22, "FOMC"),
    (9, 16, 18, 22, "FOMC"),
    (11, 4, 18, 22, "FOMC"),
    (12, 16, 18, 22, "FOMC"),
]


@dataclass
class EventDecision:
    """Result of event risk check."""
    skip:         bool
    reason:       str
    severity:     str        # 'none', 'low', 'medium', 'high', 'extreme'
    size_mult:    float      # 0.0–1.0 position size multiplier
    active_events: List[str] = field(default_factory=list)

    @property
    def should_reduce(self) -> bool:
        return self.size_mult < 1.0 and not self.skip


class EventRiskManager:
    """
    Monitors multiple event sources and provides entry/sizing decisions.

    Designed to be called every main loop iteration.
    """

    def __init__(self):
        # Per-symbol state
        self._funding_history:  Dict[str, deque] = {}   # (rate, timestamp) tuples
        self._oi_history:       Dict[str, deque] = {}   # (oi, timestamp) tuples
        self._price_history:    Dict[str, deque] = {}   # close prices
        self._next_funding_ts:  Dict[str, Optional[datetime]] = {}

        # Global state
        self._last_checked: Optional[datetime] = None

    # ── Data Ingestion ───────────────────────────────────────────────────────

    def update_funding(self, symbol: str, rate: float,
                       next_funding_ts: Optional[int] = None):
        """
        Call this after fetching mark price / funding info.

        Args:
            symbol:          trading pair
            rate:            current funding rate (e.g. 0.0001 = 0.01%)
            next_funding_ts: Unix timestamp (ms) of next funding payment
        """
        if symbol not in self._funding_history:
            self._funding_history[symbol] = deque(maxlen=20)

        self._funding_history[symbol].append({
            "rate":      float(rate),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        if next_funding_ts:
            try:
                self._next_funding_ts[symbol] = datetime.fromtimestamp(
                    int(next_funding_ts) / 1000, tz=timezone.utc
                )
            except Exception:
                pass

    def update_oi(self, symbol: str, current_oi: float, prev_oi: float = 0.0):
        """Update open interest. Call from main loop after fetching OI."""
        if symbol not in self._oi_history:
            self._oi_history[symbol] = deque(maxlen=30)

        self._oi_history[symbol].append({
            "oi":        float(current_oi),
            "prev_oi":   float(prev_oi),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def update_price(self, symbol: str, close: float,
                     prev_closes: Optional[List[float]] = None):
        """Update recent price history for anomaly detection."""
        if symbol not in self._price_history:
            self._price_history[symbol] = deque(maxlen=20)

        self._price_history[symbol].append(float(close))

        if prev_closes:
            for p in prev_closes[-10:]:
                self._price_history[symbol].append(float(p))

    # ── Main Gate ────────────────────────────────────────────────────────────

    def should_skip_entry(
        self, symbol: str, direction: str = None,
        now: Optional[datetime] = None
    ) -> EventDecision:
        """
        Main entry gate. Call before every signal execution.

        Returns EventDecision with skip=True if entry should be blocked,
        or skip=False with size_mult < 1.0 if size should be reduced.
        """
        if now is None:
            now = datetime.now(timezone.utc)

        active_events = []
        worst_severity = "none"
        min_size_mult  = 1.0
        skip = False
        reason = ""

        # ── Check 1: Funding Spike ──
        funding_check = self._check_funding_spike(symbol)
        if funding_check["severity"] != "none":
            active_events.append(f"FundingSpike({funding_check['rate_pct']:.3f}%)")
            if funding_check["severity"] == "extreme":
                skip = True
                reason = f"Funding rate extreme: {funding_check['rate_pct']:.3f}%"
            elif funding_check["severity"] == "high":
                min_size_mult = min(min_size_mult, 0.5)
            else:
                min_size_mult = min(min_size_mult, 0.75)
            worst_severity = _max_severity(worst_severity, funding_check["severity"])

        # ── Check 2: Funding Payment Window ──
        payment_check = self._check_funding_payment_window(symbol, now)
        if payment_check["in_window"]:
            active_events.append(f"FundingWindow(T{payment_check['minutes_to_payment']:+.0f}min)")
            min_size_mult = min(min_size_mult, 0.5)
            worst_severity = _max_severity(worst_severity, "medium")

        # ── Check 3: OI Divergence ──
        oi_check = self._check_oi_divergence(symbol, direction)
        if oi_check["alert"]:
            active_events.append(f"OIDivergence({oi_check['oi_change_pct']:.2f}%)")
            min_size_mult = min(min_size_mult, 0.6)
            worst_severity = _max_severity(worst_severity, "medium")
            if oi_check.get("extreme"):
                min_size_mult = min(min_size_mult, 0.0)
                skip = True
                reason = f"Extreme OI divergence: {oi_check['oi_change_pct']:.2f}% OI move"

        # ── Check 4: Price Anomaly ──
        anomaly_check = self._check_price_anomaly(symbol)
        if anomaly_check["detected"]:
            active_events.append(f"PriceAnomaly({anomaly_check['move_pct']:.2f}%)")
            if anomaly_check["extreme"]:
                skip = True
                reason = f"Price anomaly: {anomaly_check['move_pct']:.2f}% in 1 bar"
            else:
                min_size_mult = min(min_size_mult, 0.5)
            worst_severity = _max_severity(worst_severity, "high")

        # ── Check 5: Session Dead Zone ──
        dead_zone_check = self._check_dead_zone(now)
        if dead_zone_check["in_dead_zone"]:
            active_events.append(f"DeadZone(UTC{now.hour:02d})")
            min_size_mult = min(min_size_mult, 0.5)
            worst_severity = _max_severity(worst_severity, "low")

        # ── Check 6: Macro Blackout ──
        macro_check = self._check_macro_blackout(now)
        if macro_check["in_blackout"]:
            active_events.append(f"MacroEvent({macro_check['event_name']})")
            skip = True
            reason = f"Macro event blackout: {macro_check['event_name']}"
            worst_severity = _max_severity(worst_severity, "extreme")

        # ── Funding direction flip ──
        flip_check = self._check_funding_flip(symbol)
        if flip_check["flipped"]:
            active_events.append(f"FundingFlip({flip_check['direction']})")
            min_size_mult = min(min_size_mult, 0.7)
            worst_severity = _max_severity(worst_severity, "low")

        # ── Compose final decision ──
        if not reason:
            if skip:
                reason = " | ".join(active_events) or "Multiple risk events"
            elif active_events:
                reason = f"Risk events: {', '.join(active_events)} → size×{min_size_mult:.2f}"
            else:
                reason = "No events"

        return EventDecision(
            skip          = skip,
            reason        = reason,
            severity      = worst_severity,
            size_mult     = 0.0 if skip else min_size_mult,
            active_events = active_events,
        )

    def get_size_multiplier(self, symbol: str,
                             now: Optional[datetime] = None) -> float:
        """Shorthand: return size multiplier without full skip logic."""
        decision = self.should_skip_entry(symbol, now=now)
        return 0.0 if decision.skip else decision.size_mult

    # ── Individual Checks ────────────────────────────────────────────────────

    def _check_funding_spike(self, symbol: str) -> dict:
        hist = self._funding_history.get(symbol)
        if not hist:
            return {"severity": "none", "rate_pct": 0.0}

        current_rate = abs(hist[-1]["rate"])

        if current_rate >= FUNDING_EXTREME_THRESHOLD:
            return {"severity": "extreme", "rate_pct": current_rate * 100}
        elif current_rate >= FUNDING_SPIKE_THRESHOLD:
            return {"severity": "high", "rate_pct": current_rate * 100}
        elif current_rate >= FUNDING_SPIKE_THRESHOLD * 0.6:
            return {"severity": "medium", "rate_pct": current_rate * 100}
        return {"severity": "none", "rate_pct": current_rate * 100}

    def _check_funding_payment_window(
        self, symbol: str, now: datetime
    ) -> dict:
        ts = self._next_funding_ts.get(symbol)
        if not ts:
            return {"in_window": False, "minutes_to_payment": 9999}

        delta_minutes = (ts - now).total_seconds() / 60
        in_window = abs(delta_minutes) <= FUNDING_WINDOW_MINUTES
        return {"in_window": in_window, "minutes_to_payment": delta_minutes}

    def _check_oi_divergence(self, symbol: str, direction: str = None) -> dict:
        hist = self._oi_history.get(symbol)
        if not hist or len(hist) < 2:
            return {"alert": False, "oi_change_pct": 0.0}

        recent = hist[-1]
        prev_oi = recent.get("prev_oi", 0) or (hist[-2]["oi"] if len(hist) >= 2 else 0)
        curr_oi = recent["oi"]

        if prev_oi <= 0:
            return {"alert": False, "oi_change_pct": 0.0}

        oi_change_pct = (curr_oi - prev_oi) / prev_oi * 100

        # OI surging → lots of new leveraged positions → potential squeeze
        alert = abs(oi_change_pct) >= OI_SURGE_THRESHOLD * 100
        extreme = abs(oi_change_pct) >= OI_SURGE_THRESHOLD * 200

        return {
            "alert":          alert,
            "extreme":        extreme,
            "oi_change_pct":  oi_change_pct,
        }

    def _check_price_anomaly(self, symbol: str) -> dict:
        hist = self._price_history.get(symbol)
        if not hist or len(hist) < 2:
            return {"detected": False, "move_pct": 0.0, "extreme": False}

        prices = list(hist)
        move_pct = abs(prices[-1] - prices[-2]) / (prices[-2] + 1e-10) * 100

        detected = move_pct >= PRICE_ANOMALY_PCT * 100
        extreme  = move_pct >= PRICE_ANOMALY_PCT * 200  # 4%+ = extreme

        return {"detected": detected, "move_pct": move_pct, "extreme": extreme}

    def _check_dead_zone(self, now: datetime) -> dict:
        in_dead = now.hour in DEAD_ZONE_HOURS_UTC
        return {"in_dead_zone": in_dead, "hour_utc": now.hour}

    def _check_macro_blackout(self, now: datetime) -> dict:
        month = now.month
        day   = now.day
        hour  = now.hour

        for (ev_month, ev_day, h_start, h_end, label) in MACRO_BLACKOUT_EVENTS:
            if month == ev_month and day == ev_day and h_start <= hour < h_end:
                return {"in_blackout": True, "event_name": label}
        return {"in_blackout": False, "event_name": ""}

    def _check_funding_flip(self, symbol: str) -> dict:
        hist = self._funding_history.get(symbol)
        if not hist or len(hist) < 3:
            return {"flipped": False, "direction": ""}

        rates = [h["rate"] for h in hist]
        recent = rates[-1]
        prev   = rates[-3]  # compare 3 periods back

        flipped = (recent > 0 and prev < 0) or (recent < 0 and prev > 0)
        direction = "positive→negative" if (prev > 0 and recent < 0) else \
                    "negative→positive" if (prev < 0 and recent > 0) else ""

        return {"flipped": flipped, "direction": direction}

    # ── Reporting ────────────────────────────────────────────────────────────

    def get_risk_dashboard(self, symbols: Optional[List[str]] = None) -> dict:
        """Return current event risk status for all symbols (for dashboard)."""
        now = datetime.now(timezone.utc)
        result = {}

        target_symbols = symbols or (
            list(self._funding_history.keys()) or
            list(self._price_history.keys())
        )

        for sym in target_symbols:
            decision = self.should_skip_entry(sym, now=now)
            funding = self._funding_history.get(sym)
            latest_rate = abs(funding[-1]["rate"]) if funding else 0

            result[sym] = {
                "skip_entry":     decision.skip,
                "severity":       decision.severity,
                "size_mult":      round(decision.size_mult, 3),
                "active_events":  decision.active_events,
                "funding_rate":   round(latest_rate * 100, 4),
                "reason":         decision.reason,
            }

        # Global checks
        dead = self._check_dead_zone(now)
        macro = self._check_macro_blackout(now)

        result["_global"] = {
            "in_dead_zone":   dead["in_dead_zone"],
            "hour_utc":       dead["hour_utc"],
            "macro_blackout": macro["in_blackout"],
            "macro_event":    macro.get("event_name", ""),
            "checked_at":     now.isoformat(),
        }

        return result


# ── Helpers ──────────────────────────────────────────────────────────────────

_SEVERITY_ORDER = {"none": 0, "low": 1, "medium": 2, "high": 3, "extreme": 4}

def _max_severity(a: str, b: str) -> str:
    if _SEVERITY_ORDER.get(a, 0) >= _SEVERITY_ORDER.get(b, 0):
        return a
    return b
