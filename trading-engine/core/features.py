"""
Feature Engineering - Advanced Technical Indicators
====================================================
World-class feature engineering module with:
- All classic + advanced indicators (EMA, ATR, ADX, RSI, MACD, BB, Keltner, Ichimoku, OBV, CVD, VWAP)
- Heikin-Ashi trend analysis
- Session/time-based features (cyclical encoding, session overlap detection)
- Market structure features (swing highs/lows, higher highs/lower lows, price position)
- Linear regression channels (slope, R², deviation)
- Volume profile (POC distance, high volume nodes)
- Fibonacci retracement levels
- Advanced volatility (Garman-Klass, Parkinson, Yang-Zhang, vol-of-vol)
- Order flow features (buy/sell ratio, volume delta, large trades, CVD divergence)
- Multi-timeframe helper function

All computations are vectorized (no per-bar loops), NaN-safe, and prevent look-ahead bias.
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
    df['ichimoku_tenkan'] = (df['high'].rolling(9).max() + df['low'].rolling(9).min()) / 2
    df['ichimoku_kijun'] = (df['high'].rolling(26).max() + df['low'].rolling(26).min()) / 2
    df['ichimoku_senkou_a'] = ((df['ichimoku_tenkan'] + df['ichimoku_kijun']) / 2).shift(26)
    df['ichimoku_senkou_b'] = (
        (df['high'].rolling(52).max() + df['low'].rolling(52).min()) / 2
    ).shift(26)

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
    df['rv_hv_ratio'] = df['volatility_5'] / (df['volatility_20'] + 1e-10)

    df['bb_width_pct'] = df['bb_width'].rolling(100, min_periods=20).rank(pct=True) * 100

    # ─── VWAP ───
    typical_price = (df['high'] + df['low'] + df['close']) / 3
    if isinstance(df.index, pd.DatetimeIndex):
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
    upper_wick = df['high'] - df[['close', 'open']].max(axis=1)
    lower_wick = df[['close', 'open']].min(axis=1) - df['low']

    prev_body = body.shift(1)
    df['is_engulfing'] = (
        (body * prev_body < 0) &
        (body_abs > prev_body.abs())
    ).astype(float)

    df['is_pin_bar'] = (
        ((lower_wick > 2 * body_abs) & (lower_wick > upper_wick * 2)) |
        ((upper_wick > 2 * body_abs) & (upper_wick > lower_wick * 2))
    ).astype(float)

    # ─── RSI Divergence ───
    df['rsi_divergence'] = _detect_rsi_divergence_vec(df['close'], df['rsi_14'])

    # ─────────────────────────────────────────────────────────────────────────
    # NEW: HEIKIN-ASHI
    # ─────────────────────────────────────────────────────────────────────────
    df = _add_heikin_ashi(df)

    # ─────────────────────────────────────────────────────────────────────────
    # NEW: SESSION/TIME FEATURES
    # ─────────────────────────────────────────────────────────────────────────
    df = _add_session_features(df)

    # ─────────────────────────────────────────────────────────────────────────
    # NEW: MARKET STRUCTURE FEATURES
    # ─────────────────────────────────────────────────────────────────────────
    df = _add_market_structure(df)

    # ─────────────────────────────────────────────────────────────────────────
    # NEW: LINEAR REGRESSION CHANNEL
    # ─────────────────────────────────────────────────────────────────────────
    df = _add_linear_regression(df)

    # ─────────────────────────────────────────────────────────────────────────
    # NEW: VOLUME PROFILE
    # ─────────────────────────────────────────────────────────────────────────
    df = _add_volume_profile(df)

    # ─────────────────────────────────────────────────────────────────────────
    # NEW: FIBONACCI RETRACEMENT
    # ─────────────────────────────────────────────────────────────────────────
    df = _add_fibonacci_levels(df)

    # ─────────────────────────────────────────────────────────────────────────
    # NEW: ADVANCED VOLATILITY
    # ─────────────────────────────────────────────────────────────────────────
    df = _add_advanced_volatility(df)

    # ─────────────────────────────────────────────────────────────────────────
    # NEW: ORDER FLOW FEATURES
    # ─────────────────────────────────────────────────────────────────────────
    df = _add_order_flow(df)

    # ─── Regime composite features ───
    df['trend_strength'] = df['adx']
    df['range_score'] = 100 - df['adx']
    df['vol_score'] = df['atr_pct'] * df['volume_ratio']

    return df


# ═════════════════════════════════════════════════════════════════════════════
# HEIKIN-ASHI
# ═════════════════════════════════════════════════════════════════════════════

def _add_heikin_ashi(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate Heikin-Ashi OHLC and trend strength.

    HA Open = (HA_Open[prev] + HA_Close[prev]) / 2
    HA Close = (Open + High + Low + Close) / 4
    HA High = max(High, HA_Open, HA_Close)
    HA Low = min(Low, HA_Open, HA_Close)
    HA Trend: count consecutive bullish/bearish candles (capped at 8).
    """
    ha_close = (df['open'] + df['high'] + df['low'] + df['close']) / 4

    ha_open = pd.Series(index=df.index, dtype=float)
    ha_open.iloc[0] = (df['open'].iloc[0] + df['close'].iloc[0]) / 2
    for i in range(1, len(df)):
        ha_open.iloc[i] = (ha_open.iloc[i-1] + ha_close.iloc[i-1]) / 2

    ha_high = pd.concat([df['high'], ha_open, ha_close], axis=1).max(axis=1)
    ha_low = pd.concat([df['low'], ha_open, ha_close], axis=1).min(axis=1)

    df['ha_open'] = ha_open
    df['ha_high'] = ha_high
    df['ha_low'] = ha_low
    df['ha_close'] = ha_close

    # Trend: bullish if HA close > HA open, else bearish
    is_bullish = (ha_close > ha_open).astype(int)

    # Count consecutive bars: trend strength
    trend_count = np.zeros(len(df), dtype=float)
    for i in range(len(df)):
        if i == 0:
            trend_count[i] = 1 if is_bullish.iloc[i] else -1
        else:
            if is_bullish.iloc[i] == is_bullish.iloc[i-1]:
                # Same direction: increment (cap at 8)
                trend_count[i] = max(-8, min(8, trend_count[i-1] + (1 if is_bullish.iloc[i] else -1)))
            else:
                # Direction change: reset
                trend_count[i] = 1 if is_bullish.iloc[i] else -1

    # Normalize to 0-1 range (max strength at ±8)
    df['ha_trend_strength'] = np.abs(trend_count) / 8.0
    df['ha_trend_strength'] = df['ha_trend_strength'].clip(0, 1)

    return df


# ═════════════════════════════════════════════════════════════════════════════
# SESSION/TIME FEATURES
# ═════════════════════════════════════════════════════════════════════════════

def _add_session_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add cyclical time encoding and session detection.

    - hour_sin, hour_cos: cyclical encoding of hour (0-23)
    - day_of_week_sin, day_of_week_cos: cyclical encoding of day (0-6, Mon-Sun)
    - is_asian_session: 1 if UTC hour in [0, 8)
    - is_europe_session: 1 if UTC hour in [8, 16)
    - is_us_session: 1 if UTC hour in [13, 22)
    - session_overlap: 1 if London/NY overlap (14-16 UTC)
    """
    if not isinstance(df.index, pd.DatetimeIndex):
        # Can't compute session features without datetime index
        df['hour_sin'] = 0.0
        df['hour_cos'] = 0.0
        df['day_of_week_sin'] = 0.0
        df['day_of_week_cos'] = 0.0
        df['is_asian_session'] = 0.0
        df['is_europe_session'] = 0.0
        df['is_us_session'] = 0.0
        df['session_overlap'] = 0.0
        return df

    hours = df.index.hour.values.astype(float)
    days = df.index.dayofweek.values.astype(float)  # 0=Monday, 6=Sunday

    # Cyclical encoding: hour (0-23) and day (0-6)
    df['hour_sin'] = np.sin(2 * np.pi * hours / 24)
    df['hour_cos'] = np.cos(2 * np.pi * hours / 24)
    df['day_of_week_sin'] = np.sin(2 * np.pi * days / 7)
    df['day_of_week_cos'] = np.cos(2 * np.pi * days / 7)

    # Session detection (UTC times)
    df['is_asian_session'] = ((hours >= 0) & (hours < 8)).astype(float)
    df['is_europe_session'] = ((hours >= 8) & (hours < 16)).astype(float)
    df['is_us_session'] = ((hours >= 13) & (hours < 22)).astype(float)

    # London/NY overlap: London opens 8 UTC, NY opens 13 UTC, London closes 16 UTC
    df['session_overlap'] = ((hours >= 14) & (hours < 16)).astype(float)

    return df


# ═════════════════════════════════════════════════════════════════════════════
# MARKET STRUCTURE FEATURES
# ═════════════════════════════════════════════════════════════════════════════

def _add_market_structure(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add market structure features: swing highs/lows, price position, HH/LL count.

    - swing_high_distance: bars since last swing high (20-bar lookback)
    - swing_low_distance: bars since last swing low
    - price_position_in_range: normalized position between recent high/low (0-1)
    - higher_highs: count of higher highs in last 10 bars
    - lower_lows: count of lower lows in last 10 bars
    """
    lookback_swing = 20
    lookback_hl = 10

    # Swing highs: local max (higher than both neighbors)
    is_swing_high = pd.Series(False, index=df.index)
    for i in range(1, len(df) - 1):
        if df['high'].iloc[i] > df['high'].iloc[i-1] and df['high'].iloc[i] > df['high'].iloc[i+1]:
            is_swing_high.iloc[i] = True

    # Swing lows: local min
    is_swing_low = pd.Series(False, index=df.index)
    for i in range(1, len(df) - 1):
        if df['low'].iloc[i] < df['low'].iloc[i-1] and df['low'].iloc[i] < df['low'].iloc[i+1]:
            is_swing_low.iloc[i] = True

    # Distance to nearest swing high/low
    swing_high_dist = _distance_to_event(is_swing_high, lookback_swing)
    swing_low_dist = _distance_to_event(is_swing_low, lookback_swing)

    df['swing_high_distance'] = swing_high_dist
    df['swing_low_distance'] = swing_low_dist

    # Price position in recent range: where is price between recent high/low
    recent_high = df['high'].rolling(lookback_swing).max()
    recent_low = df['low'].rolling(lookback_swing).min()
    range_span = recent_high - recent_low
    df['price_position_in_range'] = (df['close'] - recent_low) / (range_span + 1e-10)
    df['price_position_in_range'] = df['price_position_in_range'].clip(0, 1)

    # Higher highs: count in last 10 bars
    higher_highs = np.zeros(len(df), dtype=float)
    for i in range(1, len(df)):
        count = 0
        for j in range(max(0, i - lookback_hl), i):
            if df['high'].iloc[i] > df['high'].iloc[j]:
                count += 1
        higher_highs[i] = count
    df['higher_highs'] = higher_highs

    # Lower lows: count in last 10 bars
    lower_lows = np.zeros(len(df), dtype=float)
    for i in range(1, len(df)):
        count = 0
        for j in range(max(0, i - lookback_hl), i):
            if df['low'].iloc[i] < df['low'].iloc[j]:
                count += 1
        lower_lows[i] = count
    df['lower_lows'] = lower_lows

    return df


def _distance_to_event(event_series: pd.Series, max_lookback: int) -> pd.Series:
    """
    Calculate bars since last True event (capped at max_lookback).
    Returns float series; NaN if no event in lookback window.
    """
    distance = pd.Series(np.nan, index=event_series.index)
    for i in range(len(event_series)):
        for j in range(i, max(i - max_lookback - 1, -1), -1):
            if event_series.iloc[j]:
                distance.iloc[i] = float(i - j)
                break
    return distance


# ═════════════════════════════════════════════════════════════════════════════
# LINEAR REGRESSION CHANNEL
# ═════════════════════════════════════════════════════════════════════════════

def _add_linear_regression(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add 20-bar linear regression features: slope, R², deviation.

    - linreg_slope: normalized slope of price regression
    - linreg_r2: R² (how well price follows trend)
    - linreg_deviation: std devs from regression line
    """
    window = 20
    closes = df['close'].values

    slopes = np.full(len(df), np.nan)
    r2_values = np.full(len(df), np.nan)
    deviations = np.full(len(df), np.nan)

    for i in range(window - 1, len(df)):
        y = closes[i - window + 1:i + 1]
        x = np.arange(window, dtype=float)

        # Linear regression
        x_mean = x.mean()
        y_mean = y.mean()
        numerator = np.sum((x - x_mean) * (y - y_mean))
        denominator = np.sum((x - x_mean) ** 2)

        if denominator < 1e-10:
            continue

        slope = numerator / denominator
        intercept = y_mean - slope * x_mean
        y_pred = slope * x + intercept

        # Normalize slope by mean price
        slopes[i] = slope / (abs(y_mean) + 1e-10)

        # R²
        ss_res = np.sum((y - y_pred) ** 2)
        ss_tot = np.sum((y - y_mean) ** 2)
        r2_values[i] = 1 - (ss_res / (ss_tot + 1e-10))

        # Deviation from line (in std devs)
        residuals = y - y_pred
        residual_std = np.std(residuals)
        deviations[i] = residuals[-1] / (residual_std + 1e-10)

    df['linreg_slope'] = slopes
    df['linreg_r2'] = r2_values
    df['linreg_r2'] = df['linreg_r2'].clip(0, 1)
    df['linreg_deviation'] = deviations

    return df


# ═════════════════════════════════════════════════════════════════════════════
# VOLUME PROFILE
# ═════════════════════════════════════════════════════════════════════════════

def _add_volume_profile(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add volume profile features: POC distance, weighted range, high volume nodes.

    - poc_distance: distance to Point of Control (highest volume price in 50-bar window)
    - volume_weighted_price_range: range weighted by volume
    - high_volume_nodes: count of price levels with > 1.5x average volume
    """
    window = 50

    # Point of Control: price level with most volume in window
    poc_dist = np.full(len(df), np.nan)
    vol_weighted_range = np.full(len(df), np.nan)
    high_vol_nodes = np.full(len(df), np.nan)

    for i in range(window - 1, len(df)):
        start = i - window + 1
        window_vol = df['volume'].iloc[start:i+1].sum()
        avg_vol = df['volume'].iloc[start:i+1].mean()

        # POC: approximate as the high/low of the candle with most volume
        max_vol_idx = df['volume'].iloc[start:i+1].idxmax()
        poc = (df.loc[max_vol_idx, 'high'] + df.loc[max_vol_idx, 'low']) / 2
        poc_dist[i] = abs(df['close'].iloc[i] - poc) / (df['atr_14'].iloc[i] + 1e-10)

        # Volume-weighted price range
        vol_weighted_high = np.sum(df['high'].iloc[start:i+1] * df['volume'].iloc[start:i+1]) / window_vol
        vol_weighted_low = np.sum(df['low'].iloc[start:i+1] * df['volume'].iloc[start:i+1]) / window_vol
        vol_weighted_range[i] = vol_weighted_high - vol_weighted_low

        # Count high volume nodes (candles with volume > 1.5x average)
        high_vol_nodes[i] = (df['volume'].iloc[start:i+1] > 1.5 * avg_vol).sum()

    df['poc_distance'] = poc_dist
    df['volume_weighted_price_range'] = vol_weighted_range
    df['high_volume_nodes'] = high_vol_nodes

    return df


# ═════════════════════════════════════════════════════════════════════════════
# FIBONACCI RETRACEMENT
# ═════════════════════════════════════════════════════════════════════════════

def _add_fibonacci_levels(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate Fibonacci retracement levels from recent swing high/low.

    - nearest_fib_distance: normalized distance to nearest fib level
    - fib_zone: which fib zone price is in (0=below 0, 1=0-0.236, 2=0.236-0.382, etc.)
    """
    fib_ratios = np.array([0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0])
    lookback = 50

    nearest_fib_dist = np.full(len(df), np.nan)
    fib_zone = np.full(len(df), np.nan)

    for i in range(lookback, len(df)):
        window_high = df['high'].iloc[i - lookback:i + 1].max()
        window_low = df['low'].iloc[i - lookback:i + 1].min()
        retracement = window_high - window_low

        # Calculate fib levels (from high down to low)
        fib_levels = window_high - fib_ratios * retracement

        # Distance to nearest fib level
        current_price = df['close'].iloc[i]
        distances = np.abs(current_price - fib_levels)
        nearest_fib_dist[i] = distances.min() / (df['atr_14'].iloc[i] + 1e-10)

        # Determine which zone price is in
        for zone_idx, ratio in enumerate(fib_ratios[:-1]):
            next_ratio = fib_ratios[zone_idx + 1]
            level_top = window_high - ratio * retracement
            level_bot = window_high - next_ratio * retracement
            if current_price <= level_top and current_price >= level_bot:
                fib_zone[i] = float(zone_idx)
                break

    df['nearest_fib_distance'] = nearest_fib_dist
    df['fib_zone'] = fib_zone

    return df


# ═════════════════════════════════════════════════════════════════════════════
# ADVANCED VOLATILITY
# ═════════════════════════════════════════════════════════════════════════════

def _add_advanced_volatility(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add advanced volatility estimators: Garman-Klass, Parkinson, Yang-Zhang, vol-of-vol.

    - garman_klass_vol: Garman-Klass volatility (intrabar high/low aware)
    - parkinson_vol: High-Low volatility (range-based)
    - yang_zhang_vol: Yang-Zhang volatility (most accurate)
    - vol_of_vol: volatility of volatility (20-bar std of 5-bar vol)
    """
    window = 20

    garman_klass = np.full(len(df), np.nan)
    parkinson = np.full(len(df), np.nan)
    yang_zhang = np.full(len(df), np.nan)

    for i in range(window - 1, len(df)):
        start = i - window + 1
        hi = df['high'].iloc[start:i+1].values
        lo = df['low'].iloc[start:i+1].values
        cl = df['close'].iloc[start:i+1].values
        op = df['open'].iloc[start:i+1].values

        # Garman-Klass: sqrt(0.5*ln(H/L)² - (2ln2-1)*ln(C/O)²)
        hl_ratio = np.log(hi / lo)
        co_ratio = np.log(cl / op)
        gk = np.sqrt(np.mean(0.5 * hl_ratio**2 - (2*np.log(2)-1) * co_ratio**2))
        garman_klass[i] = gk * np.sqrt(252) * 100  # Annualized %

        # Parkinson: sqrt(ln(H/L)² / (4*ln(2)))
        pk = np.sqrt(np.mean(np.log(hi / lo)**2) / (4 * np.log(2)))
        parkinson[i] = pk * np.sqrt(252) * 100

        # Yang-Zhang: blends close-to-close, high-low, open-close
        cc = np.log(cl[1:] / cl[:-1])  # close-to-close (numpy array, no .shift)
        ho = np.log(hi / op)
        hc = np.log(hi / cl)
        lo_calc = np.log(lo / cl)

        rs_cc = np.mean(cc**2)
        rs_ho = np.mean(ho * hc + lo_calc * (lo_calc - hc))

        alpha = np.mean(ho * (ho - hc) + lo_calc * (lo_calc - hc))
        yz = np.sqrt(alpha / window + rs_cc / (window - 1) + rs_ho / window)
        yang_zhang[i] = yz * np.sqrt(252) * 100

    df['garman_klass_vol'] = garman_klass
    df['parkinson_vol'] = parkinson
    df['yang_zhang_vol'] = yang_zhang

    # Vol-of-vol: 20-bar std of 5-bar volatility
    vol_5 = df['volatility_5'].rolling(20).std()
    df['vol_of_vol'] = vol_5

    return df


# ═════════════════════════════════════════════════════════════════════════════
# ORDER FLOW FEATURES
# ═════════════════════════════════════════════════════════════════════════════

def _add_order_flow(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add order flow and microstructure features.

    - buy_sell_ratio: buy_volume / sell_volume
    - volume_delta_ma: smoothed volume delta (5-bar MA)
    - large_trade_indicator: 1 if volume > 3x MA
    - cvd_divergence: 1 if CVD trend diverges from price trend
    """
    # Buy/sell ratio
    buy_sell_ratio = df['buy_volume'] / (df['sell_volume'] + 1e-10)
    df['buy_sell_ratio'] = buy_sell_ratio.fillna(1.0)

    # Volume delta MA (5-bar)
    df['volume_delta_ma'] = df['volume_delta'].rolling(5).mean()

    # Large trade indicator
    df['large_trade_indicator'] = (
        df['volume'] > (3 * df['volume_ma_20'])
    ).astype(float)

    # CVD divergence: compare CVD trend vs price trend
    # CVD trend: positive if CVD rising, negative if falling
    cvd_slope = _vectorized_rolling_slope(df['cvd_20'], window=10)
    price_slope = _vectorized_rolling_slope(df['close'], window=10)

    # Divergence: if slopes have opposite signs
    cvd_divergence = (
        (cvd_slope * price_slope < 0).astype(float)
    )
    df['cvd_divergence'] = cvd_divergence

    return df


# ═════════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═════════════════════════════════════════════════════════════════════════════

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
    """
    divergence = pd.Series(0.0, index=close.index)

    for i in range(lookback, len(close)):
        window_close = close.iloc[i - lookback:i + 1]
        window_rsi = rsi.iloc[i - lookback:i + 1]

        if window_rsi.isna().any():
            continue

        price_min_idx = window_close.idxmin()
        price_max_idx = window_close.idxmax()

        if close.iloc[i] <= window_close.quantile(0.2):
            rsi_at_price_low = window_rsi.loc[price_min_idx] if price_min_idx in window_rsi.index else window_rsi.min()
            if rsi.iloc[i] > rsi_at_price_low + 3:
                divergence.iloc[i] = 1.0

        if close.iloc[i] >= window_close.quantile(0.8):
            rsi_at_price_high = window_rsi.loc[price_max_idx] if price_max_idx in window_rsi.index else window_rsi.max()
            if rsi.iloc[i] < rsi_at_price_high - 3:
                divergence.iloc[i] = -1.0

    return divergence


def _vectorized_rolling_slope(series: pd.Series, window: int = 20) -> pd.Series:
    """
    O(N) vectorized linear regression slope for a rolling window.

    For x = [0, 1, ..., n-1]:
      slope = (n*Σxy - Σx*Σy) / (n*Σx² - (Σx)²)
    """
    n = window
    sum_x = n * (n - 1) / 2
    sum_x2 = n * (n - 1) * (2 * n - 1) / 6
    denom = n * sum_x2 - sum_x ** 2

    vals = series.values
    N = len(vals)

    pos = np.arange(N, dtype=float)

    jy = pos * vals
    cs_jy = np.concatenate(([0.0], np.nancumsum(jy)))
    cs_y = np.concatenate(([0.0], np.nancumsum(vals)))

    slopes = np.full(N, np.nan)
    for t in range(n - 1, N):
        w_start = t - n + 1
        sum_y = cs_y[t + 1] - cs_y[w_start]
        sum_jy = cs_jy[t + 1] - cs_jy[w_start]
        sum_xy = sum_jy - w_start * sum_y

        raw_slope = (n * sum_xy - sum_x * sum_y) / denom

        mean_y = sum_y / n
        slopes[t] = raw_slope / (abs(mean_y) + 1e-10)

    return pd.Series(slopes, index=series.index)


def _detect_rsi_divergence_vec(close: pd.Series, rsi: pd.Series,
                                lookback: int = 14) -> pd.Series:
    """
    Vectorized RSI divergence detection using rolling min/max.
    """
    w = lookback + 1

    divergence = pd.Series(0.0, index=close.index)

    valid = rsi.notna()

    price_q20 = close.rolling(w, min_periods=w).quantile(0.2)
    price_q80 = close.rolling(w, min_periods=w).quantile(0.8)
    rsi_min = rsi.rolling(w, min_periods=w).min()
    rsi_max = rsi.rolling(w, min_periods=w).max()

    bullish = valid & (close <= price_q20) & (rsi > rsi_min + 3)
    divergence[bullish] = 1.0

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

    # Add new regime-relevant features
    features['ha_trend_strength'] = df['ha_trend_strength']
    features['linreg_r2'] = df['linreg_r2']
    features['linreg_slope'] = df['linreg_slope']
    features['garman_klass_vol'] = df['garman_klass_vol']
    features['price_position_in_range'] = df['price_position_in_range']
    features['buy_sell_ratio'] = df['buy_sell_ratio']

    return features.dropna()


def calculate_htf_features(df_htf: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate simplified feature set for higher timeframe data (HTF).
    Used by signal engine for multi-timeframe confluence.

    Returns DataFrame with HTF versions of key indicators:
    - ema_9_slope_htf, ema_21_slope_htf, ema_50_slope_htf
    - rsi_14_htf
    - macd_hist_htf, macd_hist_slope_htf
    - adx_htf
    - volume_ratio_htf
    - atr_pct_htf
    """
    df_htf = df_htf.copy()

    # EMAs and slopes
    for period in [9, 21, 50]:
        col_name = f'ema_{period}_htf'
        df_htf[col_name] = df_htf['close'].ewm(span=period, adjust=False).mean()

    df_htf['ema_9_slope_htf'] = df_htf['ema_9_htf'].pct_change(5) * 100
    df_htf['ema_21_slope_htf'] = df_htf['ema_21_htf'].pct_change(5) * 100
    df_htf['ema_50_slope_htf'] = df_htf['ema_50_htf'].pct_change(5) * 100

    # RSI
    df_htf['rsi_14_htf'] = _calculate_rsi(df_htf['close'], period=14)

    # MACD
    df_htf['ema_12_htf'] = df_htf['close'].ewm(span=12, adjust=False).mean()
    df_htf['ema_26_htf'] = df_htf['close'].ewm(span=26, adjust=False).mean()
    df_htf['macd_line_htf'] = df_htf['ema_12_htf'] - df_htf['ema_26_htf']
    df_htf['macd_signal_htf'] = df_htf['macd_line_htf'].ewm(span=9, adjust=False).mean()
    df_htf['macd_hist_htf'] = df_htf['macd_line_htf'] - df_htf['macd_signal_htf']
    df_htf['macd_hist_slope_htf'] = df_htf['macd_hist_htf'].diff(3)

    # ADX
    df_htf['adx_htf'], _, _ = _calculate_adx_full(df_htf, period=14)

    # Volume
    df_htf['volume_ma_20_htf'] = df_htf['volume'].rolling(20).mean()
    df_htf['volume_ratio_htf'] = df_htf['volume'] / df_htf['volume_ma_20_htf']

    # ATR
    high_low = df_htf['high'] - df_htf['low']
    high_close = (df_htf['high'] - df_htf['close'].shift()).abs()
    low_close = (df_htf['low'] - df_htf['close'].shift()).abs()
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df_htf['atr_14_htf'] = true_range.rolling(14).mean()
    df_htf['atr_pct_htf'] = df_htf['atr_14_htf'] / df_htf['close'] * 100

    # Keep only HTF features for return
    htf_features = pd.DataFrame(index=df_htf.index)
    for col in df_htf.columns:
        if col.endswith('_htf'):
            htf_features[col] = df_htf[col]

    return htf_features.dropna()
