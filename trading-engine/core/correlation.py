"""
Position Correlation Manager — v2 (Regime-Aware + EWM Real-Time)
==================================================================
Prevents over-concentration by checking correlation between open positions
and new signals before entry.

v2 upgrades:
  1. Regime-aware thresholds: stricter during trending (correlated moves = bigger losses)
  2. EWM (Exponential Weighted) correlation: recent data matters more
  3. Rolling EWM update: O(1) per bar instead of full recalculation
  4. Per-regime correlation budgets: max concurrent positions per regime type
  5. Portfolio heatmap for dashboard reporting
"""
import numpy as np
import pandas as pd
from collections import deque
from typing import Dict, List, Optional, Tuple

# ── Regime constants (mirror regime_detector.py) ──────────────────────────
TRENDING_UP   = 0
RANGING       = 1
VOLATILE      = 2
TRENDING_DOWN = 3

# ── Regime-specific correlation thresholds ────────────────────────────────
# Trending: tighter (correlated positions amplify drawdown during reversals)
# Ranging:  looser  (mean-reversion signals partially offset each other)
# Volatile: tightest (sudden reversals affect all correlated positions)
REGIME_CORRELATION_THRESHOLDS = {
    TRENDING_UP:   0.60,   # Stricter: trending up → all correlated assets move together
    RANGING:       0.80,   # Looser: range trades partially cancel out
    VOLATILE:      0.50,   # Tightest: volatility spikes hit correlated assets hardest
    TRENDING_DOWN: 0.60,   # Same as trending up
    -1:            0.70,   # Unknown regime → use default
}

# ── Max positions per regime ───────────────────────────────────────────────
REGIME_MAX_POSITIONS = {
    TRENDING_UP:   3,   # Trending = momentum carries, can hold more
    RANGING:       2,   # Range = careful, MR signals can flip
    VOLATILE:      1,   # Volatile = one position max (risk control)
    TRENDING_DOWN: 3,
    -1:            2,
}


class CorrelationManager:
    """
    Check correlation between trading pairs to prevent over-concentration.
    v2: Regime-aware, EWM-based, real-time updates.
    """

    def __init__(self, max_correlated: int = 2, correlation_threshold: float = 0.7,
                 lookback_days: int = 30, ewm_span: int = 48):
        self.max_correlated = max_correlated
        self.correlation_threshold = correlation_threshold
        self.lookback_days = lookback_days
        self.ewm_span = ewm_span           # EWM span in bars (48 = 4h on 5m tf)
        self._correlation_matrix: Optional[pd.DataFrame] = None
        self._price_cache: Dict[str, pd.Series] = {}

        # v2: EWM-based rolling returns (deque for O(1) updates)
        self._returns_cache: Dict[str, deque] = {}  # symbol → last N returns
        self._ewm_corr_cache: Dict[Tuple[str, str], float] = {}   # (s1,s2) → corr
        self._ewm_dirty: bool = True

        # v2: current regime (set externally)
        self._current_regime: int = -1
        self._regime_history: deque = deque(maxlen=10)  # last 10 regime values

    def update_regime(self, regime: int):
        """
        Update current market regime. Call this every loop from main.py.
        Adjusts correlation thresholds and max position limits dynamically.
        """
        self._current_regime = regime
        self._regime_history.append(regime)

    def get_active_threshold(self) -> float:
        """Return the regime-appropriate correlation threshold."""
        return REGIME_CORRELATION_THRESHOLDS.get(
            self._current_regime, self.correlation_threshold
        )

    def get_regime_max_positions(self) -> int:
        """Return max concurrent positions for current regime."""
        base = REGIME_MAX_POSITIONS.get(self._current_regime, self.max_correlated)
        return max(1, min(base, self.max_correlated + 1))  # +1 allowance

    def update_prices(self, symbol: str, prices: pd.Series):
        """Update price cache for a symbol (both static and EWM cache)."""
        self._price_cache[symbol] = prices
        self._correlation_matrix = None  # invalidate static cache

        # v2: Update EWM returns cache
        if len(prices) > 1:
            rets = prices.pct_change().dropna().values
            # Keep last 2 × lookback bars
            max_len = int(self.lookback_days * 24 * 2)
            if symbol not in self._returns_cache:
                self._returns_cache[symbol] = deque(maxlen=max_len)
            self._returns_cache[symbol].extend(rets[-50:])  # add last 50 new bars
            self._ewm_dirty = True

    def update_price_bar(self, symbol: str, new_return: float):
        """
        Lightweight update: add a single return value (O(1) per bar).
        Use this instead of update_prices() in the main loop for real-time updates.
        """
        if symbol not in self._returns_cache:
            self._returns_cache[symbol] = deque(maxlen=self.lookback_days * 24 * 2)
        self._returns_cache[symbol].append(float(new_return))
        self._ewm_dirty = True

    def _build_ewm_correlation(self) -> Dict[Tuple[str, str], float]:
        """
        Build EWM-based pairwise correlations (faster, more recent-data-weighted).
        Uses exponential weighting so recent returns have higher influence.
        """
        if not self._ewm_dirty and self._ewm_corr_cache:
            return self._ewm_corr_cache

        symbols = list(self._returns_cache.keys())
        if len(symbols) < 2:
            self._ewm_dirty = False
            return self._ewm_corr_cache

        # Align returns series to same length
        min_len = min(len(v) for v in self._returns_cache.values())
        if min_len < 10:
            return self._ewm_corr_cache

        aligned = {}
        for sym in symbols:
            vals = list(self._returns_cache[sym])[-min_len:]
            aligned[sym] = np.array(vals, dtype=float)

        # Exponential weights: more recent = higher weight
        weights = np.exp(np.linspace(-2, 0, min_len))
        weights /= weights.sum()

        new_cache = {}
        for i, s1 in enumerate(symbols):
            for j, s2 in enumerate(symbols):
                if j <= i:
                    continue
                r1 = aligned[s1]
                r2 = aligned[s2]
                # Weighted correlation
                w_mean1 = np.dot(weights, r1)
                w_mean2 = np.dot(weights, r2)
                d1 = r1 - w_mean1
                d2 = r2 - w_mean2
                cov = np.dot(weights, d1 * d2)
                var1 = np.dot(weights, d1 ** 2)
                var2 = np.dot(weights, d2 ** 2)
                denom = np.sqrt(var1 * var2)
                corr = float(cov / denom) if denom > 1e-10 else 0.0
                corr = float(np.clip(corr, -1.0, 1.0))
                new_cache[(s1, s2)] = corr
                new_cache[(s2, s1)] = corr

        self._ewm_corr_cache = new_cache
        self._ewm_dirty = False
        return new_cache

    def _build_correlation_matrix(self) -> pd.DataFrame:
        """Build correlation matrix from cached prices."""
        if self._correlation_matrix is not None:
            return self._correlation_matrix

        if len(self._price_cache) < 2:
            return pd.DataFrame()

        # Build returns dataframe
        returns = {}
        for symbol, prices in self._price_cache.items():
            if len(prices) > 1:
                returns[symbol] = prices.pct_change().dropna()

        if len(returns) < 2:
            return pd.DataFrame()

        returns_df = pd.DataFrame(returns).dropna()
        # Use last N days
        cutoff = max(0, len(returns_df) - self.lookback_days * 24)  # hourly data
        returns_df = returns_df.iloc[cutoff:]

        self._correlation_matrix = returns_df.corr()
        return self._correlation_matrix

    def get_correlation(self, symbol_a: str, symbol_b: str) -> float:
        """
        Get correlation between two symbols.
        Prefers EWM-based correlation (real-time); falls back to static.
        """
        if symbol_a == symbol_b:
            return 1.0

        # Try EWM first (more accurate, more recent data)
        ewm_cache = self._build_ewm_correlation()
        if (symbol_a, symbol_b) in ewm_cache:
            return ewm_cache[(symbol_a, symbol_b)]

        # Fallback: static correlation matrix
        corr_matrix = self._build_correlation_matrix()
        if corr_matrix.empty:
            return 0.0

        if symbol_a in corr_matrix.columns and symbol_b in corr_matrix.columns:
            return float(corr_matrix.loc[symbol_a, symbol_b])
        return 0.0

    def can_open_position_v2(self, new_symbol: str, new_direction: str,
                             open_positions: List[dict]) -> dict:
        """
        v2: Regime-aware position check.
        Uses dynamic threshold based on current market regime.

        Returns: {allowed: bool, reason: str, correlated_with: list,
                  threshold_used: float, regime_max_pos: int}
        """
        if not open_positions:
            return {"allowed": True, "reason": "No existing positions",
                    "correlated_with": [], "threshold_used": self.get_active_threshold(),
                    "regime_max_pos": self.get_regime_max_positions()}

        active_threshold = self.get_active_threshold()
        regime_max = self.get_regime_max_positions()

        # Check total position count against regime limit
        if len(open_positions) >= regime_max:
            return {
                "allowed": False,
                "reason": f"Regime max positions ({regime_max}) reached for regime {self._current_regime}",
                "correlated_with": [],
                "threshold_used": active_threshold,
                "regime_max_pos": regime_max,
            }

        correlated_count = 0
        correlated_with = []

        for pos in open_positions:
            pos_symbol = pos.get("symbol", "")
            pos_direction = pos.get("direction", "")
            corr = self.get_correlation(new_symbol, pos_symbol)
            same_direction = (new_direction == pos_direction)
            if abs(corr) >= active_threshold and same_direction:
                correlated_count += 1
                correlated_with.append({
                    "symbol": pos_symbol,
                    "correlation": round(corr, 3),
                    "direction": pos_direction,
                })

        if correlated_count >= self.max_correlated:
            return {
                "allowed": False,
                "reason": (f"Too many correlated positions ({correlated_count} >= "
                           f"{self.max_correlated}) at threshold {active_threshold:.2f}"),
                "correlated_with": correlated_with,
                "threshold_used": active_threshold,
                "regime_max_pos": regime_max,
            }

        return {
            "allowed": True,
            "reason": "OK",
            "correlated_with": correlated_with,
            "threshold_used": active_threshold,
            "regime_max_pos": regime_max,
        }

    def can_open_position(self, new_symbol: str, new_direction: str,
                          open_positions: List[dict]) -> dict:
        """Check if opening a new position would violate correlation limits.

        Returns: {allowed: bool, reason: str, correlated_with: list}
        """
        if not open_positions:
            return {"allowed": True, "reason": "No existing positions", "correlated_with": []}

        correlated_count = 0
        correlated_with = []

        for pos in open_positions:
            pos_symbol = pos.get('symbol', '')
            pos_direction = pos.get('direction', '')

            corr = self.get_correlation(new_symbol, pos_symbol)

            # Same direction + high correlation = concentrated risk
            same_direction = (new_direction == pos_direction)
            if abs(corr) >= self.correlation_threshold and same_direction:
                correlated_count += 1
                correlated_with.append({
                    "symbol": pos_symbol,
                    "correlation": round(corr, 3),
                    "direction": pos_direction
                })

        if correlated_count >= self.max_correlated:
            return {
                "allowed": False,
                "reason": f"Too many correlated positions ({correlated_count} >= {self.max_correlated})",
                "correlated_with": correlated_with
            }

        return {"allowed": True, "reason": "OK", "correlated_with": correlated_with}

    def get_correlation_heatmap(self) -> dict:
        """
        Return full pairwise correlation matrix for dashboard display.
        Format: {(sym_a, sym_b): correlation, ...}
        """
        ewm = self._build_ewm_correlation()
        if ewm:
            return {f"{a}:{b}": round(v, 3) for (a, b), v in ewm.items() if a < b}

        # Fallback: static matrix
        mat = self._build_correlation_matrix()
        if mat.empty:
            return {}
        result = {}
        for i, s1 in enumerate(mat.columns):
            for j, s2 in enumerate(mat.columns):
                if j > i:
                    result[f"{s1}:{s2}"] = round(float(mat.loc[s1, s2]), 3)
        return result

    def get_portfolio_risk_score(self, open_positions: List[dict]) -> float:
        """Calculate a 0-1 portfolio concentration risk score.
        0 = perfectly diversified, 1 = all positions identical.
        """
        if len(open_positions) <= 1:
            return 0.0

        symbols = [p.get('symbol', '') for p in open_positions]
        unique = set(symbols)

        if len(unique) <= 1:
            return 1.0  # all same symbol

        # Average pairwise correlation
        pairs = []
        for i, s1 in enumerate(symbols):
            for j, s2 in enumerate(symbols):
                if i < j:
                    pairs.append(abs(self.get_correlation(s1, s2)))

        return float(np.mean(pairs)) if pairs else 0.0
