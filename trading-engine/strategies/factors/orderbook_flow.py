"""
Orderbook Flow Factor — Real Bid-Ask Microstructure
====================================================
ใช้ข้อมูล Level 2 orderbook (bid/ask depth) จาก exchange จริงๆ
เพื่อวัด buy/sell pressure ณ ขณะที่จะ entry

ข้อมูลที่ใช้:
1. Bid-Ask Imbalance: (bid_vol - ask_vol) / (bid_vol + ask_vol)
   - Positive → buy pressure (bid wall ใหญ่กว่า ask)
   - Negative → sell pressure
2. Depth Slope: bid depth slope vs ask depth slope
   - Bid depth steeper = buyers aggressive ใกล้ market
3. Spread Ratio: current spread / avg spread
   - Spread กว้างกว่าปกติ = ลดความมั่นใจสัญญาณ
4. Liquidation Cluster Estimate: ราคาที่ concentration of stops likely
   - ถ้า price approaching cluster → boost signal ตาม direction

Returns: float [-1.0, +1.0]
  +1.0 = strong buy pressure in orderbook
  -1.0 = strong sell pressure in orderbook
   0.0 = neutral / no data

Usage (ใน main loop):
    ob_factor = OrderbookFlowFactor()

    # Every loop (or every few minutes):
    snapshot = ccxt_client.fetch_order_book(symbol, limit=20)
    ob_factor.update(symbol, snapshot)

    # At signal generation time:
    score = ob_factor.score(symbol, signal_direction="LONG")
    # Use score to boost/reduce composite_score before ML filter

Integration ใน signal_engine.py (v5 patch):
    ob_score = ob_factor.score(symbol, direction)
    composite_score += ob_score * 0.10   # 10% weight for OB confirmation
"""
from __future__ import annotations

import numpy as np
import math
from collections import deque
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple


# ── Config ──────────────────────────────────────────────────────────────────
OB_SNAPSHOT_WINDOW   = 10    # เก็บ N snapshots ล่าสุด (rolling window)
OB_DEPTH_LEVELS      = 20    # ใช้กี่ level จาก orderbook
OB_SPREAD_LOOKBACK   = 50    # bars ใช้คำนวณ avg spread
OB_IMBALANCE_SCALE   = 0.40  # imbalance ที่ถือว่า "เต็ม signal" (40%)
OB_LIQ_CLUSTER_RANGE = 0.015 # ± 1.5% รอบ current price สำหรับ liquidation cluster


class OrderbookFlowFactor:
    """
    Level 2 orderbook microstructure factor.

    Thread-safe via deque (no lock needed — Python GIL protects deque ops).
    """

    def __init__(self):
        # symbol → deque of snapshots
        self._snapshots: Dict[str, deque] = {}
        # symbol → deque of spread history (for normalization)
        self._spread_history: Dict[str, deque] = {}
        # symbol → last score (for logging/dashboard)
        self._last_score: Dict[str, float] = {}
        # symbol → last price (used for liquidation cluster)
        self._last_price: Dict[str, float] = {}

    # ── Data Ingestion ───────────────────────────────────────────────────────

    def update(self, symbol: str, orderbook: dict, current_price: float = 0.0):
        """
        Ingest a new orderbook snapshot.

        Args:
            symbol:   e.g. "BTC-USDT-SWAP"
            orderbook: dict from ccxt fetch_order_book():
                       {"bids": [[price, size], ...], "asks": [[price, size], ...]}
            current_price: latest trade price (for spread normalization)
        """
        if not orderbook or "bids" not in orderbook or "asks" not in orderbook:
            return

        bids = orderbook.get("bids", [])[:OB_DEPTH_LEVELS]
        asks = orderbook.get("asks", [])[:OB_DEPTH_LEVELS]

        if not bids or not asks:
            return

        snapshot = self._parse_snapshot(bids, asks, current_price)

        if symbol not in self._snapshots:
            self._snapshots[symbol] = deque(maxlen=OB_SNAPSHOT_WINDOW)
            self._spread_history[symbol] = deque(maxlen=OB_SPREAD_LOOKBACK)

        self._snapshots[symbol].append(snapshot)

        if snapshot["spread_pct"] > 0:
            self._spread_history[symbol].append(snapshot["spread_pct"])

        if current_price > 0:
            self._last_price[symbol] = current_price

    def _parse_snapshot(self, bids: list, asks: list,
                        current_price: float) -> dict:
        """Extract key metrics from raw bids/asks."""
        bid_prices  = [b[0] for b in bids if len(b) >= 2]
        bid_sizes   = [b[1] for b in bids if len(b) >= 2]
        ask_prices  = [a[0] for a in asks if len(a) >= 2]
        ask_sizes   = [a[1] for a in asks if len(a) >= 2]

        best_bid = bid_prices[0] if bid_prices else 0.0
        best_ask = ask_prices[0] if ask_prices else 0.0

        total_bid_vol = sum(bid_sizes)
        total_ask_vol = sum(ask_sizes)
        total_vol = total_bid_vol + total_ask_vol + 1e-10

        # Imbalance: positive = bid-heavy (buy pressure)
        imbalance = (total_bid_vol - total_ask_vol) / total_vol

        # Weighted mid-price (volume-weighted)
        wm_bid = (sum(p * s for p, s in zip(bid_prices, bid_sizes))
                  / (total_bid_vol + 1e-10)) if bid_prices else best_bid
        wm_ask = (sum(p * s for p, s in zip(ask_prices, ask_sizes))
                  / (total_ask_vol + 1e-10)) if ask_prices else best_ask

        # Spread
        spread_abs = best_ask - best_bid
        mid = (best_bid + best_ask) / 2 if best_bid and best_ask else current_price
        spread_pct = (spread_abs / mid * 100) if mid > 0 else 0.0

        # Bid depth slope: how quickly does bid volume thin out with distance?
        # Steeper bid = strong support nearby
        bid_depth_score = self._depth_slope(bid_prices, bid_sizes, sign=1)
        ask_depth_score = self._depth_slope(ask_prices, ask_sizes, sign=-1)

        return {
            "timestamp":      datetime.now(timezone.utc).isoformat(),
            "best_bid":       best_bid,
            "best_ask":       best_ask,
            "mid":            mid,
            "spread_pct":     spread_pct,
            "total_bid_vol":  total_bid_vol,
            "total_ask_vol":  total_ask_vol,
            "imbalance":      imbalance,      # [-1, +1]
            "bid_depth_score": bid_depth_score,
            "ask_depth_score": ask_depth_score,
        }

    def _depth_slope(self, prices: list, sizes: list, sign: int = 1) -> float:
        """
        Measure how concentrated volume is near the best price.
        High concentration near best = aggressive positioning = strong signal.
        Returns float in [-1, +1] (positive = bullish for bids, bearish for asks).
        """
        if len(prices) < 2 or sum(sizes) == 0:
            return 0.0

        total = sum(sizes)
        # Volume in first 5 levels vs last 5 levels
        n = min(5, len(sizes))
        near_vol  = sum(sizes[:n])
        far_vol   = sum(sizes[-n:]) if len(sizes) > n else 0

        if near_vol + far_vol == 0:
            return 0.0

        concentration = (near_vol - far_vol) / (near_vol + far_vol + 1e-10)
        return float(np.clip(concentration * sign, -1.0, 1.0))

    # ── Score Computation ────────────────────────────────────────────────────

    def score(self, symbol: str, direction: str = None) -> float:
        """
        Compute orderbook flow score for a symbol.

        Args:
            symbol:    trading pair
            direction: "LONG", "SHORT", or None (unsigned score)

        Returns:
            float in [-1, +1]:
              Positive = buy pressure (favors LONG)
              Negative = sell pressure (favors SHORT)
              0 = neutral / no data
        """
        snaps = self._snapshots.get(symbol)
        if not snaps:
            return 0.0

        # Use last N snapshots (EMA-weighted, recent = higher weight)
        n = len(snaps)
        weights = np.exp(np.linspace(-1, 0, n))  # exp decay
        weights /= weights.sum()

        imbalances    = [s["imbalance"]       for s in snaps]
        bid_depths    = [s["bid_depth_score"] for s in snaps]
        ask_depths    = [s["ask_depth_score"] for s in snaps]
        spread_pcts   = [s["spread_pct"]      for s in snaps]

        # ── Component 1: Bid-Ask Imbalance ──
        avg_imbalance = float(np.dot(imbalances, weights))
        imb_signal = float(np.clip(avg_imbalance / OB_IMBALANCE_SCALE, -1.0, 1.0))

        # ── Component 2: Depth Slope Differential ──
        avg_bid_depth = float(np.dot(bid_depths, weights))
        avg_ask_depth = float(np.dot(ask_depths, weights))
        depth_signal = float(np.clip((avg_bid_depth + avg_ask_depth) / 2, -1.0, 1.0))

        # ── Component 3: Spread Confidence Modifier ──
        # Wide spread = uncertain market = reduce signal strength
        spread_history = self._spread_history.get(symbol)
        if spread_history and len(spread_history) >= 5:
            avg_spread = np.mean(list(spread_history)[:-1])  # exclude most recent
            current_spread = spread_pcts[-1] if spread_pcts else avg_spread
            spread_ratio = current_spread / (avg_spread + 1e-6)
            # Normal spread (<1.5x avg): confidence = 1.0
            # Wide spread (>3x avg): confidence = 0.4
            spread_confidence = float(np.clip(1.5 / max(spread_ratio, 1.0), 0.4, 1.0))
        else:
            spread_confidence = 0.8  # no history → moderate confidence

        # ── Composite Score ──
        raw_score = (
            imb_signal   * 0.55 +    # Imbalance is the primary signal
            depth_signal * 0.45      # Depth slope as confirmation
        ) * spread_confidence

        raw_score = float(np.clip(raw_score, -1.0, 1.0))
        self._last_score[symbol] = raw_score

        # ── Direction gate ──
        # If direction is given, return 0 if OB opposes it strongly
        if direction == "LONG" and raw_score < -0.3:
            return 0.0    # OB strongly bearish → don't amplify LONG signal
        if direction == "SHORT" and raw_score > 0.3:
            return 0.0    # OB strongly bullish → don't amplify SHORT signal

        return raw_score

    def get_liquidation_pressure(self, symbol: str, current_price: float) -> float:
        """
        Estimate liquidation pressure near current price.

        If there's a large ask wall above current price (likely stop-loss cluster
        for shorts or TP for longs), a breakout could accelerate.

        Returns: float in [-1, +1]
          Positive = upside liquidation pressure (shorts being squeezed)
          Negative = downside liquidation pressure (longs being squeezed)
        """
        snaps = self._snapshots.get(symbol)
        if not snaps or current_price <= 0:
            return 0.0

        latest = snaps[-1]
        mid = latest.get("mid", current_price)

        if mid <= 0:
            return 0.0

        # Measure asymmetry between bid/ask total volume
        bid_vol = latest.get("total_bid_vol", 0)
        ask_vol = latest.get("total_ask_vol", 0)

        if bid_vol + ask_vol == 0:
            return 0.0

        # Large ask wall above = resistance → possible SHORT liquidation squeeze above
        # Large bid wall below = support → possible LONG liquidation squeeze below
        vol_ratio = (ask_vol - bid_vol) / (ask_vol + bid_vol + 1e-10)
        # vol_ratio positive = more asks (resistance, bearish pressure)
        # vol_ratio negative = more bids (support, bullish pressure)

        return float(np.clip(-vol_ratio * 1.5, -1.0, 1.0))

    def get_spread_quality(self, symbol: str) -> str:
        """Return spread quality label: 'tight', 'normal', 'wide', 'extreme'."""
        spread_history = self._spread_history.get(symbol)
        snaps = self._snapshots.get(symbol)
        if not spread_history or not snaps:
            return "unknown"

        current_spread = snaps[-1].get("spread_pct", 0)
        avg_spread = np.mean(list(spread_history))

        ratio = current_spread / (avg_spread + 1e-6)
        if ratio < 0.8:
            return "tight"
        elif ratio < 1.5:
            return "normal"
        elif ratio < 3.0:
            return "wide"
        else:
            return "extreme"

    def get_report(self, symbol: str = None) -> dict:
        """Return current orderbook metrics for dashboard/logging."""
        symbols = [symbol] if symbol else list(self._snapshots.keys())
        report = {}
        for sym in symbols:
            snaps = self._snapshots.get(sym)
            if not snaps:
                continue
            latest = snaps[-1]
            report[sym] = {
                "last_score":        round(self._last_score.get(sym, 0.0), 4),
                "imbalance":         round(latest.get("imbalance", 0), 4),
                "spread_pct":        round(latest.get("spread_pct", 0), 5),
                "spread_quality":    self.get_spread_quality(sym),
                "bid_depth_score":   round(latest.get("bid_depth_score", 0), 3),
                "ask_depth_score":   round(latest.get("ask_depth_score", 0), 3),
                "total_bid_vol":     round(latest.get("total_bid_vol", 0), 4),
                "total_ask_vol":     round(latest.get("total_ask_vol", 0), 4),
                "n_snapshots":       len(snaps),
            }
        return report

    def has_data(self, symbol: str) -> bool:
        """Return True if we have at least one snapshot for symbol."""
        snaps = self._snapshots.get(symbol)
        return bool(snaps and len(snaps) > 0)
