"""
ML Signal Filter — LightGBM-based signal quality predictor
============================================================
Trains on historical trade outcomes to predict if a signal will be profitable.
Used as a final filter before placing orders.
"""
import numpy as np
import pandas as pd
from typing import Optional
import warnings
warnings.filterwarnings('ignore')

try:
    from sklearn.ensemble import GradientBoostingClassifier
    HAS_ML = True
except ImportError:
    HAS_ML = False


class MLSignalFilter:
    """Filter signals using ML prediction of trade outcome."""

    def __init__(self, min_samples: int = 50, threshold: float = 0.55):
        self.min_samples = min_samples
        self.threshold = threshold  # minimum probability to pass
        self.model = None
        self.is_fitted = False
        self.feature_cols = []

    def _extract_features(self, signal: dict, df: pd.DataFrame) -> dict:
        """Extract features from a signal and market data for ML prediction."""
        idx = signal.get('time') or signal.get('timestamp')
        features = {}

        # Price action features
        if idx is not None and idx in df.index:
            loc = df.index.get_loc(idx)
            if loc >= 20:
                recent = df.iloc[loc-20:loc+1]
                features['rsi'] = recent['rsi_14'].iloc[-1] if 'rsi_14' in recent.columns else 50
                features['atr_pct'] = recent['atr_pct'].iloc[-1] if 'atr_pct' in recent.columns else 0
                features['adx'] = recent['adx'].iloc[-1] if 'adx' in recent.columns else 0
                features['volume_ratio'] = recent['volume_ratio'].iloc[-1] if 'volume_ratio' in recent.columns else 1
                features['momentum'] = recent['momentum_10'].iloc[-1] if 'momentum_10' in recent.columns else 0
                features['bb_width'] = recent['bb_width'].iloc[-1] if 'bb_width' in recent.columns else 0
                features['vwap_dist'] = recent['vwap_distance'].iloc[-1] if 'vwap_distance' in recent.columns else 0

                # Derived features
                features['volatility_rank'] = (recent['atr_pct'].iloc[-1] / recent['atr_pct'].mean()) if 'atr_pct' in recent.columns and recent['atr_pct'].mean() > 0 else 1
                features['trend_strength'] = abs(features.get('momentum', 0))
                features['is_long'] = 1 if signal.get('direction') == 'LONG' else 0

        # Signal quality features
        features['confidence'] = signal.get('confidence', 0.5)
        features['risk_reward'] = signal.get('risk_reward', 0)
        features['expected_profit_pct'] = signal.get('expected_profit_pct', 0)

        # Regime
        regime_map = {'Trending': 0, 'Ranging': 1, 'Volatile': 2}
        features['regime'] = regime_map.get(signal.get('regime', ''), 1)

        return features

    def train(self, trades_df: pd.DataFrame, market_df: pd.DataFrame):
        """Train the ML filter on historical trade data."""
        if not HAS_ML:
            print("⚠️ ML libraries not available, filter disabled")
            return

        if len(trades_df) < self.min_samples:
            print(f"⚠️ ML filter needs {self.min_samples} trades, got {len(trades_df)}")
            return

        # Build feature matrix from historical trades
        X_rows = []
        y = []

        for _, trade in trades_df.iterrows():
            signal_dict = {
                'time': trade.get('entry_time'),
                'timestamp': trade.get('entry_time'),
                'direction': trade.get('direction', 'LONG'),
                'confidence': float(trade.get('confidence', 0.5) or 0.5),
                'risk_reward': float(trade.get('risk_reward', 0) or 0),
                'expected_profit_pct': 0,
                'regime': trade.get('regime', 'Ranging'),
            }
            features = self._extract_features(signal_dict, market_df)
            if features:
                X_rows.append(features)
                y.append(1 if float(trade.get('pnl', 0) or 0) > 0 else 0)

        if len(X_rows) < self.min_samples:
            return

        X = pd.DataFrame(X_rows).fillna(0)
        self.feature_cols = list(X.columns)
        y = np.array(y)

        # Train GradientBoosting (similar to LightGBM but in sklearn)
        self.model = GradientBoostingClassifier(
            n_estimators=100, max_depth=4, learning_rate=0.1,
            min_samples_leaf=10, subsample=0.8, random_state=42
        )
        self.model.fit(X, y)
        self.is_fitted = True

        # Print feature importance
        importances = sorted(zip(self.feature_cols, self.model.feature_importances_), key=lambda x: -x[1])
        print(f"✅ ML filter trained on {len(X)} trades | Top features: {', '.join(f'{n}={v:.3f}' for n,v in importances[:5])}")

    def predict(self, signal: dict, df: pd.DataFrame) -> dict:
        """Predict if a signal will be profitable. Returns {pass: bool, probability: float}."""
        if not self.is_fitted or not HAS_ML:
            return {"pass": True, "probability": 0.5, "reason": "ML filter not trained"}

        features = self._extract_features(signal, df)
        X = pd.DataFrame([features]).reindex(columns=self.feature_cols, fill_value=0)

        prob = self.model.predict_proba(X)[0][1]  # probability of class 1 (profitable)
        passed = prob >= self.threshold

        return {
            "pass": passed,
            "probability": round(float(prob), 3),
            "reason": f"ML confidence {prob:.1%}" if passed else f"ML rejected ({prob:.1%} < {self.threshold:.1%})"
        }
