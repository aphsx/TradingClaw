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
    # 1.5σ bands for Range strategy (wider trigger zone → more signals)
    df['bb_upper_1_5'] = df['bb_mid'] + 1.5 * bb_std
    df['bb_lower_1_5'] = df['bb_mid'] - 1.5 * bb_std
    df['bb_width'] = (df['bb_upper'] - df['bb_lower']) / df['bb_mid'] * 100
    df['bb_pct'] = (df['close'] - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'])
    
    # ─── Volume ───
    df['volume_ma_20'] = df['volume'].rolling(20).mean()
    df['volume_ratio'] = df['volume'] / df['volume_ma_20']
    df['volume_std'] = df['volume'].rolling(20).std()
    
    # ─── Volatility measures ───
    # Use daily vol (sqrt(24) for hourly data), not annualized for regime detection
    df['volatility_20'] = df['returns'].rolling(20).std() * np.sqrt(24) * 100
    df['volatility_ratio'] = df['volatility_20'] / df['volatility_20'].rolling(50).mean()

    # ─── VWAP (daily reset for crypto) ───
    # Cumulative VWAP resets at midnight UTC so it stays meaningful over time
    typical_price = (df['high'] + df['low'] + df['close']) / 3
    if isinstance(df.index, pd.DatetimeIndex):
        df['_date'] = df.index.date
        grp = df.groupby('_date')
        cum_tp_vol = grp.apply(lambda g: (g['volume'] * ((g['high'] + g['low'] + g['close']) / 3)).cumsum())
        cum_vol = grp.apply(lambda g: g['volume'].cumsum())
        # Flatten multi-index back to original index
        cum_tp_vol = cum_tp_vol.reset_index(level=0, drop=True).reindex(df.index)
        cum_vol = cum_vol.reset_index(level=0, drop=True).reindex(df.index)
        df['vwap'] = cum_tp_vol / cum_vol
        df.drop(columns=['_date'], inplace=True)
    else:
        df['vwap'] = (df['volume'] * typical_price).cumsum() / df['volume'].cumsum()

    # Rolling VWAP (20-period moving window)
    vol_price = df['volume'] * typical_price
    df['vwap_20'] = vol_price.rolling(20).sum() / df['volume'].rolling(20).sum()

    # ─── VWAP Distance (normalized by ATR) ───
    df['vwap_distance'] = (df['close'] - df['vwap_20']) / df['atr_14']  # Price distance from VWAP
    
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
    """Calculate ADX using Wilder's smoothing (RMA), matching TradingView / standard.
    
    Previous implementation used ewm(alpha=1/period) which is mathematically
    equivalent to Wilder's RMA only asymptotically; the startup behaviour differs,
    yielding ADX values 5-10 points lower than reference implementations.
    We now seed the first smoothed value with a simple mean (SMA) over `period` bars
    and then apply Wilder's recursive formula manually.
    """
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

    def wilder_smooth(series: pd.Series, n: int) -> pd.Series:
        """Wilder's Smoothed Moving Average (RMA): seed=SMA(n), then recursive."""
        result = pd.Series(index=series.index, dtype=float)
        # Find first valid index where we have `n` bars
        valid = series.dropna()
        if len(valid) < n:
            return result
        first_idx = valid.index[n - 1]
        result[first_idx] = valid.iloc[:n].mean()  # SMA seed
        alpha = 1.0 / n
        for i in range(n, len(valid)):
            idx = valid.index[i]
            prev_idx = valid.index[i - 1]
            result[idx] = result[prev_idx] * (1 - alpha) + valid.iloc[i] * alpha
        return result

    atr_w = wilder_smooth(tr, period)
    plus_di_w = wilder_smooth(plus_dm, period)
    minus_di_w = wilder_smooth(minus_dm, period)

    plus_di = 100 * (plus_di_w / atr_w.replace(0, float('nan')))
    minus_di = 100 * (minus_di_w / atr_w.replace(0, float('nan')))

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, float('nan'))
    adx = wilder_smooth(dx.dropna(), period)
    adx = adx.reindex(df.index)

    return adx


def _calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Calculate RSI with proper SMA seed for first `period` bars, then EMA.
    
    Standard Wilder RSI: first avg_gain/loss = SMA over first `period` bars,
    then Wilder's EMA (alpha=1/period). This matches TradingView within 0.1 pts.
    Pure EWM from bar 1 gives consistently biased values.
    """
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)

    avg_gain = gain.copy().astype(float)
    avg_loss = loss.copy().astype(float)

    # Seed: SMA of first `period` gains/losses
    avg_gain.iloc[:period] = float('nan')
    avg_loss.iloc[:period] = float('nan')
    if len(gain) >= period:
        avg_gain.iloc[period - 1] = gain.iloc[:period].mean()
        avg_loss.iloc[period - 1] = loss.iloc[:period].mean()

    alpha = 1.0 / period
    for i in range(period, len(series)):
        avg_gain.iloc[i] = avg_gain.iloc[i - 1] * (1 - alpha) + gain.iloc[i] * alpha
        avg_loss.iloc[i] = avg_loss.iloc[i - 1] * (1 - alpha) + loss.iloc[i] * alpha

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
