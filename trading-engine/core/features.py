"""
Feature Engineering - Technical Indicators
============================================
Provides all technical features for regime detection, signal engine,
and ML filter. Includes classic + advanced indicators.
"""
import pandas as pd
import numpy as np


def calculate_features(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate all technical features. Returns enriched DataFrame."""
    df = df.copy()

    # ─── Price-based ───
    df['returns'] = df['close'].pct_change()
    df['log_returns'] = np.log(df['close'] / df['close'].shift(1))

    # ─── EMAs ───
    for period in [9, 12, 21, 26, 50, 200]:
        df[f'ema_{period}'] = df['close'].ewm(span=period, adjust=False).mean()

    df['ema_9_slope'] = df['ema_9'].pct_change(5) * 100
    df['ema_21_slope'] = df['ema_21'].pct_change(5) * 100

    # ─── ATR ───
    high_low = df['high'] - df['low']
    high_close = (df['high'] - df['close'].shift()).abs()
    low_close = (df['low'] - df['close'].shift()).abs()
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['atr_14'] = true_range.rolling(14).mean()
    df['atr_10'] = true_range.rolling(10).mean()
    df['atr_pct'] = df['atr_14'] / df['close'] * 100

    # ─── ADX + DI ───
    df['adx'], df['plus_di'], df['minus_di'] = _calculate_adx_full(df, period=14)

    # ─── RSI ───
    df['rsi_14'] = _calculate_rsi(df['close'], period=14)

    # ─── Stochastic RSI ───
    df['stoch_rsi_k'], df['stoch_rsi_d'] = _calculate_stoch_rsi(df['rsi_14'])

    # ─── Bollinger Bands ───
    df['bb_mid'] = df['close'].rolling(20).mean()
    bb_std = df['close'].rolling(20).std()
    df['bb_upper'] = df['bb_mid'] + 2 * bb_std
    df['bb_lower'] = df['bb_mid'] - 2 * bb_std
    df['bb_upper_1_5'] = df['bb_mid'] + 1.5 * bb_std
    df['bb_lower_1_5'] = df['bb_mid'] - 1.5 * bb_std
    df['bb_width'] = (df['bb_upper'] - df['bb_lower']) / df['bb_mid'] * 100
    df['bb_pct'] = (df['close'] - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'])

    # ─── Keltner Channel ───
    df['keltner_mid'] = df['ema_21']
    df['keltner_upper'] = df['ema_21'] + df['atr_10'] * 1.5
    df['keltner_lower'] = df['ema_21'] - df['atr_10'] * 1.5
    df['bb_inside_keltner'] = (
        (df['bb_upper'] < df['keltner_upper']) &
        (df['bb_lower'] > df['keltner_lower'])
    ).astype(float)

    # ─── MACD ───
    df['macd_line'] = df['ema_12'] - df['ema_26']
    df['macd_signal'] = df['macd_line'].ewm(span=9, adjust=False).mean()
    df['macd_hist'] = df['macd_line'] - df['macd_signal']
    df['macd_hist_slope'] = df['macd_hist'].diff(3)

    # ─── Ichimoku Cloud ───
    # LEAK-SAFE NOTES:
    #   ichimoku_tenkan/kijun   → only look back, no leakage ✓
    #   ichimoku_senkou_a/b     → shift(+26): value at T = cloud computed from T-26. ✓
    #                             Equivalent to "cloud from 26 bars ago projected to now".
    #   ichimoku_chikou         → shift(-26): USES FUTURE CLOSE → REMOVED to prevent leakage ✗
    df['ichimoku_tenkan'] = (df['high'].rolling(9).max() + df['low'].rolling(9).min()) / 2
    df['ichimoku_kijun'] = (df['high'].rolling(26).max() + df['low'].rolling(26).min()) / 2
    df['ichimoku_senkou_a'] = ((df['ichimoku_tenkan'] + df['ichimoku_kijun']) / 2).shift(26)
    df['ichimoku_senkou_b'] = (
        (df['high'].rolling(52).max() + df['low'].rolling(52).min()) / 2
    ).shift(26)
    # ichimoku_chikou intentionally omitted: close.shift(-26) uses T+26 future price.

    # Ichimoku cloud position: above=1, inside=0, below=-1
    cloud_top = df[['ichimoku_senkou_a', 'ichimoku_senkou_b']].max(axis=1)
    cloud_bot = df[['ichimoku_senkou_a', 'ichimoku_senkou_b']].min(axis=1)
    df['ichimoku_position'] = np.where(df['close'] > cloud_top, 1.0,
                               np.where(df['close'] < cloud_bot, -1.0, 0.0))

    # ─── Volume ───
    df['volume_ma_20'] = df['volume'].rolling(20).mean()
    df['volume_ratio'] = df['volume'] / df['volume_ma_20']
    df['volume_std'] = df['volume'].rolling(20).std()

    # ─── OBV (On-Balance Volume) ───
    obv = [0]
    closes = df['close'].values
    volumes = df['volume'].values
    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            obv.append(obv[-1] + volumes[i])
        elif closes[i] < closes[i - 1]:
            obv.append(obv[-1] - volumes[i])
        else:
            obv.append(obv[-1])
    df['obv'] = obv
    # Issue #3 fix — OBV slope: O(N) vectorized linear regression instead of O(N²) polyfit.
    # For a window of n bars with x = [0,1,...,n-1]:
    #   slope = (n*Σxy - Σx*Σy) / (n*Σx² - (Σx)²)
    # With Σx and Σx² constant for fixed n, only Σxy and Σy change per window.
    # Σxy is computed via rolling weighted sums using cumulative index trick (O(N)).
    df['obv_slope'] = _vectorized_rolling_slope(df['obv'], window=20)

    # ─── Cumulative Volume Delta (CVD) ───
    df['buy_volume'] = df['volume'] * (df['close'] - df['low']) / (df['high'] - df['low'] + 1e-10)
    df['sell_volume'] = df['volume'] * (df['high'] - df['close']) / (df['high'] - df['low'] + 1e-10)
    df['volume_delta'] = df['buy_volume'] - df['sell_volume']
    df['cvd_20'] = df['volume_delta'].rolling(20).sum()

    # ─── Volatility ───
    df['volatility_20'] = df['returns'].rolling(20).std() * np.sqrt(24) * 100
    df['volatility_5'] = df['returns'].rolling(5).std() * np.sqrt(24) * 100
    df['volatility_ratio'] = df['volatility_20'] / (df['volatility_20'].rolling(50).mean() + 1e-10)
    df['rv_hv_ratio'] = df['volatility_5'] / (df['volatility_20'] + 1e-10)  # Realized vs historical

    # BB bandwidth percentile (0-100) over last 100 bars
    df['bb_width_pct'] = df['bb_width'].rolling(100, min_periods=20).rank(pct=True) * 100

    # Issue #9 fix — VWAP: replace daily UTC-reset with 8h-period reset.
    # Crypto trades 24/7 — UTC midnight is not a meaningful session boundary.
    # Binance funding periods fire every 8h (00:00, 08:00, 16:00 UTC), making
    # 8h the most natural reset point for crypto VWAP.
    # Fallback: if index is not DatetimeIndex, use rolling 24-bar VWAP.
    typical_price = (df['high'] + df['low'] + df['close']) / 3
    if isinstance(df.index, pd.DatetimeIndex):
        # Assign each bar to its 8h funding period: floor to 8h bucket
        df['_period_8h'] = df.index.floor('8h')
        grp = df.groupby('_period_8h')
        cum_tp_vol = grp.apply(
            lambda g: (g['volume'] * ((g['high'] + g['low'] + g['close']) / 3)).cumsum(),
            include_groups=False
        )
        cum_vol = grp.apply(lambda g: g['volume'].cumsum(), include_groups=False)
        cum_tp_vol = cum_tp_vol.reset_index(level=0, drop=True).reindex(df.index)
        cum_vol = cum_vol.reset_index(level=0, drop=True).reindex(df.index)
        df['vwap'] = cum_tp_vol / cum_vol
        df.drop(columns=['_period_8h'], inplace=True)
    else:
        df['vwap'] = (df['volume'] * typical_price).cumsum() / df['volume'].cumsum()

    vol_price = df['volume'] * typical_price
    df['vwap_20'] = vol_price.rolling(20).sum() / df['volume'].rolling(20).sum()
    df['vwap_distance'] = (df['close'] - df['vwap_20']) / (df['atr_14'] + 1e-10)

    # VWAP Z-score (standard deviations above/below VWAP)
    vwap_diff = df['close'] - df['vwap_20']
    vwap_std = vwap_diff.rolling(20).std()
    df['vwap_zscore'] = vwap_diff / (vwap_std + 1e-10)

    # ─── Momentum ───
    df['momentum_10'] = df['close'].pct_change(10) * 100
    df['momentum_20'] = df['close'].pct_change(20) * 100
    df['roc_5'] = df['close'].pct_change(5) * 100

    # ─── Price structure ───
    df['dist_ema_50'] = (df['close'] - df['ema_50']) / df['close'] * 100
    df['dist_vwap'] = (df['close'] - df['vwap_20']) / df['close'] * 100

    # ─── Candlestick Patterns ───
    body = df['close'] - df['open']
    body_abs = body.abs()
    candle_range = df['high'] - df['low']
    upper_wick = df['high'] - df[['close', 'open']].max(axis=1)
    lower_wick = df[['close', 'open']].min(axis=1) - df['low']

    # Engulfing: current body completely covers previous body
    prev_body = body.shift(1)
    df['is_engulfing'] = (
        (body * prev_body < 0) &  # opposite directions
        (body_abs > prev_body.abs())  # current body larger
    ).astype(float)

    # Pin bar: wick > 2x body, small body at extreme
    df['is_pin_bar'] = (
        ((lower_wick > 2 * body_abs) & (lower_wick > upper_wick * 2)) |  # bullish pin
        ((upper_wick > 2 * body_abs) & (upper_wick > lower_wick * 2))    # bearish pin
    ).astype(float)

    # Issue #4 fix — RSI Divergence: vectorized rolling min/max instead of per-bar for loop
    df['rsi_divergence'] = _detect_rsi_divergence_vec(df['close'], df['rsi_14'])

    # ─── Regime composite features ───
    df['trend_strength'] = df['adx']
    df['range_score'] = 100 - df['adx']
    df['vol_score'] = df['atr_pct'] * df['volume_ratio']

    return df


def _calculate_adx_full(df: pd.DataFrame, period: int = 14):
    """Return (adx, plus_di, minus_di) using Wilder's smoothing."""
    high = df['high']
    low = df['low']
    close = df['close']

    plus_dm_raw = high.diff()
    minus_dm_raw = -low.diff()
    plus_dm = plus_dm_raw.where((plus_dm_raw > minus_dm_raw) & (plus_dm_raw > 0), 0.0)
    minus_dm = minus_dm_raw.where((minus_dm_raw > plus_dm_raw) & (minus_dm_raw > 0), 0.0)

    high_low = high - low
    high_close = (high - close.shift()).abs()
    low_close = (low - close.shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)

    atr_w = _wilder_smooth(tr, period)
    plus_di_w = _wilder_smooth(plus_dm, period)
    minus_di_w = _wilder_smooth(minus_dm, period)

    plus_di = 100 * (plus_di_w / atr_w.replace(0, float('nan')))
    minus_di = 100 * (minus_di_w / atr_w.replace(0, float('nan')))

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, float('nan'))
    adx = _wilder_smooth(dx.dropna(), period).reindex(df.index)

    return adx, plus_di, minus_di


def _calculate_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Calculate ADX only (backward-compatible wrapper)."""
    adx, _, _ = _calculate_adx_full(df, period)
    return adx


def _wilder_smooth(series: pd.Series, n: int) -> pd.Series:
    """Wilder's Smoothed Moving Average: seed=SMA(n), then recursive."""
    result = pd.Series(index=series.index, dtype=float)
    valid = series.dropna()
    if len(valid) < n:
        return result
    first_idx = valid.index[n - 1]
    result[first_idx] = valid.iloc[:n].mean()
    alpha = 1.0 / n
    for i in range(n, len(valid)):
        idx = valid.index[i]
        prev_idx = valid.index[i - 1]
        result[idx] = result[prev_idx] * (1 - alpha) + valid.iloc[i] * alpha
    return result


def _calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """RSI with SMA seed then Wilder EMA."""
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)

    avg_gain = gain.copy().astype(float)
    avg_loss = loss.copy().astype(float)
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
    return 100 - (100 / (1 + rs))


def _calculate_stoch_rsi(rsi: pd.Series, period: int = 14, smooth_k: int = 3, smooth_d: int = 3):
    """Stochastic RSI: Stochastic oscillator applied to RSI."""
    rsi_min = rsi.rolling(period).min()
    rsi_max = rsi.rolling(period).max()
    stoch = (rsi - rsi_min) / (rsi_max - rsi_min + 1e-10) * 100
    k = stoch.rolling(smooth_k).mean()
    d = k.rolling(smooth_d).mean()
    return k, d


def _detect_rsi_divergence(close: pd.Series, rsi: pd.Series, lookback: int = 14) -> pd.Series:
    """
    Detect RSI divergences.
    Returns: +1 (bullish divergence), -1 (bearish divergence), 0 (none).
    Bullish: price lower low, RSI higher low (potential reversal up).
    Bearish: price higher high, RSI lower high (potential reversal down).
    """
    divergence = pd.Series(0.0, index=close.index)

    for i in range(lookback, len(close)):
        window_close = close.iloc[i - lookback:i + 1]
        window_rsi = rsi.iloc[i - lookback:i + 1]

        if window_rsi.isna().any():
            continue

        # Find local extremes in price
        price_min_idx = window_close.idxmin()
        price_max_idx = window_close.idxmax()
        curr_idx = close.index[i]

        # Bullish divergence: current price near window low, RSI above its window low
        if close.iloc[i] <= window_close.quantile(0.2):
            rsi_at_price_low = window_rsi.loc[price_min_idx] if price_min_idx in window_rsi.index else window_rsi.min()
            if rsi.iloc[i] > rsi_at_price_low + 3:
                divergence.iloc[i] = 1.0

        # Bearish divergence: current price near window high, RSI below its window high
        if close.iloc[i] >= window_close.quantile(0.8):
            rsi_at_price_high = window_rsi.loc[price_max_idx] if price_max_idx in window_rsi.index else window_rsi.max()
            if rsi.iloc[i] < rsi_at_price_high - 3:
                divergence.iloc[i] = -1.0

    return divergence


def _vectorized_rolling_slope(series: pd.Series, window: int = 20) -> pd.Series:
    """
    Issue #3 — O(N) vectorized linear regression slope for a rolling window.

    For x = [0, 1, ..., n-1] within each window of size n:
      slope = (n*Σxy - Σx*Σy) / (n*Σx² - (Σx)²)

    Since Σx and Σx² are constant for fixed n, only Σxy and Σy vary.
    Σxy is computed using the identity:
      Σ_{i=0}^{n-1} i * y_{t-n+1+i}
      = (Σ_{j=t-n+1}^{t} j*y_j) - (t-n+1) * (Σ_{j=t-n+1}^{t} y_j)
    where j is the absolute positional index (0..N-1).
    Both terms are rolling sums → O(N) total.

    Returns slope normalized by |mean(y)| over the window.
    """
    n = window
    # Precompute constant terms for x = [0, ..., n-1]
    sum_x  = n * (n - 1) / 2                    # = 190 for n=20
    sum_x2 = n * (n - 1) * (2 * n - 1) / 6     # = 2470 for n=20
    denom  = n * sum_x2 - sum_x ** 2            # = 13300 for n=20

    vals = series.values
    N = len(vals)

    # Absolute positional indices (0, 1, ..., N-1)
    pos = np.arange(N, dtype=float)

    # Rolling sums via numpy cumsum (fastest path)
    jy = pos * vals                                   # j * y[j]
    cs_jy = np.concatenate(([0.0], np.nancumsum(jy))) # cumsum with sentinel at [0]
    cs_y  = np.concatenate(([0.0], np.nancumsum(vals)))

    slopes = np.full(N, np.nan)
    for t in range(n - 1, N):
        # Window start position
        w_start = t - n + 1
        sum_y  = cs_y[t + 1] - cs_y[w_start]
        sum_jy = cs_jy[t + 1] - cs_jy[w_start]
        sum_xy = sum_jy - w_start * sum_y   # rebase j to local index 0..n-1

        raw_slope = (n * sum_xy - sum_x * sum_y) / denom

        # Normalize by |mean(y)| to make it scale-independent (same as old polyfit code)
        mean_y = sum_y / n
        slopes[t] = raw_slope / (abs(mean_y) + 1e-10)

    return pd.Series(slopes, index=series.index)


def _detect_rsi_divergence_vec(close: pd.Series, rsi: pd.Series,
                                lookback: int = 14) -> pd.Series:
    """
    Issue #4 — RSI divergence: fully vectorized with rolling min/max.

    Original used a per-bar Python for loop → O(N·lookback).
    Vectorized approach: rolling quantile / rolling min / rolling max → O(N).

    Bullish divergence:  price near rolling low  AND  RSI > rolling_min(RSI) + 3
    Bearish divergence:  price near rolling high  AND  RSI < rolling_max(RSI) - 3

    "Near" is defined as <= 20th percentile (bullish) or >= 80th percentile (bearish)
    of the price distribution over the lookback window — matching the original logic.
    """
    w = lookback + 1   # window size (same as original: i-lookback to i inclusive)

    divergence = pd.Series(0.0, index=close.index)

    # Drop NaN RSI bars up front
    valid = rsi.notna()

    price_q20 = close.rolling(w, min_periods=w).quantile(0.2)
    price_q80 = close.rolling(w, min_periods=w).quantile(0.8)
    rsi_min   = rsi.rolling(w, min_periods=w).min()
    rsi_max   = rsi.rolling(w, min_periods=w).max()

    # Bullish: price at/below 20th percentile, RSI above rolling min + 3
    bullish = valid & (close <= price_q20) & (rsi > rsi_min + 3)
    divergence[bullish] = 1.0

    # Bearish: price at/above 80th percentile, RSI below rolling max - 3
    bearish = valid & (close >= price_q80) & (rsi < rsi_max - 3)
    divergence[bearish] = -1.0

    return divergence


def get_regime_features(df: pd.DataFrame) -> pd.DataFrame:
    """Extract features specifically for regime classification (HMM + RF)."""
    features = pd.DataFrame(index=df.index)

    features['adx'] = df['adx']
    features['plus_di'] = df['plus_di']
    features['minus_di'] = df['minus_di']
    features['atr_pct'] = df['atr_pct']
    features['bb_width'] = df['bb_width']
    features['volatility_20'] = df['volatility_20']
    features['volatility_ratio'] = df['volatility_ratio']
    features['volume_ratio'] = df['volume_ratio']
    features['ema_9_slope'] = df['ema_9_slope']
    features['ema_21_slope'] = df['ema_21_slope']
    features['momentum_10'] = df['momentum_10']
    features['rsi_14'] = df['rsi_14']
    features['rv_hv_ratio'] = df['rv_hv_ratio']
    features['obv_slope'] = df['obv_slope']
    features['cvd_20_norm'] = df['cvd_20'] / (df['volume'].rolling(20).mean() * 20 + 1e-10)

    return features.dropna()
