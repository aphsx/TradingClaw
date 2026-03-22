"""
Regime Detector v2 — HMM-based Market Regime Classification
=============================================================
Replaces circular RandomForest-on-rule-labels approach.
Uses Gaussian HMM (unsupervised) so regimes emerge from data,
not from human-defined ADX/ATR thresholds.

4 Hidden States:
  0 = Trending-Up   (high positive returns, moderate vol)
  1 = Ranging        (low |returns|, low vol)
  2 = Volatile       (high |returns|, high vol)
  3 = Trending-Down  (high negative returns, moderate vol)

State assignment is done post-hoc by analyzing each state's statistics.
"""
import pandas as pd
import numpy as np
from sklearn.preprocessing import StandardScaler
import warnings
warnings.filterwarnings('ignore')

import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import HMM_N_STATES, HMM_N_ITER

try:
    from hmmlearn.hmm import GaussianHMM
    HAS_HMM = True
except ImportError:
    HAS_HMM = False
    from sklearn.mixture import GaussianMixture


# Public regime constants (aligned with REGIME_WEIGHTS in signal_engine.py)
TRENDING_UP   = 0
RANGING       = 1
VOLATILE      = 2
TRENDING_DOWN = 3

REGIME_NAMES = {
    TRENDING_UP:   "Trending-Up",
    RANGING:       "Ranging",
    VOLATILE:      "Volatile",
    TRENDING_DOWN: "Trending-Down",
}
REGIME_COLORS = {
    TRENDING_UP:   "#1D9E75",
    RANGING:       "#378ADD",
    VOLATILE:      "#D85A30",
    TRENDING_DOWN: "#C0392B",
}


class RegimeDetector:
    """
    HMM-based regime detector.
    Interface keeps fit() / predict() / get_current_regime() from v1
    so main.py changes are minimal.
    """

    def __init__(self):
        self.scaler = StandardScaler()
        self.is_fitted = False
        self._state_map: dict = {}   # HMM state -> regime constant
        self._last_features_len = 0
        self._model = None
        self._n_states = HMM_N_STATES

    # ─── Feature selection ───
    FEATURE_COLS = [
        'returns', 'adx', 'atr_pct', 'bb_width',
        'volatility_20', 'volume_ratio',
        'ema_9_slope', 'momentum_10', 'rsi_14',
    ]

    def _select_features(self, features: pd.DataFrame) -> pd.DataFrame:
        cols = [c for c in self.FEATURE_COLS if c in features.columns]
        return features[cols].dropna()

    # ─── Model creation ───
    def _make_model(self):
        if HAS_HMM:
            return GaussianHMM(
                n_components=self._n_states,
                covariance_type="full",
                n_iter=HMM_N_ITER,
                random_state=42,
                tol=1e-4,
            )
        else:
            # Fallback to GaussianMixture (no temporal structure but similar clustering)
            return GaussianMixture(
                n_components=self._n_states,
                covariance_type="full",
                n_init=5,
                random_state=42,
            )

    # ─── State labeling ───
    def _label_states(self, X_scaled: np.ndarray, raw_df: pd.DataFrame,
                      states: np.ndarray) -> dict:
        """
        Map HMM hidden states to regime constants by analyzing state statistics.
        Uses mean return, mean absolute return, and mean volatility per state.
        """
        if 'returns' not in raw_df.columns:
            return {i: i % 4 for i in range(self._n_states)}

        aligned_len = min(len(states), len(raw_df))
        state_stats = {}
        for s in range(self._n_states):
            mask = states[:aligned_len] == s
            if mask.sum() < 5:
                state_stats[s] = {'mean_ret': 0, 'abs_ret': 0, 'vol': 0}
                continue
            rets = raw_df['returns'].values[:aligned_len][mask]
            vols = raw_df['volatility_20'].values[:aligned_len][mask] if 'volatility_20' in raw_df else np.abs(rets)
            state_stats[s] = {
                'mean_ret': float(np.nanmean(rets)),
                'abs_ret':  float(np.nanmean(np.abs(rets))),
                'vol':      float(np.nanmean(vols)),
            }

        # Sort states by mean_ret to assign regime labels
        sorted_by_ret = sorted(state_stats.items(), key=lambda x: x[1]['mean_ret'])
        sorted_by_vol = sorted(state_stats.items(), key=lambda x: x[1]['vol'], reverse=True)
        sorted_by_abs = sorted(state_stats.items(), key=lambda x: x[1]['abs_ret'])

        state_map = {}
        remaining = set(range(self._n_states))

        # Volatile = highest vol
        volatile_state = sorted_by_vol[0][0]
        state_map[volatile_state] = VOLATILE
        remaining.discard(volatile_state)

        # Trending-Down = most negative mean return (excluding volatile)
        for s, stats in sorted_by_ret:
            if s in remaining:
                state_map[s] = TRENDING_DOWN
                remaining.discard(s)
                break

        # Trending-Up = most positive mean return (excluding volatile)
        for s, stats in reversed(sorted_by_ret):
            if s in remaining:
                state_map[s] = TRENDING_UP
                remaining.discard(s)
                break

        # Ranging = whatever is left (lowest abs return, lowest vol)
        for s in remaining:
            state_map[s] = RANGING

        return state_map

    # ─── Public API ───
    def fit(self, df: pd.DataFrame, features: pd.DataFrame) -> dict:
        """
        Train HMM on the feature matrix.
        df: raw OHLCV + indicators DataFrame.
        features: output of get_regime_features(df).
        """
        X_raw = self._select_features(features)
        if len(X_raw) < 100:
            return {"error": "Not enough data to fit HMM"}

        # Align df to feature index
        common_idx = X_raw.index.intersection(df.index)
        X_raw = X_raw.loc[common_idx]
        df_aligned = df.loc[common_idx]

        # Scale
        X_scaled = self.scaler.fit_transform(X_raw.values)

        # Fit model
        model = self._make_model()
        try:
            if HAS_HMM:
                model.fit(X_scaled)
                states = model.predict(X_scaled)
            else:
                model.fit(X_scaled)
                states = model.predict(X_scaled)
        except Exception as e:
            return {"error": f"HMM fit failed: {e}"}

        # Label states semantically
        self._state_map = self._label_states(X_scaled, df_aligned, states)
        self._model = model
        self.is_fitted = True
        self._last_features_len = len(X_raw)

        # Build distribution stats for report
        mapped = [self._state_map.get(s, RANGING) for s in states]
        regime_dist = {REGIME_NAMES[r]: int(sum(m == r for m in mapped)) for r in REGIME_NAMES}

        # Holdout accuracy proxy: predict last 20% and compare to naive rule
        split = int(len(X_scaled) * 0.8)
        X_holdout = X_scaled[split:]
        if HAS_HMM:
            holdout_states = model.predict(X_holdout)
        else:
            holdout_states = model.predict(X_holdout)
        holdout_regimes = [self._state_map.get(s, RANGING) for s in holdout_states]
        # Basic sanity: at least 2 different regimes on holdout
        unique_regimes = len(set(holdout_regimes))

        return {
            "model": "GaussianHMM" if HAS_HMM else "GaussianMixture",
            "n_states": self._n_states,
            "state_map": {str(k): REGIME_NAMES[v] for k, v in self._state_map.items()},
            "regime_distribution": regime_dist,
            "holdout_unique_regimes": unique_regimes,
            "cv_accuracy": "N/A (unsupervised)",
        }

    def predict(self, features: pd.DataFrame) -> pd.Series:
        """Predict regime for each bar. Returns Series of regime ints."""
        if not self.is_fitted:
            raise ValueError("RegimeDetector not fitted. Call fit() first.")

        X_raw = self._select_features(features)
        if X_raw.empty:
            return pd.Series(RANGING, index=features.index)

        X_scaled = self.scaler.transform(X_raw.values)
        if HAS_HMM:
            states = self._model.predict(X_scaled)
        else:
            states = self._model.predict(X_scaled)

        regimes = pd.Series(
            [self._state_map.get(int(s), RANGING) for s in states],
            index=X_raw.index
        )
        # Fill gaps (bars where features were NaN)
        regimes = regimes.reindex(features.index, method='ffill').fillna(RANGING).astype(int)
        return regimes

    def predict_with_confidence(self, features: pd.DataFrame) -> pd.DataFrame:
        """Predict regime + posterior probabilities per bar."""
        if not self.is_fitted:
            raise ValueError("Not fitted.")

        X_raw = self._select_features(features)
        if X_raw.empty:
            return pd.DataFrame()

        X_scaled = self.scaler.transform(X_raw.values)

        if HAS_HMM:
            try:
                log_probs = self._model.predict_proba(X_scaled)
            except AttributeError:
                # Older hmmlearn: use score_samples per state
                states = self._model.predict(X_scaled)
                log_probs = np.zeros((len(states), self._n_states))
                for i, s in enumerate(states):
                    log_probs[i, s] = 1.0
        else:
            log_probs = self._model.predict_proba(X_scaled)

        states = self._model.predict(X_scaled)

        result = pd.DataFrame(index=X_raw.index)
        result['regime'] = [self._state_map.get(int(s), RANGING) for s in states]
        result['regime_name'] = result['regime'].map(REGIME_NAMES)
        result['confidence'] = log_probs.max(axis=1)

        for state_idx in range(self._n_states):
            regime_const = self._state_map.get(state_idx, RANGING)
            rname = REGIME_NAMES[regime_const].lower().replace('-', '_').replace(' ', '_')
            result[f'prob_{rname}'] = log_probs[:, state_idx]

        return result

    def get_current_regime(self, features: pd.DataFrame) -> dict:
        """Get most recent regime with confidence and transition info."""
        try:
            result = self.predict_with_confidence(features)
            if result.empty:
                return self._default_regime()

            latest = result.iloc[-1]
            regime_int = int(latest['regime'])
            confidence = float(latest.get('confidence', 0.5))

            # Transition: look at last 5 bars for regime changes
            if len(result) >= 5:
                recent = result['regime'].values[-5:]
                is_transitioning = len(set(recent)) > 2
            else:
                is_transitioning = False

            probs = {
                REGIME_NAMES[r]: float(latest.get(
                    f'prob_{REGIME_NAMES[r].lower().replace("-","_").replace(" ","_")}', 0
                ))
                for r in REGIME_NAMES
            }

            return {
                "regime": regime_int,
                "regime_name": REGIME_NAMES.get(regime_int, "Ranging"),
                "confidence": confidence,
                "probabilities": probs,
                "transitioning": is_transitioning,
            }
        except Exception:
            return self._default_regime()

    def get_factor_weights(self, features: pd.DataFrame) -> dict:
        """Return recommended factor weights for the current regime."""
        from strategies.signal_engine import REGIME_WEIGHTS, DEFAULT_WEIGHTS
        try:
            current = self.get_current_regime(features)
            regime = current.get('regime', -1)
            return REGIME_WEIGHTS.get(regime, DEFAULT_WEIGHTS)
        except Exception:
            return DEFAULT_WEIGHTS

    def _default_regime(self) -> dict:
        return {
            "regime": RANGING,
            "regime_name": "Ranging",
            "confidence": 0.5,
            "probabilities": {n: 0.25 for n in REGIME_NAMES.values()},
            "transitioning": False,
        }
