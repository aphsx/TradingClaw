"""
Data Fetcher - CCXT (Universal API) + Synthetic Data Generator
======================================================
"""
import pandas as pd
import numpy as np
import time
from datetime import datetime, timedelta
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import *

from data import ccxt_client

def test_connection() -> dict:
    """Test API connectivity and account access."""
    return ccxt_client.test_connection()


def validate_candles(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Validate candles: remove duplicates, fill small gaps, detect outliers."""
    if df.empty:
        return df
    # Remove duplicates
    df = df[~df.index.duplicated(keep='last')]
    # Sort
    df = df.sort_index()
    # Detect price outliers (spike >10x average ATR in a single candle)
    if 'high' in df.columns and 'low' in df.columns:
        candle_range = df['high'] - df['low']
        avg_range = candle_range.rolling(20).mean()
        spike_mask = candle_range > avg_range * 10
        if spike_mask.sum() > 0:
            print(f"[WARN] {symbol}: Detected {spike_mask.sum()} spike candles, flagging")
            df.loc[spike_mask, 'is_spike'] = True
    return df


def fetch_klines(symbol: str = SYMBOL, interval: str = TIMEFRAME,
                 days: int = LOOKBACK_DAYS, lookback_days: int = None) -> pd.DataFrame:
    """Fetch historical klines/candlestick data using CCXT."""
    if lookback_days is not None:
        days = lookback_days

    ex = ccxt_client.get_exchange()
    sym = ccxt_client._ccxt_symbol(symbol)
    
    tf_map = {'1m': '1m', '5m': '5m', '15m': '15m', '1h': '1h', '4h': '4h', '1d': '1d'}
    tf = tf_map.get(interval, interval)

    # Note: For OKX, fetch_ohlcv supports pagination with 'since' parameter
    end_time = int(time.time() * 1000)
    start_time = int((datetime.now() - timedelta(days=days)).timestamp() * 1000)
    
    print(f"[DATA] Fetching {symbol} {interval} data via CCXT ({days} days)...")
    
    all_data = []
    
    while start_time < end_time:
        try:
            # We fetch up to 100 bars per request, CCXT automatically maps standard limits
            bars = ex.fetch_ohlcv(sym, tf, since=start_time, limit=100)
            if not bars:
                break
                
            all_data.extend(bars)
            # Next batch starts after the last fetched candle
            start_time = bars[-1][0] + 1
            time.sleep(0.1) # Rate limit
        except Exception as e:
            print(f"[WARN] Error fetching data: {e}")
            break
            
    if not all_data:
        print(f"[ERROR] No data fetched from exchange")
        return pd.DataFrame()
        
    df = pd.DataFrame(all_data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    
    for col in ['open', 'high', 'low', 'close', 'volume']:
        df[col] = df[col].astype(float)
        
    df = df.set_index('timestamp')
    df = validate_candles(df, symbol)
    print(f"[OK] Fetched {len(df)} candles from {df.index[0]} to {df.index[-1]}")
    return df


def place_test_order(symbol: str = SYMBOL, side: str = "BUY",
                     quantity: float = 0.001, order_type: str = "MARKET") -> dict:
    """Mock testing API using ccxt."""
    print("Testing fake order on CCXT implementation.")
    return {"test_order_status": 200, "response": "Simulated fake order test"}


def place_real_order(symbol: str = SYMBOL, side: str = "BUY",
                     quantity: float = 0.001, order_type: str = "MARKET",
                     price: float = None) -> dict:
    """Use CCXT client explicitly instead."""
    if order_type.upper() == "LIMIT" and price:
        return ccxt_client.place_limit_order(symbol, side, quantity, price)
    return ccxt_client.place_market_order(symbol, side, quantity)


def generate_realistic_btc_data(days: int = 90, interval_hours: float = 1.0,
                                 seed: int = 42) -> pd.DataFrame:
    """
    Generate realistic BTC/USDT synthetic data with regime changes.
    Uses GBM with regime-switching volatility for realistic behavior.
    """
    np.random.seed(seed)
    
    n_candles = int(days * 24 / interval_hours)
    dt = interval_hours / (24 * 365)  # Time step in years
    
    # Start price around typical BTC range
    price = 84000.0
    
    # Define regimes with transition matrix
    # 0=Trending Up, 1=Trending Down, 2=Ranging, 3=Volatile
    regimes = []
    current_regime = 2  # Start ranging
    
    transition_matrix = np.array([
        [0.92, 0.02, 0.04, 0.02],  # From trending up
        [0.02, 0.90, 0.05, 0.03],  # From trending down  
        [0.06, 0.06, 0.84, 0.04],  # From ranging
        [0.05, 0.05, 0.10, 0.80],  # From volatile
    ])
    
    regime_params = {
        0: {"drift": 0.15, "vol": 0.25, "vol_name": "trend_up"},
        1: {"drift": -0.12, "vol": 0.30, "vol_name": "trend_down"},
        2: {"drift": 0.0,  "vol": 0.12, "vol_name": "ranging"},
        3: {"drift": 0.0,  "vol": 0.55, "vol_name": "volatile"},
    }
    
    opens, highs, lows, closes, volumes = [], [], [], [], []
    timestamps = []
    start_date = datetime(2025, 1, 1)
    
    for i in range(n_candles):
        # Regime transition
        if np.random.random() < 0.01 or i == 0:
            probs = transition_matrix[current_regime]
            current_regime = np.random.choice(4, p=probs)
        
        regimes.append(current_regime)
        params = regime_params[current_regime]
        
        # GBM with intra-candle simulation
        drift = params["drift"] * dt
        vol = params["vol"] * np.sqrt(dt)
        
        open_price = price
        
        # Simulate 10 sub-steps within candle
        sub_prices = [open_price]
        for _ in range(10):
            ret = drift/10 + vol/np.sqrt(10) * np.random.randn()
            sub_prices.append(sub_prices[-1] * (1 + ret))
        
        close_price = sub_prices[-1]
        high_price = max(sub_prices) * (1 + abs(np.random.randn()) * 0.001)
        low_price = min(sub_prices) * (1 - abs(np.random.randn()) * 0.001)
        
        # Volume correlates with volatility and regime
        base_vol = 500 + abs(np.random.randn()) * 200
        if current_regime == 3:  # Volatile = high volume
            base_vol *= 2.5
        elif current_regime in [0, 1]:  # Trending = moderate-high
            base_vol *= 1.5
        
        # Volume spike on big moves
        move = abs(close_price - open_price) / open_price
        if move > 0.005:
            base_vol *= (1 + move * 50)
        
        opens.append(round(open_price, 2))
        highs.append(round(high_price, 2))
        lows.append(round(low_price, 2))
        closes.append(round(close_price, 2))
        volumes.append(round(base_vol, 4))
        timestamps.append(start_date + timedelta(hours=i * interval_hours))
        
        price = close_price
    
    df = pd.DataFrame({
        'open': opens,
        'high': highs,
        'low': lows,
        'close': closes,
        'volume': volumes,
        'quote_volume': [v * c for v, c in zip(volumes, closes)],
        'trades': [int(v * 0.8) for v in volumes],
        '_true_regime': regimes  # Hidden: for validation only
    }, index=pd.DatetimeIndex(timestamps, name='timestamp'))
    
    return df


def fetch_multi_symbol(symbols: list, interval: str = "1h", lookback_days: int = 180) -> dict:
    """Fetch data for multiple symbols. Returns {symbol: dataframe}."""
    result = {}
    for symbol in symbols:
        try:
            df = fetch_klines(symbol=symbol, interval=interval, lookback_days=lookback_days)
            df = validate_candles(df, symbol)
            result[symbol] = df
            print(f"[OK] Fetched {len(df)} candles for {symbol}")
        except Exception as e:
            print(f"[WARN] Failed to fetch {symbol}: {e}")
    return result


def get_data(use_api: bool = True, days: int = LOOKBACK_DAYS) -> pd.DataFrame:
    """Get data: try API first, fall back to synthetic."""
    if use_api:
        try:
            df = fetch_klines(days=days)
            if len(df) > 100:
                return df
        except Exception as e:
            print(f"[WARN] API failed: {e}, using synthetic data")
    
    print("[DATA] Generating realistic synthetic BTC data...")
    df = generate_realistic_btc_data(days=days)
    print(f"[OK] Generated {len(df)} candles from {df.index[0]} to {df.index[-1]}")
    return df


def fetch_funding_rates(symbol: str = SYMBOL, limit: int = 100) -> pd.DataFrame:
    """Fetch funding rate history."""
    from data import ccxt_client as bnb
    rates = bnb.get_funding_rate(symbol, limit)
    if not rates:
        return pd.DataFrame()
    df = pd.DataFrame(rates)
    df['fundingTime'] = pd.to_datetime(df['fundingTime'], unit='ms')
    df['fundingRate'] = df['fundingRate'].astype(float)
    df.set_index('fundingTime', inplace=True)
    return df


def fetch_mark_price_klines(symbol: str = SYMBOL, interval: str = "1h", limit: int = 500) -> pd.DataFrame:
    """Fetch mark price klines (more accurate for futures SL/TP)."""
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    r = requests.get(f"{BASE_URL}/fapi/v1/markPriceKlines", params=params, timeout=10)
    if r.status_code != 200:
        return pd.DataFrame()
    data = r.json()
    df = pd.DataFrame(data, columns=["open_time","open","high","low","close","volume","close_time","na1","na2","na3","na4","na5"])
    df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
    for col in ['open','high','low','close']:
        df[col] = df[col].astype(float)
    df.set_index('open_time', inplace=True)
    return df


if __name__ == "__main__":
    print("=" * 60)
    print("TESTING BINANCE API CONNECTION")
    print("=" * 60)

    results = test_connection()
    print(json.dumps(results, indent=2, default=str))

    print("\n" + "=" * 60)
    print("TESTING DATA FETCH")
    print("=" * 60)

    df = get_data(use_api=True, days=7)
    if len(df) > 0:
        print(f"\nData shape: {df.shape}")
        print(f"Columns: {list(df.columns)}")
        print(f"\nLast 5 candles:")
        print(df.tail())
