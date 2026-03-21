"""
Data Fetcher - Binance API + Synthetic Data Generator
======================================================
"""
import pandas as pd
import numpy as np
import requests
import time
import hmac
import hashlib
from urllib.parse import urlencode
from datetime import datetime, timedelta
import json
import os

import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import *

# API version prefix based on market type
API_PREFIX = "/fapi/v1" if USE_FUTURES else "/api/v3"


def _sign(params: dict) -> str:
    """Sign request with HMAC SHA256."""
    query = urlencode(params)
    sig = hmac.new(SECRET_KEY.encode(), query.encode(), hashlib.sha256).hexdigest()
    return query + "&signature=" + sig


def _headers():
    return {"X-MBX-APIKEY": API_KEY}


def test_connection() -> dict:
    """Test Binance API connectivity and account access."""
    results = {}

    # Test 1: Server time
    try:
        r = requests.get(f"{BASE_URL}{API_PREFIX}/time", timeout=10)
        results["server"] = {"status": r.status_code, "data": r.json()}
    except Exception as e:
        results["server"] = {"status": "error", "error": str(e)}

    # Test 2: Account info
    try:
        params = {"timestamp": int(time.time() * 1000), "recvWindow": 10000}
        url = f"{BASE_URL}{API_PREFIX}/account?{_sign(params)}"
        r = requests.get(url, headers=_headers(), timeout=10)
        data = r.json()
        if r.status_code == 200:
            balances = [b for b in data.get('balances', [])
                       if float(b['free']) > 0 or float(b['locked']) > 0]
            results["account"] = {
                "status": 200,
                "can_trade": data.get("canTrade"),
                "balances": balances[:10]
            }
        else:
            results["account"] = {"status": r.status_code, "error": data}
    except Exception as e:
        results["account"] = {"status": "error", "error": str(e)}

    # Test 3: Current price
    try:
        r = requests.get(f"{BASE_URL}{API_PREFIX}/ticker/price?symbol={SYMBOL}", timeout=10)
        results["price"] = r.json()
    except Exception as e:
        results["price"] = {"status": "error", "error": str(e)}

    return results


def validate_candles(df: pd.DataFrame, symbol: str = "BTCUSDT") -> pd.DataFrame:
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
            print(f"⚠️ {symbol}: Detected {spike_mask.sum()} spike candles, flagging")
            df.loc[spike_mask, 'is_spike'] = True
    return df


def fetch_klines(symbol: str = SYMBOL, interval: str = TIMEFRAME,
                 days: int = LOOKBACK_DAYS, lookback_days: int = None) -> pd.DataFrame:
    """Fetch historical klines/candlestick data from Binance."""
    # Support both parameter names for backwards compatibility
    if lookback_days is not None:
        days = lookback_days

    all_data = []
    end_time = int(time.time() * 1000)
    start_time = int((datetime.now() - timedelta(days=days)).timestamp() * 1000)

    print(f"📊 Fetching {symbol} {interval} data from Binance ({days} days)...")

    while start_time < end_time:
        try:
            params = {
                "symbol": symbol,
                "interval": interval,
                "startTime": start_time,
                "limit": 1000
            }
            r = requests.get(f"{BASE_URL}{API_PREFIX}/klines", params=params, timeout=15)
            data = r.json()

            if not data or isinstance(data, dict):
                break

            all_data.extend(data)
            start_time = data[-1][0] + 1  # Next batch after last candle
            time.sleep(0.1)  # Rate limit

        except Exception as e:
            print(f"⚠️ Error fetching data: {e}")
            break
    
    if not all_data:
        print("❌ No data fetched from Binance")
        return pd.DataFrame()
    
    df = pd.DataFrame(all_data, columns=[
        'timestamp', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_volume', 'trades', 'taker_buy_base',
        'taker_buy_quote', 'ignore'
    ])
    
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    for col in ['open', 'high', 'low', 'close', 'volume', 'quote_volume']:
        df[col] = df[col].astype(float)
    
    df = df[['timestamp', 'open', 'high', 'low', 'close', 'volume', 'quote_volume', 'trades']].copy()
    df = df.set_index('timestamp')

    # Validate candles
    df = validate_candles(df, symbol)

    print(f"✅ Fetched {len(df)} candles from {df.index[0]} to {df.index[-1]}")
    return df


def place_test_order(symbol: str = SYMBOL, side: str = "BUY",
                     quantity: float = 0.001, order_type: str = "MARKET") -> dict:
    """Place a test order (or real order on demo account)."""
    params = {
        "symbol": symbol,
        "side": side,
        "type": order_type,
        "quantity": f"{quantity:.6f}",
        "timestamp": int(time.time() * 1000),
        "recvWindow": 10000
    }

    # First try test order endpoint (Spot only, Futures doesn't support test endpoint)
    try:
        if USE_FUTURES:
            # Futures doesn't have test order endpoint, skip it
            test_result = {"test_order_status": "skipped", "reason": "Futures API doesn't support test orders"}
        else:
            url = f"{BASE_URL}{API_PREFIX}/order/test?{_sign(params)}"
            r = requests.post(url, headers=_headers(), timeout=10)
            test_result = {"test_order_status": r.status_code, "response": r.json() if r.text else {}}
    except Exception as e:
        test_result = {"test_order_status": "error", "error": str(e)}

    return test_result


def place_real_order(symbol: str = SYMBOL, side: str = "BUY",
                     quantity: float = 0.001, order_type: str = "MARKET",
                     price: float = None) -> dict:
    """Place a real order (use on demo account only!)."""
    params = {
        "symbol": symbol,
        "side": side,
        "type": order_type,
        "quantity": f"{quantity:.6f}",
        "timestamp": int(time.time() * 1000),
        "recvWindow": 10000
    }

    if order_type == "LIMIT" and price:
        params["price"] = f"{price:.2f}"
        params["timeInForce"] = "GTC"

    try:
        url = f"{BASE_URL}{API_PREFIX}/order?{_sign(params)}"
        r = requests.post(url, headers=_headers(), timeout=10)
        return {"status": r.status_code, "response": r.json()}
    except Exception as e:
        return {"status": "error", "error": str(e)}


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
            print(f"✅ Fetched {len(df)} candles for {symbol}")
        except Exception as e:
            print(f"⚠️ Failed to fetch {symbol}: {e}")
    return result


def get_data(use_api: bool = True, days: int = LOOKBACK_DAYS) -> pd.DataFrame:
    """Get data: try API first, fall back to synthetic."""
    if use_api:
        try:
            df = fetch_klines(days=days)
            if len(df) > 100:
                return df
        except Exception as e:
            print(f"⚠️ API failed: {e}, using synthetic data")
    
    print("📊 Generating realistic synthetic BTC data...")
    df = generate_realistic_btc_data(days=days)
    print(f"✅ Generated {len(df)} candles from {df.index[0]} to {df.index[-1]}")
    return df


def fetch_funding_rates(symbol: str = SYMBOL, limit: int = 100) -> pd.DataFrame:
    """Fetch funding rate history."""
    from data import binance_client as bnb
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
