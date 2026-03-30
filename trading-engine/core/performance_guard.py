from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Dict, Tuple


@dataclass
class GuardBucket:
    recent_pnl: deque = field(default_factory=lambda: deque(maxlen=30))
    recent_r: deque = field(default_factory=lambda: deque(maxlen=30))
    total_trades: int = 0
    disabled_until_bar: int = 0

    @property
    def avg_pnl(self) -> float:
        return sum(self.recent_pnl) / max(len(self.recent_pnl), 1)

    @property
    def avg_r(self) -> float:
        return sum(self.recent_r) / max(len(self.recent_r), 1) if self.recent_r else 0.0

    @property
    def win_rate(self) -> float:
        if not self.recent_pnl:
            return 0.0
        wins = sum(1 for v in self.recent_pnl if v > 0)
        return wins / len(self.recent_pnl)


class StrategyPerformanceGuard:
    """
    Blocks or scales strategies that are losing after fees.

    Keyed by (symbol, timeframe, strategy, regime) so weak pockets of performance
    can be disabled without killing the entire engine.
    """

    def __init__(
        self,
        min_trades: int = 8,
        reduce_after_trades: int = 5,
        disable_after_trades: int = 10,
        cooldown_bars: int = 48,
        weak_avg_pnl: float = -0.03,
        weak_avg_r: float = -0.10,
        disable_avg_pnl: float = -0.10,
        disable_avg_r: float = -0.25,
    ):
        self.min_trades = min_trades
        self.reduce_after_trades = reduce_after_trades
        self.disable_after_trades = disable_after_trades
        self.cooldown_bars = cooldown_bars
        self.weak_avg_pnl = weak_avg_pnl
        self.weak_avg_r = weak_avg_r
        self.disable_avg_pnl = disable_avg_pnl
        self.disable_avg_r = disable_avg_r
        self._bar = 0
        self._buckets: Dict[Tuple[str, str, str, int], GuardBucket] = defaultdict(GuardBucket)

    def tick(self):
        self._bar += 1

    def reset(self):
        self._bar = 0
        self._buckets.clear()

    def _key(self, symbol: str, timeframe: str, strategy: str, regime: int) -> Tuple[str, str, str, int]:
        return ((symbol or "UNKNOWN").upper(), timeframe or "5m", strategy or "UNKNOWN", int(regime))

    def load_from_dataframe(self, df, timeframe: str, reset: bool = True):
        if reset:
            self.reset()
        if df is None or len(df) == 0:
            return
        for _, row in df.iloc[::-1].iterrows():
            self.record_outcome(
                symbol=row.get("symbol", "UNKNOWN"),
                timeframe=timeframe,
                strategy=row.get("strategy", "UNKNOWN"),
                regime=int(row.get("regime", 0) or 0),
                pnl=float(row.get("pnl", 0) or 0),
                r_multiple=None,
                historical=True,
            )

    def record_outcome(
        self,
        symbol: str,
        timeframe: str,
        strategy: str,
        regime: int,
        pnl: float,
        r_multiple: float | None,
        historical: bool = False,
    ):
        bucket = self._buckets[self._key(symbol, timeframe, strategy, regime)]
        bucket.recent_pnl.append(float(pnl))
        if r_multiple is not None:
            bucket.recent_r.append(float(r_multiple))
        bucket.total_trades += 1

        enough_disable = len(bucket.recent_pnl) >= self.disable_after_trades
        avg_r = bucket.avg_r if bucket.recent_r else 0.0
        if enough_disable and bucket.avg_pnl <= self.disable_avg_pnl:
            if not bucket.recent_r or avg_r <= self.disable_avg_r:
                bucket.disabled_until_bar = max(bucket.disabled_until_bar, self._bar + self.cooldown_bars)
                if not historical:
                    print(
                        f"[PERF-GUARD] DISABLE {strategy} {symbol} tf={timeframe} regime={regime} "
                        f"avg_pnl={bucket.avg_pnl:+.3f} avg_r={avg_r:+.2f}"
                    )

    def can_trade(self, symbol: str, timeframe: str, strategy: str, regime: int) -> tuple[bool, str]:
        bucket = self._buckets.get(self._key(symbol, timeframe, strategy, regime))
        if not bucket:
            return True, "no history"
        if self._bar < bucket.disabled_until_bar:
            return False, f"disabled for {bucket.disabled_until_bar - self._bar} more bars"
        if len(bucket.recent_pnl) < self.min_trades:
            return True, "warming up"
        avg_r = bucket.avg_r if bucket.recent_r else 0.0
        if bucket.avg_pnl <= self.disable_avg_pnl and (not bucket.recent_r or avg_r <= self.disable_avg_r):
            return False, f"after-fee expectancy weak ({bucket.avg_pnl:+.3f}, R={avg_r:+.2f})"
        return True, "ok"

    def get_size_multiplier(self, symbol: str, timeframe: str, strategy: str, regime: int) -> float:
        bucket = self._buckets.get(self._key(symbol, timeframe, strategy, regime))
        if not bucket or len(bucket.recent_pnl) < self.reduce_after_trades:
            return 1.0
        avg_r = bucket.avg_r if bucket.recent_r else 0.0
        if bucket.avg_pnl <= self.disable_avg_pnl and (not bucket.recent_r or avg_r <= self.disable_avg_r):
            return 0.0
        if bucket.avg_pnl <= self.weak_avg_pnl or (bucket.recent_r and avg_r <= self.weak_avg_r):
            return 0.5
        if bucket.win_rate < 0.40 and bucket.avg_pnl < 0:
            return 0.75
        return 1.0

    def get_report(self) -> dict:
        report = {}
        for key, bucket in self._buckets.items():
            report["|".join(map(str, key))] = {
                "trades": len(bucket.recent_pnl),
                "avg_pnl": round(bucket.avg_pnl, 4),
                "avg_r": round(bucket.avg_r, 4),
                "win_rate": round(bucket.win_rate, 4),
                "disabled_until_bar": bucket.disabled_until_bar,
            }
        return report

