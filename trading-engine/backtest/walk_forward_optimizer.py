"""
Walk-Forward Parameter Optimizer
==================================
ค้นหา parameter set ที่ดีที่สุด โดยใช้ walk-forward validation
เพื่อป้องกัน curve fitting บน in-sample data

แนวคิด:
  - แบ่งข้อมูลออกเป็น N folds (train / out-of-sample)
  - แต่ละ fold: sweep parameter grid บน train → เลือก best → วัดผล OOS
  - รายงาน median OOS Sharpe และ consistency (% folds ที่ให้ Sharpe > 0)

Parameters ที่ optimize:
  - ADX_TREND_MIN (18, 20, 23, 25)
  - TREND_ATR_SL_MULT (1.2, 1.5, 1.8, 2.0)
  - TREND_ATR_TP_MULT (2.5, 3.0, 3.5, 4.0)
  - RANGE_ATR_SL_MULT (1.5, 2.0, 2.5)
  - RANGE_ATR_TP_MULT (2.0, 2.5, 3.0)
  - FEE_MULTIPLIER (2.5, 3.0, 3.5)

Usage:
    from backtest.walk_forward_optimizer import WalkForwardOptimizer
    wfo = WalkForwardOptimizer(n_folds=5, train_ratio=0.6)
    result = wfo.run(df_features, initial_capital=1000)
    print(result.best_params)
    print(result.oos_sharpe_median)
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import itertools
import json
import os
import sys
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Tuple, Optional, Any
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── Default parameter grid ──────────────────────────────────────────────────
DEFAULT_PARAM_GRID = {
    "ADX_TREND_MIN":        [18, 20, 23, 25],
    "TREND_ATR_SL_MULT":    [1.2, 1.5, 1.8],
    "TREND_ATR_TP_MULT":    [2.5, 3.0, 3.5],
    "RANGE_ATR_SL_MULT":    [1.5, 2.0, 2.5],
    "RANGE_ATR_TP_MULT":    [2.0, 2.5, 3.0],
    "FEE_MULTIPLIER":       [2.5, 3.0, 3.5],
}

# ── Reduced grid for fast mode ───────────────────────────────────────────────
FAST_PARAM_GRID = {
    "ADX_TREND_MIN":        [20, 23],
    "TREND_ATR_SL_MULT":    [1.5, 1.8],
    "TREND_ATR_TP_MULT":    [3.0, 3.5],
    "RANGE_ATR_SL_MULT":    [2.0, 2.5],
    "RANGE_ATR_TP_MULT":    [2.5, 3.0],
    "FEE_MULTIPLIER":       [3.0],
}


@dataclass
class FoldResult:
    fold_idx:        int
    train_bars:      int
    oos_bars:        int
    best_params:     Dict[str, Any]
    train_sharpe:    float
    oos_sharpe:      float
    oos_return_pct:  float
    oos_max_dd_pct:  float
    oos_n_trades:    int
    oos_win_rate:    float


@dataclass
class WFOResult:
    folds:               List[FoldResult]
    best_params:         Dict[str, Any]      # Voted across folds
    oos_sharpe_median:   float
    oos_sharpe_std:      float
    consistency_pct:     float               # % folds with OOS Sharpe > 0
    total_oos_return:    float
    total_oos_trades:    int
    param_stability:     Dict[str, Any]      # Which param values won most folds
    generated_at:        str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def summary(self) -> str:
        lines = [
            "═" * 55,
            "  WALK-FORWARD OPTIMIZATION RESULT",
            "═" * 55,
            f"  Folds:              {len(self.folds)}",
            f"  OOS Sharpe (med):   {self.oos_sharpe_median:.3f}",
            f"  OOS Sharpe (std):   {self.oos_sharpe_std:.3f}",
            f"  Consistency:        {self.consistency_pct:.1f}% folds > 0 Sharpe",
            f"  Total OOS Return:   {self.total_oos_return:.2f}%",
            f"  Total OOS Trades:   {self.total_oos_trades}",
            "",
            "  BEST PARAMS (voted across folds):",
        ]
        for k, v in self.best_params.items():
            lines.append(f"    {k:28s} = {v}")
        lines.append("═" * 55)
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "best_params":         self.best_params,
            "oos_sharpe_median":   self.oos_sharpe_median,
            "oos_sharpe_std":      self.oos_sharpe_std,
            "consistency_pct":     self.consistency_pct,
            "total_oos_return":    self.total_oos_return,
            "total_oos_trades":    self.total_oos_trades,
            "param_stability":     self.param_stability,
            "folds": [
                {
                    "fold": f.fold_idx,
                    "oos_sharpe": f.oos_sharpe,
                    "oos_return_pct": f.oos_return_pct,
                    "oos_n_trades": f.oos_n_trades,
                    "best_params": f.best_params,
                }
                for f in self.folds
            ],
            "generated_at": self.generated_at,
        }


class WalkForwardOptimizer:
    """
    Walk-Forward Parameter Optimizer for TradingClaw.

    ใช้ mini backtest engine แบบ vectorized (ไม่ใช้ backtest/engine.py เต็ม)
    เพื่อความเร็ว — คำนวณ Sharpe ต่อ parameter set ต่อ fold ได้เร็ว
    """

    def __init__(
        self,
        n_folds: int = 5,
        train_ratio: float = 0.60,
        param_grid: Optional[Dict[str, List]] = None,
        fast_mode: bool = False,
        verbose: bool = True,
    ):
        self.n_folds = n_folds
        self.train_ratio = train_ratio
        self.param_grid = param_grid or (FAST_PARAM_GRID if fast_mode else DEFAULT_PARAM_GRID)
        self.verbose = verbose
        self._all_combos = self._build_combos()
        if self.verbose:
            print(f"[WFO] Grid: {len(self._all_combos)} combinations × {n_folds} folds = "
                  f"{len(self._all_combos) * n_folds} backtests")

    # ── Public API ──────────────────────────────────────────────────────────

    def run(
        self,
        df_features: pd.DataFrame,
        initial_capital: float = 1000.0,
        save_path: Optional[str] = None,
    ) -> WFOResult:
        """
        Main entry: run walk-forward optimization.

        Args:
            df_features: DataFrame with columns required by _mini_backtest()
                         (close, atr_14, adx, regime, etc.)
            initial_capital: Starting capital in USD
            save_path: If given, saves JSON result to this path

        Returns:
            WFOResult with best params, fold stats, and consistency score
        """
        folds = self._make_folds(df_features)
        fold_results: List[FoldResult] = []

        for fold_idx, (train_df, oos_df) in enumerate(folds):
            if self.verbose:
                print(f"\n[WFO] Fold {fold_idx + 1}/{self.n_folds}  "
                      f"(train={len(train_df)}, oos={len(oos_df)} bars)")

            # ── Find best params on train ──
            best_params, train_sharpe = self._grid_search(train_df, initial_capital)

            # ── Evaluate on OOS ──
            oos_stats = self._mini_backtest(oos_df, best_params, initial_capital)

            fold_results.append(FoldResult(
                fold_idx       = fold_idx,
                train_bars     = len(train_df),
                oos_bars       = len(oos_df),
                best_params    = best_params,
                train_sharpe   = train_sharpe,
                oos_sharpe     = oos_stats["sharpe"],
                oos_return_pct = oos_stats["return_pct"],
                oos_max_dd_pct = oos_stats["max_dd_pct"],
                oos_n_trades   = oos_stats["n_trades"],
                oos_win_rate   = oos_stats["win_rate"],
            ))

            if self.verbose:
                print(f"   Train Sharpe={train_sharpe:.3f}  "
                      f"OOS Sharpe={oos_stats['sharpe']:.3f}  "
                      f"OOS Return={oos_stats['return_pct']:.1f}%  "
                      f"OOS Trades={oos_stats['n_trades']}")

        # ── Aggregate ──
        result = self._aggregate(fold_results)

        if save_path:
            self._save(result, save_path)

        if self.verbose:
            print("\n" + result.summary())

        return result

    # ── Internals ───────────────────────────────────────────────────────────

    def _build_combos(self) -> List[Dict[str, Any]]:
        """Build all parameter combinations from grid."""
        keys = list(self.param_grid.keys())
        values = list(self.param_grid.values())
        combos = []
        for combo in itertools.product(*values):
            combos.append(dict(zip(keys, combo)))
        return combos

    def _make_folds(
        self, df: pd.DataFrame
    ) -> List[Tuple[pd.DataFrame, pd.DataFrame]]:
        """
        Anchored WFO: train window grows, OOS window slides.
        Fold 0: train=[0 : n0], oos=[n0 : n0+step]
        Fold 1: train=[0 : n0+step], oos=[n0+step : n0+2*step]
        ...
        """
        n = len(df)
        # Minimum train size = 60% of a fold slice
        step = int(n / (self.n_folds + self.n_folds * (1 - self.train_ratio)))
        folds = []
        for i in range(self.n_folds):
            train_end = int(n * self.train_ratio) + i * step
            oos_end   = train_end + step
            if oos_end > n:
                oos_end = n
            if train_end >= n or train_end == oos_end:
                break
            folds.append((df.iloc[:train_end], df.iloc[train_end:oos_end]))
        return folds

    def _grid_search(
        self, df: pd.DataFrame, capital: float
    ) -> Tuple[Dict[str, Any], float]:
        """Return (best_params, best_sharpe) from grid search on df."""
        best_sharpe = -999.0
        best_params = self._all_combos[0]
        for params in self._all_combos:
            stats = self._mini_backtest(df, params, capital)
            if stats["sharpe"] > best_sharpe:
                best_sharpe = stats["sharpe"]
                best_params = params
        return best_params, best_sharpe

    def _mini_backtest(
        self, df: pd.DataFrame, params: Dict[str, Any], capital: float
    ) -> Dict[str, float]:
        """
        Vectorized mini-backtest — fast approximation for grid search.

        Logic:
        - Identify entry signals from regime + ADX + direction in df
        - Apply SL/TP from ATR × params multipliers
        - Track equity curve, compute Sharpe, max_dd, win_rate

        Returns dict with: sharpe, return_pct, max_dd_pct, n_trades, win_rate
        """
        if len(df) < 10:
            return self._empty_stats()

        try:
            adx_min   = params.get("ADX_TREND_MIN", 23)
            sl_trend  = params.get("TREND_ATR_SL_MULT", 1.5)
            tp_trend  = params.get("TREND_ATR_TP_MULT", 3.5)
            sl_range  = params.get("RANGE_ATR_SL_MULT", 2.0)
            tp_range  = params.get("RANGE_ATR_TP_MULT", 2.5)
            fee_mult  = params.get("FEE_MULTIPLIER", 3.0)

            # ── Required columns (with fallbacks) ──
            closes = df["close"].values if "close" in df.columns else np.ones(len(df))
            atrs   = df.get("atr_14", df.get("atr", pd.Series(closes * 0.01))).fillna(closes * 0.01).values
            adxs   = df.get("adx", pd.Series(20.0)).fillna(20.0).values
            regimes = df.get("regime", pd.Series(1)).fillna(1).values  # 0=TrendUp,1=Ranging,2=Volatile,3=TrendDown

            # ── Fee ──
            taker   = 0.0005
            slip    = 0.0003
            fee_per = (taker * 2 + slip)
            min_move_needed = fee_per * fee_mult

            # ── Simulate trades ──
            equity     = float(capital)
            peak       = equity
            trades     = []
            in_trade   = False
            entry_p    = 0.0
            sl_p       = 0.0
            tp_p       = 0.0
            direction  = 0  # +1 long, -1 short
            equity_curve = [equity]

            for i in range(1, len(closes)):
                c = closes[i]
                c_prev = closes[i - 1]
                atr = atrs[i] if atrs[i] > 0 else c * 0.01
                adx = adxs[i]
                regime = int(regimes[i])

                if in_trade:
                    # ── Check SL/TP ──
                    if direction == 1:
                        hit_sl = c <= sl_p
                        hit_tp = c >= tp_p
                    else:
                        hit_sl = c >= sl_p
                        hit_tp = c <= tp_p

                    if hit_tp or hit_sl:
                        exit_p = tp_p if hit_tp else sl_p
                        pnl_pct = direction * (exit_p - entry_p) / entry_p - fee_per
                        equity *= (1 + pnl_pct)
                        trades.append(pnl_pct)
                        in_trade = False

                    peak = max(peak, equity)
                    equity_curve.append(equity)
                    continue

                # ── Look for entry signal ──
                # Trending regime (0 or 3) + ADX above threshold
                if regime in (0, 3) and adx >= adx_min:
                    # Use price momentum as direction proxy
                    if i >= 5:
                        mom = (c - closes[i - 5]) / closes[i - 5]
                        if abs(mom) > min_move_needed:
                            direction  = 1 if (regime == 0 or mom > 0) else -1
                            sl_dist    = atr * sl_trend
                            tp_dist    = atr * tp_trend
                            entry_p    = c
                            sl_p       = c - direction * sl_dist
                            tp_p       = c + direction * tp_dist
                            in_trade   = True

                # Ranging regime (1) — counter-trend
                elif regime == 1 and adx < adx_min:
                    if i >= 3:
                        mom = (c - closes[i - 3]) / closes[i - 3]
                        if abs(mom) > min_move_needed * 0.7:
                            direction  = -1 if mom > 0 else 1  # counter-trend
                            sl_dist    = atr * sl_range
                            tp_dist    = atr * tp_range
                            # Require minimum R:R
                            if tp_dist / (sl_dist + 1e-10) < 1.5:
                                equity_curve.append(equity)
                                continue
                            entry_p    = c
                            sl_p       = c - direction * sl_dist
                            tp_p       = c + direction * tp_dist
                            in_trade   = True

                peak = max(peak, equity)
                equity_curve.append(equity)

            return self._compute_stats(equity_curve, trades, capital)

        except Exception as e:
            return self._empty_stats()

    def _compute_stats(
        self,
        equity_curve: List[float],
        trades: List[float],
        initial_capital: float,
    ) -> Dict[str, float]:
        """Compute Sharpe, return, max_dd, win_rate from equity curve."""
        ec = np.array(equity_curve)
        if len(ec) < 2:
            return self._empty_stats()

        # ── Return ──
        total_return_pct = (ec[-1] - initial_capital) / initial_capital * 100

        # ── Sharpe (annualized, assume 5m bars → 105120 bars/year) ──
        rets = np.diff(ec) / ec[:-1]
        if len(rets) == 0 or rets.std() == 0:
            sharpe = 0.0
        else:
            bars_per_year = 105120  # 5m bars
            sharpe = float((rets.mean() / rets.std()) * np.sqrt(bars_per_year))
            sharpe = float(np.clip(sharpe, -10, 10))

        # ── Max Drawdown ──
        running_max = np.maximum.accumulate(ec)
        dd = (ec - running_max) / (running_max + 1e-10)
        max_dd_pct = float(abs(dd.min()) * 100)

        # ── Trade stats ──
        n_trades = len(trades)
        win_rate = float(np.mean([1 for t in trades if t > 0])) if trades else 0.0

        return {
            "sharpe":       sharpe,
            "return_pct":   total_return_pct,
            "max_dd_pct":   max_dd_pct,
            "n_trades":     n_trades,
            "win_rate":     win_rate,
        }

    def _empty_stats(self) -> Dict[str, float]:
        return {"sharpe": 0.0, "return_pct": 0.0, "max_dd_pct": 0.0,
                "n_trades": 0, "win_rate": 0.0}

    def _aggregate(self, folds: List[FoldResult]) -> WFOResult:
        """Aggregate fold results: vote on params, compute median OOS Sharpe."""
        if not folds:
            return WFOResult(
                folds=[], best_params={}, oos_sharpe_median=0.0,
                oos_sharpe_std=0.0, consistency_pct=0.0,
                total_oos_return=0.0, total_oos_trades=0, param_stability={}
            )

        oos_sharpes = [f.oos_sharpe for f in folds]

        # ── Vote: for each param key, which value won most folds ──
        param_votes: Dict[str, Dict[Any, int]] = {}
        for fold in folds:
            for k, v in fold.best_params.items():
                if k not in param_votes:
                    param_votes[k] = {}
                param_votes[k][v] = param_votes[k].get(v, 0) + 1

        best_params = {}
        param_stability = {}
        for k, votes in param_votes.items():
            winner = max(votes, key=votes.__getitem__)
            best_params[k] = winner
            total_votes = sum(votes.values())
            param_stability[k] = {
                "winner": winner,
                "consistency_pct": round(votes[winner] / total_votes * 100, 1),
                "votes": votes,
            }

        return WFOResult(
            folds              = folds,
            best_params        = best_params,
            oos_sharpe_median  = float(np.median(oos_sharpes)),
            oos_sharpe_std     = float(np.std(oos_sharpes)),
            consistency_pct    = float(np.mean([1 for s in oos_sharpes if s > 0]) * 100),
            total_oos_return   = float(sum(f.oos_return_pct for f in folds)),
            total_oos_trades   = int(sum(f.oos_n_trades for f in folds)),
            param_stability    = param_stability,
        )

    def _save(self, result: WFOResult, path: str):
        """Save result as JSON."""
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                json.dump(result.to_dict(), f, indent=2, default=str)
            print(f"[WFO] Result saved to: {path}")
        except Exception as e:
            print(f"[WFO] Save failed: {e}")


# ── Convenience function for loading best params back into config ────────────

def load_optimal_params(json_path: str) -> Optional[Dict[str, Any]]:
    """
    Load best params from a saved WFO result JSON.
    Returns None if file not found or invalid.

    Usage in main.py / config override:
        optimal = load_optimal_params("output/wfo_result.json")
        if optimal:
            import config
            config.ADX_TREND_MIN = optimal["ADX_TREND_MIN"]
            config.TREND_ATR_SL_MULT = optimal["TREND_ATR_SL_MULT"]
            ...
    """
    try:
        with open(json_path) as f:
            data = json.load(f)
        return data.get("best_params")
    except Exception:
        return None


def apply_optimal_params(json_path: str) -> bool:
    """
    Auto-apply WFO optimal params to config module at runtime.
    Returns True if params were applied, False otherwise.

    Call this near the top of main.py / run_live() before creating
    regime_detector, signal_engine, etc.
    """
    params = load_optimal_params(json_path)
    if not params:
        return False

    try:
        import config as cfg
        mapping = {
            "ADX_TREND_MIN":        "ADX_TREND_MIN",
            "TREND_ATR_SL_MULT":    "TREND_ATR_SL_MULT",
            "TREND_ATR_TP_MULT":    "TREND_ATR_TP_MULT",
            "RANGE_ATR_SL_MULT":    "RANGE_ATR_SL_MULT",
            "RANGE_ATR_TP_MULT":    "RANGE_ATR_TP_MULT",
            "FEE_MULTIPLIER":       "FEE_MULTIPLIER",
        }
        applied = []
        for wfo_key, cfg_key in mapping.items():
            if wfo_key in params and hasattr(cfg, cfg_key):
                old = getattr(cfg, cfg_key)
                setattr(cfg, cfg_key, params[wfo_key])
                applied.append(f"{cfg_key}: {old} → {params[wfo_key]}")

        if applied:
            print("[WFO] Applied optimal params:")
            for line in applied:
                print(f"   {line}")
        return True

    except Exception as e:
        print(f"[WFO] apply_optimal_params failed: {e}")
        return False


# ── CLI runner ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    """
    Quick test / standalone run.
    Usage:
        cd trading-engine
        python -m backtest.walk_forward_optimizer --fast
    """
    import argparse

    parser = argparse.ArgumentParser(description="Walk-Forward Parameter Optimizer")
    parser.add_argument("--fast",    action="store_true", help="Use reduced grid (faster)")
    parser.add_argument("--folds",   type=int, default=5,   help="Number of WFO folds")
    parser.add_argument("--capital", type=float, default=1000.0, help="Initial capital USD")
    parser.add_argument("--symbol",  type=str, default=None, help="Symbol override")
    parser.add_argument("--save",    type=str, default="output/wfo_result.json")
    args = parser.parse_args()

    print("[WFO] Loading historical data...")

    try:
        from data.fetcher import fetch_klines
        from core.features import calculate_features, get_regime_features
        from core.regime_detector import RegimeDetector

        symbol = args.symbol or __import__("config").SYMBOLS[0]
        raw_df = fetch_klines(symbol, "5m", lookback_days=180)
        feat_df = calculate_features(raw_df)
        regime_feat = get_regime_features(feat_df)

        # Attach regime predictions
        det = RegimeDetector()
        regimes = det.predict(regime_feat)
        feat_df["regime"] = regimes

        wfo = WalkForwardOptimizer(
            n_folds=args.folds,
            fast_mode=args.fast,
            verbose=True,
        )
        result = wfo.run(feat_df, initial_capital=args.capital, save_path=args.save)

    except ImportError as e:
        # Fallback demo with synthetic data
        print(f"[WFO] Data imports not available ({e}), running demo with synthetic data...")
        np.random.seed(42)
        n = 5000
        price = 50000.0 + np.cumsum(np.random.randn(n) * 50)
        atr   = np.abs(np.random.randn(n) * 200 + 500)
        adx   = np.abs(np.random.randn(n) * 5 + 22)
        regime = np.random.choice([0, 1, 2, 3], size=n, p=[0.35, 0.35, 0.15, 0.15])

        demo_df = pd.DataFrame({
            "close": price, "atr_14": atr, "adx": adx, "regime": regime
        })

        wfo = WalkForwardOptimizer(n_folds=3, fast_mode=True, verbose=True)
        result = wfo.run(demo_df, initial_capital=args.capital)
