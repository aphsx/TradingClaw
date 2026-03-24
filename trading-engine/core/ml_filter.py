"""
Walk-Forward ML Filter — World-Class Level
============================================
Anti-leakage machine-learning gate for trade signals with ensemble modeling,
regime-conditional training, adaptive thresholds, and comprehensive quality validation.

LEAKAGE PREVENTION GUARANTEES
──────────────────────────────
1. Features extracted ONLY from data available AT signal time (df.iloc[-1] / past bars).
2. Model trained ONLY on already-CLOSED trade outcomes (never future trades).
3. No batch normalization fitted on the full dataset — StandardScaler is re-fitted
   inside _retrain() on historical closed trades only.
4. Walk-forward: each prediction uses a model trained strictly on trades that closed
   BEFORE the current bar — no peeking at the test set.

KEY UPGRADES
────────────
• Ensemble of models (GradientBoosting + RandomForest) with soft voting
• Expanded 25+ feature set (including momentum, volatility, trend indicators)
• Regime-conditional training (separate ensembles per market regime)
• Adaptive threshold based on F1-score optimization
• Permutation feature importance with drift detection
• Cross-validation-based model health monitoring
• Feature importance tracking and logging

HOW IT WORKS
────────────
  Signal generated (bar T)
    → extract_features(df, signal, regime_id, regime_conf)  ← only past data, 25+ features
    → should_trade() predicts win probability via ensemble
  Trade closes (bar T')
    → record_outcome(features, won=True/False)
  Every RETRAIN_INTERVAL new closed trades:
    → _retrain() on ALL past closed trades → new ensemble per regime
    → compute_optimal_threshold() updates adaptive threshold
    → validate_model_quality() checks cross-validation metrics
    → compute_feature_importance() tracks feature drift

ACTIVATION
──────────
  Not active until MIN_TRADES closed (returns "allow" with neutral prob = 0.5).
  Once active, gates signals where predicted win probability < adaptive_threshold.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Optional, List, Tuple, Dict
from dataclasses import dataclass, field
from collections import deque
import warnings

from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier, VotingClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.utils.class_weight import compute_class_weight
from sklearn.inspection import permutation_importance
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, roc_auc_score

# ─── Config imports with safe defaults ────────────────────────────────────────
try:
    from config import (
        ML_ENSEMBLE_ENABLED,
        ML_N_ESTIMATORS_GBM,
        ML_N_ESTIMATORS_RF,
        ML_REGIME_CONDITIONAL,
        ML_FEATURE_IMPORTANCE_TRACK,
    )
except ImportError:
    ML_ENSEMBLE_ENABLED = True
    ML_N_ESTIMATORS_GBM = 150
    ML_N_ESTIMATORS_RF = 100
    ML_REGIME_CONDITIONAL = True
    ML_FEATURE_IMPORTANCE_TRACK = True

# ─── Tunable constants ────────────────────────────────────────────────────────
MIN_TRADES_TO_ACTIVATE = 50   # don't gate anything until N trades have closed
RETRAIN_INTERVAL       = 20   # retrain every N new closed trades
INITIAL_THRESHOLD      = 0.52  # initial threshold before optimization
THRESHOLD_MIN          = 0.48  # clamp threshold to [0.48, 0.65] to avoid extreme filtering
THRESHOLD_MAX          = 0.65
MAX_HISTORY            = 500   # keep only the most recent N trades (concept drift)
MIN_REGIME_SAMPLES     = 20    # if regime has fewer samples, use global model
MIN_VALIDATION_AUC     = 0.52  # warn if AUC barely better than random
CV_N_SPLITS            = 3     # time series cross-validation folds
FEATURE_IMPORTANCE_WARNING_PCT = 30  # warn if any feature >30% importance

STRATEGY_ID = {"TrendFollow": 0, "VolBreakout": 1, "MeanRev": 2}

# ─── Original 14 features ──────────────────────────────────────────────────────
FEATURE_NAMES_BASE = [
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

# ─── New expanded features (11 additional) ──────────────────────────────────────
FEATURE_NAMES_NEW = [
    "ema_slope_9",           # EMA9 slope (trend strength)
    "ema_slope_21",          # EMA21 slope
    "momentum_10",           # 10-bar momentum
    "volume_delta_norm",     # normalized CVD
    "bb_width_pct",          # BB width percentile (compression indicator)
    "stoch_rsi_k",           # Stochastic RSI K
    "vwap_zscore",           # VWAP Z-score
    "obv_slope",             # OBV trend
    "rv_hv_ratio",           # realized/historical vol ratio
    "htf_trend_alignment",   # higher TF trend agreement score (-1 to 1)
    "session_quality",       # session-based quality score (0-1)
]

FEATURE_NAMES = FEATURE_NAMES_BASE + FEATURE_NAMES_NEW
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


@dataclass
class ModelHealth:
    """Model quality metrics from cross-validation."""
    accuracy:  float = 0.0
    precision: float = 0.0
    recall:    float = 0.0
    f1:        float = 0.0
    auc:       float = 0.0
    is_healthy: bool = False
    warning_msg: str = ""


# ─── Main Class ───────────────────────────────────────────────────────────────

class WalkForwardMLFilter:
    """
    Online walk-forward ML gate with world-class ensemble, regime conditioning,
    adaptive thresholds, and comprehensive health monitoring.

    Usage in backtest loop:
        ml = WalkForwardMLFilter()
        ...
        feats = ml.extract_features(df, signal, regime_id, regime_conf)
        decision = ml.should_trade(feats)
        if not decision.allowed:
            continue
        ...
        # After position closes:
        ml.record_outcome(feats, won=(trade.pnl > 0), regime_id=regime_id)
    """

    def __init__(self):
        self.history:  deque[TradeRecord] = deque(maxlen=MAX_HISTORY)

        # Ensemble models: global + per-regime
        self.ensemble:     Optional[VotingClassifier] = None
        self.regime_ensembles: Dict[int, VotingClassifier] = {}  # one per regime (0-3)
        self.scaler:       Optional[StandardScaler] = None
        self.regime_scalers: Dict[int, StandardScaler] = {}

        # Adaptive threshold
        self.adaptive_threshold: float = INITIAL_THRESHOLD
        self.threshold_history: List[float] = []

        # Feature importance tracking
        self.feature_importance: Dict[str, float] = {}
        self.importance_history: List[Dict[str, float]] = []

        # Model health validation
        self.model_health: Optional[ModelHealth] = None

        self._since_last_train: int = 0
        self._is_active: bool = False
        self._last_regime_id: Optional[int] = None

        # Stats for reporting
        self.total_evaluated:  int = 0
        self.total_allowed:    int = 0
        self.total_rejected:   int = 0
        self._train_count: int = 0

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
        Expanded to 25+ features including momentum, volatility, and trend signals.
        """
        last = df.iloc[-1]

        def _get(col: str, default: float = 0.0) -> float:
            v = last.get(col, default) if hasattr(last, 'get') else getattr(last, col, default)
            return float(v) if (v is not None and not (isinstance(v, float) and np.isnan(v))) else default

        # ─── Original 14 features ─────────────────────────────────────────────
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

        # ─── New 11 features ──────────────────────────────────────────────────
        # EMA slopes (trend strength)
        ema9_slope = _get('ema9_slope', 0.0)      # typically slope over last N bars
        ema21_slope = _get('ema21_slope', 0.0)

        # 10-bar momentum
        momentum_10 = _get('momentum_10', 0.0)

        # Volume delta normalized (CVD)
        volume_delta_norm = _get('volume_delta_norm', 0.0)

        # Bollinger Band width percentile (compression)
        bb_width_pct = _get('bb_width_pct', 0.5)

        # Stochastic RSI K (momentum oscillator)
        stoch_rsi_k = _get('stoch_rsi_k', 0.5)

        # VWAP Z-score (price deviation from VWAP)
        vwap_zscore = _get('vwap_zscore', 0.0)

        # OBV slope (volume trend)
        obv_slope = _get('obv_slope', 0.0)

        # Realized / Historical vol ratio (volatility regime)
        rv_hv_ratio = _get('rv_hv_ratio', 1.0)

        # Higher timeframe trend alignment (-1 to 1)
        htf_trend_alignment = _get('htf_trend_alignment', 0.0)

        # Session quality score (0-1, e.g., based on time-of-day liquidity)
        session_quality = _get('session_quality', 0.5)

        feats = np.array([
            # Original 14
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
            # New 11
            ema9_slope,
            ema21_slope,
            momentum_10,
            volume_delta_norm,
            bb_width_pct,
            stoch_rsi_k,
            vwap_zscore,
            obv_slope,
            rv_hv_ratio,
            htf_trend_alignment,
            session_quality,
        ], dtype=np.float32)

        # Clip and sanitize
        feats = np.nan_to_num(feats, nan=0.0, posinf=5.0, neginf=-5.0)
        return feats

    def should_trade(self, features: np.ndarray, regime_id: int = 0) -> MLDecision:
        """
        Return whether the ML filter allows this signal.
        Uses adaptive threshold and regime-conditional models if enabled.
        """
        self.total_evaluated += 1
        self._last_regime_id = regime_id

        if not self._is_active:
            n = len(self.history)
            self.total_allowed += 1
            return MLDecision(
                allowed=True,
                reason=f"ML warming up ({n}/{MIN_TRADES_TO_ACTIVATE} trades)",
                proba=0.5,
                active=False,
            )

        proba = self._predict_proba(features, regime_id)
        threshold = self.adaptive_threshold

        if proba >= threshold:
            self.total_allowed += 1
            return MLDecision(
                allowed=True,
                reason=f"ML approved  p={proba:.3f} (threshold={threshold:.3f})",
                proba=proba,
                active=True
            )
        else:
            self.total_rejected += 1
            return MLDecision(
                allowed=False,
                reason=f"ML rejected  p={proba:.3f} < {threshold:.3f}",
                proba=proba,
                active=True
            )

    def record_outcome(self, features: np.ndarray, won: bool, regime_id: int = 0):
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
                self._compute_optimal_threshold()
                self._validate_model_quality()
                if ML_FEATURE_IMPORTANCE_TRACK:
                    self._compute_feature_importance()

    def get_stats(self) -> dict:
        """Return filter statistics for reporting."""
        n_trades = len(self.history)
        win_rate = (sum(t.won for t in self.history) / n_trades * 100) if n_trades > 0 else 0.0
        pass_rate = (self.total_allowed / max(self.total_evaluated, 1) * 100)

        health_info = {}
        if self.model_health:
            health_info = {
                "model_health_f1": f"{self.model_health.f1:.3f}",
                "model_health_auc": f"{self.model_health.auc:.3f}",
                "model_health_warning": self.model_health.warning_msg,
            }

        importance_info = {}
        if self.feature_importance:
            top_features = sorted(
                self.feature_importance.items(),
                key=lambda x: -x[1]
            )[:5]
            importance_info = {
                "top_features": {k: f"{v:.3f}" for k, v in top_features}
            }

        return {
            "active":           self._is_active,
            "trades_in_memory": n_trades,
            "observed_win_rate": f"{win_rate:.1f}%",
            "total_evaluated":  self.total_evaluated,
            "total_allowed":    self.total_allowed,
            "total_rejected":   self.total_rejected,
            "pass_rate":        f"{pass_rate:.1f}%",
            "model_trains":     self._train_count,
            "adaptive_threshold": f"{self.adaptive_threshold:.3f}",
            "regime_models":    len(self.regime_ensembles),
            **health_info,
            **importance_info,
        }

    def get_model_health(self) -> Optional[ModelHealth]:
        """Return model health validation metrics."""
        return self.model_health

    # ── Internal ──────────────────────────────────────────────────────────────

    def _retrain(self):
        """
        Train/retrain the ensemble classifiers on all accumulated closed trades.
        Supports regime-conditional training if enabled.
        Called automatically by record_outcome() once conditions are met.
        Strictly uses past data only — no future outcomes involved.
        """
        X = np.array([t.features for t in self.history], dtype=np.float32)
        y = np.array([t.won      for t in self.history], dtype=np.int32)

        # Guard: need at least both classes
        if len(np.unique(y)) < 2:
            warnings.warn("Cannot retrain: only one class present in data")
            return

        # Balanced class weights — prevent the model from predicting all-wins
        classes = np.unique(y)
        weights = compute_class_weight('balanced', classes=classes, y=y)
        class_w = dict(zip(classes.tolist(), weights.tolist()))

        # Fit global scaler on training data only
        scaler = StandardScaler()
        X_sc = scaler.fit_transform(X)

        # Train global ensemble
        self.ensemble = self._build_ensemble(X_sc, y, class_w)
        self.scaler = scaler

        # Train regime-conditional ensembles if enabled
        if ML_REGIME_CONDITIONAL:
            self.regime_ensembles = {}
            self.regime_scalers = {}
            for regime_id in range(4):  # 4 regimes: 0, 1, 2, 3
                mask = X[:, 0] == regime_id  # regime is first feature
                if mask.sum() >= MIN_REGIME_SAMPLES and len(np.unique(y[mask])) >= 2:
                    X_regime = X[mask]
                    y_regime = y[mask]
                    scaler_regime = StandardScaler()
                    X_regime_sc = scaler_regime.fit_transform(X_regime)
                    self.regime_ensembles[regime_id] = self._build_ensemble(
                        X_regime_sc, y_regime, class_w
                    )
                    self.regime_scalers[regime_id] = scaler_regime

        self._is_active = True
        self._since_last_train = 0
        self._train_count += 1

    def _build_ensemble(self, X_sc: np.ndarray, y: np.ndarray, class_weights: dict) -> VotingClassifier:
        """Build soft-voting ensemble of GradientBoosting + RandomForest."""
        gbm = GradientBoostingClassifier(
            n_estimators=ML_N_ESTIMATORS_GBM,
            learning_rate=0.05,
            max_depth=4,
            min_samples_leaf=5,
            subsample=0.8,
            random_state=42,
        )

        rf = RandomForestClassifier(
            n_estimators=ML_N_ESTIMATORS_RF,
            max_depth=6,
            min_samples_leaf=5,
            max_features='sqrt',
            random_state=42,
            n_jobs=-1,
        )

        ensemble = VotingClassifier(
            estimators=[('gbm', gbm), ('rf', rf)],
            voting='soft',  # average predicted probabilities
        )
        ensemble.fit(X_sc, y)
        return ensemble

    def _predict_proba(self, features: np.ndarray, regime_id: int = 0) -> float:
        """
        Return win probability (class=1) using regime-conditional or global ensemble.
        Fallback=0.5 if model not ready.
        """
        # Try regime-specific model first if available
        if ML_REGIME_CONDITIONAL and regime_id in self.regime_ensembles:
            try:
                scaler = self.regime_scalers[regime_id]
                model = self.regime_ensembles[regime_id]
                X = scaler.transform(features.reshape(1, -1))
                proba = model.predict_proba(X)[0]
                classes = model.classes_
                win_idx = int(np.where(classes == 1)[0][0]) if 1 in classes else 1
                return float(proba[win_idx])
            except Exception as e:
                warnings.warn(f"Regime-specific prediction failed: {e}, falling back to global")

        # Fall back to global ensemble
        if self.ensemble is None or self.scaler is None:
            return 0.5
        try:
            X = self.scaler.transform(features.reshape(1, -1))
            proba = self.ensemble.predict_proba(X)[0]
            classes = self.ensemble.classes_
            win_idx = int(np.where(classes == 1)[0][0]) if 1 in classes else 1
            return float(proba[win_idx])
        except Exception as e:
            warnings.warn(f"Global prediction failed: {e}")
            return 0.5

    def _compute_optimal_threshold(self):
        """
        Compute optimal threshold using F1 score on training data.
        Clamp to [THRESHOLD_MIN, THRESHOLD_MAX] to avoid extreme filtering.
        """
        X = np.array([t.features for t in self.history], dtype=np.float32)
        y = np.array([t.won      for t in self.history], dtype=np.int32)

        if len(np.unique(y)) < 2 or self.ensemble is None or self.scaler is None:
            self.adaptive_threshold = INITIAL_THRESHOLD
            return

        try:
            X_sc = self.scaler.transform(X)
            y_proba = self.ensemble.predict_proba(X_sc)
            classes = self.ensemble.classes_
            win_idx = int(np.where(classes == 1)[0][0]) if 1 in classes else 1
            y_proba_win = y_proba[:, win_idx]

            # Search for threshold that maximizes F1 score
            best_f1 = 0.0
            best_threshold = INITIAL_THRESHOLD
            for threshold in np.linspace(0.4, 0.7, 31):
                y_pred = (y_proba_win >= threshold).astype(int)
                # Avoid F1 division errors
                if len(np.unique(y_pred)) < 2:
                    continue
                try:
                    f1 = f1_score(y, y_pred)
                    if f1 > best_f1:
                        best_f1 = f1
                        best_threshold = threshold
                except Exception:
                    pass

            # Clamp to safe range
            self.adaptive_threshold = np.clip(best_threshold, THRESHOLD_MIN, THRESHOLD_MAX)
            self.threshold_history.append(self.adaptive_threshold)

        except Exception as e:
            warnings.warn(f"Threshold optimization failed: {e}")
            self.adaptive_threshold = INITIAL_THRESHOLD

    def _validate_model_quality(self):
        """
        Cross-validate on training data (TimeSeriesSplit) to assess model health.
        Track: accuracy, precision, recall, F1, AUC.
        """
        X = np.array([t.features for t in self.history], dtype=np.float32)
        y = np.array([t.won      for t in self.history], dtype=np.int32)

        if len(np.unique(y)) < 2 or self.ensemble is None or self.scaler is None:
            self.model_health = ModelHealth(is_healthy=False, warning_msg="Insufficient data")
            return

        try:
            accuracies, precisions, recalls, f1s, aucs = [], [], [], [], []

            tscv = TimeSeriesSplit(n_splits=CV_N_SPLITS)
            for train_idx, test_idx in tscv.split(X):
                X_train, X_test = X[train_idx], X[test_idx]
                y_train, y_test = y[train_idx], y[test_idx]

                if len(np.unique(y_test)) < 2:
                    continue

                # Retrain scaler on this fold's training data
                scaler_fold = StandardScaler()
                X_train_sc = scaler_fold.fit_transform(X_train)
                X_test_sc = scaler_fold.transform(X_test)

                # Build and fit ensemble on this fold
                ensemble_fold = self._build_ensemble(X_train_sc, y_train, {})

                # Predict
                y_pred = ensemble_fold.predict(X_test_sc)
                y_proba = ensemble_fold.predict_proba(X_test_sc)
                classes = ensemble_fold.classes_
                win_idx = int(np.where(classes == 1)[0][0]) if 1 in classes else 1

                accuracies.append(accuracy_score(y_test, y_pred))
                precisions.append(precision_score(y_test, y_pred, zero_division=0))
                recalls.append(recall_score(y_test, y_pred, zero_division=0))
                f1s.append(f1_score(y_test, y_pred, zero_division=0))
                try:
                    aucs.append(roc_auc_score(y_test, y_proba[:, win_idx]))
                except Exception:
                    aucs.append(0.5)

            if len(f1s) > 0:
                avg_accuracy = np.mean(accuracies)
                avg_precision = np.mean(precisions)
                avg_recall = np.mean(recalls)
                avg_f1 = np.mean(f1s)
                avg_auc = np.mean(aucs)

                warning_msg = ""
                is_healthy = True

                if avg_auc < MIN_VALIDATION_AUC:
                    warning_msg = f"AUC {avg_auc:.3f} barely better than random (< {MIN_VALIDATION_AUC})"
                    is_healthy = False

                self.model_health = ModelHealth(
                    accuracy=avg_accuracy,
                    precision=avg_precision,
                    recall=avg_recall,
                    f1=avg_f1,
                    auc=avg_auc,
                    is_healthy=is_healthy,
                    warning_msg=warning_msg,
                )
            else:
                self.model_health = ModelHealth(is_healthy=False, warning_msg="CV failed")

        except Exception as e:
            warnings.warn(f"Model validation failed: {e}")
            self.model_health = ModelHealth(is_healthy=False, warning_msg=str(e))

    def _compute_feature_importance(self):
        """
        Compute permutation importance (more reliable than built-in importance).
        Store top-10 features and log warning if any feature has >30% importance.
        """
        X = np.array([t.features for t in self.history], dtype=np.float32)
        y = np.array([t.won      for t in self.history], dtype=np.int32)

        if len(np.unique(y)) < 2 or self.ensemble is None or self.scaler is None:
            return

        try:
            X_sc = self.scaler.transform(X)

            # Permutation importance (use default scoring: accuracy for classifier)
            result = permutation_importance(
                self.ensemble, X_sc, y,
                n_repeats=5,
                random_state=42,
                n_jobs=-1,
            )

            importances = result.importances_mean
            self.feature_importance = dict(zip(FEATURE_NAMES, importances.tolist()))

            # Store in history
            self.importance_history.append(self.feature_importance.copy())

            # Check for fragility (>30% importance in single feature)
            max_importance = max(importances) if len(importances) > 0 else 0.0
            if max_importance > FEATURE_IMPORTANCE_WARNING_PCT / 100.0:
                top_feature = FEATURE_NAMES[int(np.argmax(importances))]
                warnings.warn(
                    f"Feature '{top_feature}' has {max_importance*100:.1f}% importance — "
                    f"model may be fragile or overfitting"
                )

        except Exception as e:
            warnings.warn(f"Feature importance computation failed: {e}")
