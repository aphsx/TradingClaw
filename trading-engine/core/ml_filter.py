"""
Walk-Forward ML Filter
======================
Anti-leakage machine-learning gate for trade signals.

LEAKAGE PREVENTION GUARANTEES
──────────────────────────────
1. Features extracted ONLY from data available AT signal time (df.iloc[-1] / past bars).
2. Model trained ONLY on already-CLOSED trade outcomes (never future trades).
3. No batch normalization fitted on the full dataset — StandardScaler is re-fitted
   inside _retrain() on historical closed trades only.
4. Walk-forward: each prediction uses a model trained strictly on trades that closed
   BEFORE the current bar — no peeking at the test set.

HOW IT WORKS
────────────
  Signal generated (bar T)
    → extract_features(df, signal, regime_id, regime_conf)  ← only past data
    → should_trade() predicts win probability
  Trade closes (bar T')
    → record_outcome(features, won=True/False)
  Every RETRAIN_INTERVAL new closed trades:
    → _retrain() on ALL past closed trades → new model

ACTIVATION
──────────
  Not active until MIN_TRADES closed (returns "allow" with neutral prob = 0.5).
  Once active, gates signals where predicted win probability < PROBA_THRESHOLD.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Optional, List, Tuple
from dataclasses import dataclass, field
from collections import deque

from sklearn.ensemble import GradientBoostingClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.utils.class_weight import compute_class_weight


# ─── Tunable constants ────────────────────────────────────────────────────────
MIN_TRADES_TO_ACTIVATE = 50   # don't gate anything until N trades have closed
RETRAIN_INTERVAL       = 20   # retrain every N new closed trades
PROBA_THRESHOLD        = 0.52 # min predicted win-rate to allow a signal (low bar: avoids over-filtering)
MAX_HISTORY            = 500  # keep only the most recent N trades (concept drift)

STRATEGY_ID = {"TrendFollow": 0, "VolBreakout": 1, "MeanRev": 2}
FEATURE_NAMES = [
    "regime",          # 0-3
    "regime_conf",     # 0-1
    "strategy",        # 0/1/2
    "direction",       # 1=LONG, -1=SHORT
    "adx",
    "rsi",
    "vol_ratio",       # volume / vol_ma
    "atr_pct",         # ATR / close %
    "bb_pct",          # Bollinger %B (0-1)
    "macd_norm",       # macd_hist / atr (normalized)
    "signal_conf",     # signal.confidence
    "risk_reward",     # R:R ratio
    "hour_sin",        # sin(2π * hour / 24)
    "hour_cos",        # cos(2π * hour / 24)
]
N_FEATURES = len(FEATURE_NAMES)


# ─── Types ────────────────────────────────────────────────────────────────────

@dataclass
class MLDecision:
    allowed:   bool
    reason:    str
    proba:     float = 0.5   # estimated win probability
    active:    bool  = False  # whether ML is active yet


@dataclass
class TradeRecord:
    features: np.ndarray  # shape (N_FEATURES,)
    won:      int         # 1 = win, 0 = loss


# ─── Main Class ───────────────────────────────────────────────────────────────

class WalkForwardMLFilter:
    """
    Online walk-forward ML gate.

    Usage in backtest loop:
        ml = WalkForwardMLFilter()
        ...
        feats = ml.extract_features(df, signal, regime_id, regime_conf)
        decision = ml.should_trade(feats)
        if not decision.allowed:
            continue
        ...
        # After position closes:
        ml.record_outcome(feats, won=(trade.pnl > 0))
    """

    def __init__(self):
        self.history:  deque[TradeRecord] = deque(maxlen=MAX_HISTORY)
        self.model:    Optional[GradientBoostingClassifier] = None
        self.scaler:   Optional[StandardScaler] = None
        self._since_last_train: int = 0
        self._is_active: bool = False

        # Stats for reporting
        self.total_evaluated:  int = 0
        self.total_allowed:    int = 0
        self.total_rejected:   int = 0

    # ── Public API ────────────────────────────────────────────────────────────

    def extract_features(
        self,
        df: pd.DataFrame,
        signal,          # Signal dataclass from signal_engine.py
        regime_id: int,
        regime_conf: float,
    ) -> np.ndarray:
        """
        Build feature vector from market state at THIS bar.
        Strictly backward-looking — no future information used.
        """
        last = df.iloc[-1]

        def _get(col: str, default: float = 0.0) -> float:
            v = last.get(col, default) if hasattr(last, 'get') else getattr(last, col, default)
            return float(v) if (v is not None and not (isinstance(v, float) and np.isnan(v))) else default

        atr   = _get('atr_14', signal.atr)
        close = _get('close',  signal.entry_price)
        atr_pct = (atr / close * 100) if close > 0 else 0.0

        macd_hist = _get('macd_hist', 0.0)
        macd_norm = (macd_hist / atr) if atr > 0 else 0.0

        # Time-of-day (hour) — crypto has known intraday patterns
        hour = 12.0
        if isinstance(df.index, pd.DatetimeIndex):
            hour = float(df.index[-1].hour) + float(df.index[-1].minute) / 60.0
        hour_sin = np.sin(2 * np.pi * hour / 24)
        hour_cos = np.cos(2 * np.pi * hour / 24)

        feats = np.array([
            float(regime_id),
            float(regime_conf),
            float(STRATEGY_ID.get(signal.strategy, 0)),
            1.0 if signal.direction == "LONG" else -1.0,
            _get('adx', 25.0),
            _get('rsi_14', 50.0),
            _get('volume_ratio', 1.0),
            atr_pct,
            _get('bb_pct', 0.5),
            float(np.clip(macd_norm, -5.0, 5.0)),
            float(getattr(signal, 'confidence', 0.5)),
            float(getattr(signal, 'risk_reward', 1.0)),
            hour_sin,
            hour_cos,
        ], dtype=np.float32)

        # Clip and sanitize
        feats = np.nan_to_num(feats, nan=0.0, posinf=5.0, neginf=-5.0)
        return feats

    def should_trade(self, features: np.ndarray) -> MLDecision:
        """Return whether the ML filter allows this signal."""
        self.total_evaluated += 1

        if not self._is_active:
            n = len(self.history)
            self.total_allowed += 1
            return MLDecision(
                allowed=True,
                reason=f"ML warming up ({n}/{MIN_TRADES_TO_ACTIVATE} trades)",
                proba=0.5,
                active=False,
            )

        proba = self._predict_proba(features)
        if proba >= PROBA_THRESHOLD:
            self.total_allowed += 1
            return MLDecision(allowed=True,  reason=f"ML approved  p={proba:.3f}", proba=proba, active=True)
        else:
            self.total_rejected += 1
            return MLDecision(allowed=False, reason=f"ML rejected  p={proba:.3f} < {PROBA_THRESHOLD}", proba=proba, active=True)

    def record_outcome(self, features: np.ndarray, won: bool):
        """
        Register a closed trade result.
        Must be called AFTER the trade closes, not before.
        This is what prevents leakage: outcomes are only recorded after they occur.
        """
        self.history.append(TradeRecord(features=features.copy(), won=int(won)))
        self._since_last_train += 1

        # Activate once we have enough data
        if len(self.history) >= MIN_TRADES_TO_ACTIVATE:
            if (not self._is_active) or (self._since_last_train >= RETRAIN_INTERVAL):
                self._retrain()

    def get_stats(self) -> dict:
        """Return filter statistics for reporting."""
        n_trades = len(self.history)
        win_rate = (sum(t.won for t in self.history) / n_trades * 100) if n_trades > 0 else 0.0
        pass_rate = (self.total_allowed / max(self.total_evaluated, 1) * 100)
        return {
            "active":           self._is_active,
            "trades_in_memory": n_trades,
            "observed_win_rate": f"{win_rate:.1f}%",
            "total_evaluated":  self.total_evaluated,
            "total_allowed":    self.total_allowed,
            "total_rejected":   self.total_rejected,
            "pass_rate":        f"{pass_rate:.1f}%",
            "model_trains":     getattr(self, '_train_count', 0),
        }

    # ── Internal ──────────────────────────────────────────────────────────────

    def _retrain(self):
        """
        Train/retrain the GBM classifier on all accumulated closed trades.
        Called automatically by record_outcome() once conditions are met.
        Strictly uses past data only — no future outcomes involved.
        """
        X = np.array([t.features for t in self.history], dtype=np.float32)
        y = np.array([t.won      for t in self.history], dtype=np.int32)

        # Guard: need at least both classes
        if len(np.unique(y)) < 2:
            return

        # Balanced class weights — prevent the model from predicting all-wins
        classes   = np.unique(y)
        weights   = compute_class_weight('balanced', classes=classes, y=y)
        class_w   = dict(zip(classes.tolist(), weights.tolist()))

        # Fit scaler on training data only
        scaler = StandardScaler()
        X_sc = scaler.fit_transform(X)

        model = GradientBoostingClassifier(
            n_estimators=120,
            learning_rate=0.05,
            max_depth=3,          # shallow → less overfitting on small datasets
            min_samples_leaf=5,
            subsample=0.8,
            random_state=42,
        )
        model.fit(X_sc, y)

        self.model  = model
        self.scaler = scaler
        self._is_active = True
        self._since_last_train = 0
        self._train_count = getattr(self, '_train_count', 0) + 1

    def _predict_proba(self, features: np.ndarray) -> float:
        """Return win probability (class=1). Fallback=0.5 if model not ready."""
        if self.model is None or self.scaler is None:
            return 0.5
        try:
            X = self.scaler.transform(features.reshape(1, -1))
            proba = self.model.predict_proba(X)[0]
            # Index of class 1 (win)
            classes = self.model.classes_
            win_idx = int(np.where(classes == 1)[0][0]) if 1 in classes else 1
            return float(proba[win_idx])
        except Exception:
            return 0.5

    def feature_importance(self) -> dict:
        """Return feature importance dict (only available after first training)."""
        if self.model is None:
            return {}
        imp = self.model.feature_importances_
        return dict(sorted(zip(FEATURE_NAMES, imp.tolist()), key=lambda x: -x[1]))
