"""
Feature Engineering - Technical Indicators for Regime Detection
================================================================
"""
import pandas as pd
import numpy as np


def calculate_features(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate all technical features needed for regime detection and strategies."""
    df = df.copy()
    
    # ─── Price-based ───
    df['returns'] = df['close'].pct_change()
    df['log_returns'] = np.log(df['close'] / df['close'].shift(1))
    
    # ─── EMAs ───
    for period in [9, 21, 50, 200]:
        df[f'ema_{period}'] = df['close'].ewm(span=period, adjust=False).mean()
    
    df['ema_9_slope'] = df['ema_9'].pct_change(5) * 100
    df['ema_21_slope'] = df['ema_21'].pct_change(5) * 100
    
    # ─── ATR (Average True Range) ───
    high_low = df['high'] - df['low']
    high_close = (df['high'] - df['close'].shift()).abs()
    low_close = (df['low'] - df['close'].shift()).abs()
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['atr_14'] = true_range.rolling(14).mean()
    df['atr_pct'] = df['atr_14'] / df['close'] * 100  # ATR as % of price
    
    # ─── ADX (Average Directional Index) ───
    df['adx'] = _calculate_adx(df, period=14)
    
    # ─── RSI ───
    df['rsi_14'] = _calculate_rsi(df['close'], period=14)
    
    # ─── Bollinger Bands ───
    df['bb_mid'] = df['close'].rolling(20).mean()
    bb_std = df['close'].rolling(20).std()
    df['bb_upper'] = df['bb_mid'] + 2 * bb_std
    df['bb_lower'] = df['bb_mid'] - 2 * bb_std
    df['bb_width'] = (df['bb_upper'] - df['bb_lower']) / df['bb_mid'] * 100
    df['bb_pct'] = (df['close'] - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'])
    
    # ─── Volume ───
    df['volume_ma_20'] = df['volume'].rolling(20).mean()
    df['volume_ratio'] = df['volume'] / df['volume_ma_20']
    df['volume_std'] = df['volume'].rolling(20).std()
    
    # ─── Volatility measures ───
    df['volatility_20'] = df['returns'].rolling(20).std() * np.sqrt(24 * 365) * 100
    df['volatility_ratio'] = df['volatility_20'] / df['volatility_20'].rolling(50).mean()
    
    # ─── VWAP (for intraday) ───
    df['vwap'] = (df['volume'] * (df['high'] + df['low'] + df['close']) / 3).cumsum() / df['volume'].cumsum()
    # Rolling VWAP (20-period)
    vol_price = df['volume'] * (df['high'] + df['low'] + df['close']) / 3
    df['vwap_20'] = vol_price.rolling(20).sum() / df['volume'].rolling(20).sum()
    
    # ─── Momentum ───
    df['momentum_10'] = df['close'].pct_change(10) * 100
    df['momentum_20'] = df['close'].pct_change(20) * 100
    
    # ─── Price position relative to key levels ───
    df['dist_ema_50'] = (df['close'] - df['ema_50']) / df['close'] * 100
    df['dist_vwap'] = (df['close'] - df['vwap_20']) / df['close'] * 100
    
    # ─── Regime features (composite) ───
    df['trend_strength'] = df['adx']
    df['range_score'] = 100 - df['adx']  # Low ADX = ranging
    df['vol_score'] = df['atr_pct'] * df['volume_ratio']  # High ATR + Volume = volatile
    
    return df


def _calculate_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Calculate ADX (Average Directional Index)."""
    high = df['high']
    low = df['low']
    close = df['close']
    
    plus_dm = high.diff()
    minus_dm = -low.diff()
    
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)
    
    high_low = high - low
    high_close = (high - close.shift()).abs()
    low_close = (low - close.shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    
    atr = tr.ewm(alpha=1/period, adjust=False).mean()
    plus_di = 100 * (plus_dm.ewm(alpha=1/period, adjust=False).mean() / atr)
    minus_di = 100 * (minus_dm.ewm(alpha=1/period, adjust=False).mean() / atr)
    
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1)
    adx = dx.ewm(alpha=1/period, adjust=False).mean()
    
    return adx


def _calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Calculate RSI."""
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    
    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
    
    rs = avg_gain / avg_loss.replace(0, 1e-10)
    rsi = 100 - (100 / (1 + rs))
    
    return rsi


def get_regime_features(df: pd.DataFrame) -> pd.DataFrame:
    """Extract features specifically for regime classification."""
    features = pd.DataFrame(index=df.index)
    
    features['adx'] = df['adx']
    features['atr_pct'] = df['atr_pct']
    features['bb_width'] = df['bb_width']
    features['volatility_20'] = df['volatility_20']
    features['volatility_ratio'] = df['volatility_ratio']
    features['volume_ratio'] = df['volume_ratio']
    features['ema_9_slope'] = df['ema_9_slope']
    features['ema_21_slope'] = df['ema_21_slope']
    features['momentum_10'] = df['momentum_10']
    features['rsi_14'] = df['rsi_14']
    
    return features.dropna()
