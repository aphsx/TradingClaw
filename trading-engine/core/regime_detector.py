"""
Regime Detector - ML-based Market Regime Classification
========================================================
Uses a combination of rule-based + ML approaches:
1. Rule-based (ADX + Volatility thresholds) as baseline
2. K-Means clustering as unsupervised approach
3. Random Forest trained on rule-based labels (for production)
"""
import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import cross_val_score
import warnings
warnings.filterwarnings('ignore')

import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import *

# Regime labels
TRENDING = 0
RANGING = 1
VOLATILE = 2

REGIME_NAMES = {TRENDING: "Trending", RANGING: "Ranging", VOLATILE: "Volatile"}
REGIME_COLORS = {TRENDING: "#1D9E75", RANGING: "#378ADD", VOLATILE: "#D85A30"}


class RegimeDetector:
    """
    Multi-method regime detector.
    Classifies market into: Trending / Ranging / Volatile
    """
    
    def __init__(self):
        self.scaler = StandardScaler()
        self.rf_model = RandomForestClassifier(
            n_estimators=200,
            max_depth=8,
            min_samples_leaf=10,
            random_state=42,
            class_weight='balanced'
        )
        self.kmeans = KMeans(n_clusters=3, random_state=42, n_init=10)
        self.is_fitted = False
        self.feature_importance = None
    
    def _rule_based_regime(self, df: pd.DataFrame) -> pd.Series:
        """
        Classify regime using ADX + ATR rules.
        This serves as training labels for the ML model.
        """
        regimes = pd.Series(RANGING, index=df.index)
        
        # Trending: ADX > threshold AND not excessively volatile
        trending_mask = (
            (df['adx'] > ADX_THRESHOLD) & 
            (df['atr_pct'] < df['atr_pct'].rolling(50, min_periods=10).mean() * VOLATILITY_THRESHOLD)
        )
        regimes[trending_mask] = TRENDING
        
        # Volatile: High ATR OR high volatility ratio OR high volume + ATR combo
        volatile_mask = (
            (df['atr_pct'] > df['atr_pct'].rolling(50, min_periods=10).mean() * VOLATILITY_THRESHOLD) |
            (df['volatility_ratio'] > 1.3) |
            ((df['volume_ratio'] > 1.8) & (df['atr_pct'] > df['atr_pct'].rolling(20, min_periods=5).mean() * 1.2))
        )
        regimes[volatile_mask] = VOLATILE
        
        # Ranging: Low ADX, normal volatility (default)
        # Already set as default
        
        # Smooth: don't flip regime on a single bar
        regimes = regimes.rolling(3, center=True, min_periods=1).apply(
            lambda x: pd.Series(x).mode()[0]
        ).astype(int)
        
        return regimes
    
    def fit(self, df: pd.DataFrame, features: pd.DataFrame):
        """
        Train the regime detector:
        1. Generate rule-based labels
        2. Split into train (80%) + holdout (20%) for out-of-sample accuracy
        3. Train Random Forest on train set
        4. Also fit K-Means for comparison
        """
        # Get rule-based labels
        rule_labels = self._rule_based_regime(df)

        # Align features and labels
        common_idx = features.index.intersection(rule_labels.index)
        X = features.loc[common_idx].dropna()
        y = rule_labels.loc[X.index]

        # ── Train / Holdout split (80/20) for out-of-sample accuracy ──
        split = int(len(X) * 0.8)
        X_train, X_holdout = X.iloc[:split], X.iloc[split:]
        y_train, y_holdout = y.iloc[:split], y.iloc[split:]

        # Scale features (fit on train only)
        X_train_scaled = self.scaler.fit_transform(X_train)
        X_holdout_scaled = self.scaler.transform(X_holdout)

        # Train Random Forest on train set
        self.rf_model.fit(X_train_scaled, y_train)

        # Cross-validation score (within train set)
        cv_scores = cross_val_score(self.rf_model, X_train_scaled, y_train, cv=5, scoring='accuracy')

        # Out-of-sample holdout accuracy
        holdout_preds = self.rf_model.predict(X_holdout_scaled)
        holdout_correct = (holdout_preds == y_holdout.values).sum()
        holdout_accuracy = holdout_correct / max(len(y_holdout), 1)

        # Feature importance
        self.feature_importance = pd.Series(
            self.rf_model.feature_importances_,
            index=X_train.columns
        ).sort_values(ascending=False)

        # Also fit K-Means (unsupervised comparison) on full scaled data
        X_all_scaled = self.scaler.transform(X)
        self.kmeans.fit(X_all_scaled)

        self.is_fitted = True

        stats = {
            "cv_accuracy": f"{cv_scores.mean():.3f} ± {cv_scores.std():.3f}",
            "holdout_accuracy": f"{holdout_accuracy:.3f}  ({holdout_correct}/{len(y_holdout)} correct)",
            "regime_distribution": {
                REGIME_NAMES[r]: int((y == r).sum()) for r in [TRENDING, RANGING, VOLATILE]
            },
            "top_features": self.feature_importance.head(5).to_dict()
        }

        return stats
    
    def predict(self, features: pd.DataFrame) -> pd.Series:
        """Predict regime for new data."""
        if not self.is_fitted:
            raise ValueError("Model not fitted. Call fit() first.")
        
        X = features.dropna()
        X_scaled = self.scaler.transform(X)
        predictions = self.rf_model.predict(X_scaled)
        
        return pd.Series(predictions, index=X.index, name='regime')
    
    def predict_with_confidence(self, features: pd.DataFrame) -> pd.DataFrame:
        """Predict regime with confidence scores."""
        if not self.is_fitted:
            raise ValueError("Model not fitted. Call fit() first.")
        
        X = features.dropna()
        X_scaled = self.scaler.transform(X)
        
        predictions = self.rf_model.predict(X_scaled)
        probabilities = self.rf_model.predict_proba(X_scaled)
        
        result = pd.DataFrame(index=X.index)
        result['regime'] = predictions
        result['regime_name'] = [REGIME_NAMES[r] for r in predictions]
        result['confidence'] = probabilities.max(axis=1)
        
        for i, name in REGIME_NAMES.items():
            if i < probabilities.shape[1]:
                result[f'prob_{name.lower()}'] = probabilities[:, i]
        
        return result
    
    def get_current_regime(self, features: pd.DataFrame) -> dict:
        """Get the current (latest) regime with details."""
        result = self.predict_with_confidence(features)
        latest = result.iloc[-1]
        
        return {
            "regime": int(latest['regime']),
            "regime_name": latest['regime_name'],
            "confidence": float(latest['confidence']),
            "probabilities": {
                name: float(latest.get(f'prob_{name.lower()}', 0))
                for name in REGIME_NAMES.values()
            }
        }
