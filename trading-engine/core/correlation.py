"""
Position Correlation Manager
==============================
Prevents over-concentration by checking correlation between open positions
and new signals before entry.
"""
import numpy as np
import pandas as pd
from typing import Dict, List, Optional


class CorrelationManager:
    """Check correlation between trading pairs to prevent over-concentration."""

    def __init__(self, max_correlated: int = 2, correlation_threshold: float = 0.7,
                 lookback_days: int = 30):
        self.max_correlated = max_correlated
        self.correlation_threshold = correlation_threshold
        self.lookback_days = lookback_days
        self._correlation_matrix: Optional[pd.DataFrame] = None
        self._price_cache: Dict[str, pd.Series] = {}

    def update_prices(self, symbol: str, prices: pd.Series):
        """Update price cache for a symbol."""
        self._price_cache[symbol] = prices
        self._correlation_matrix = None  # invalidate cache

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
        """Get correlation between two symbols. Returns 0 if unknown."""
        if symbol_a == symbol_b:
            return 1.0

        corr_matrix = self._build_correlation_matrix()
        if corr_matrix.empty:
            return 0.0

        if symbol_a in corr_matrix.columns and symbol_b in corr_matrix.columns:
            return float(corr_matrix.loc[symbol_a, symbol_b])
        return 0.0

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
