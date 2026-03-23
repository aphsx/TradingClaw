"""
Binance Client — Public/Unsigned Endpoints Only
================================================
All authenticated order execution has been migrated to ccxt_client.py.

This file now exists ONLY as a delegate for endpoints that CCXT does not
expose in a standard way:

  get_mark_price()        → /fapi/v1/premiumIndex  (funding rate + next funding time)
  get_open_interest()     → /fapi/v1/openInterest
  get_long_short_ratio()  → /futures/data/globalLongShortAccountRatio
  get_funding_rate()      → /fapi/v1/fundingRate    (used as ccxt_client fallback)

All are called from ccxt_client.py; nothing outside this file should import
binance_client directly.
"""
import requests
from config import BASE_URL, SYMBOL, USE_FUTURES


# ─── Funding Rate ─────────────────────────────────────────────────────────────

def get_funding_rate(symbol: str = SYMBOL, limit: int = 1) -> list:
    """Get funding rate history. Latest first."""
    params = {"symbol": symbol, "limit": limit}
    r = requests.get(f"{BASE_URL}/fapi/v1/fundingRate", params=params, timeout=5)
    return r.json() if r.status_code == 200 else []


# ─── Mark Price ───────────────────────────────────────────────────────────────

def get_mark_price(symbol: str = SYMBOL) -> dict:
    """Get mark price, funding rate, and next funding time."""
    r = requests.get(f"{BASE_URL}/fapi/v1/premiumIndex", params={"symbol": symbol}, timeout=5)
    return r.json() if r.status_code == 200 else {}


# ─── Open Interest ────────────────────────────────────────────────────────────

def get_open_interest(symbol: str = SYMBOL) -> dict:
    """
    Fetch current Open Interest for a futures symbol.
    Returns {'openInterest': float, 'symbol': str, 'time': int} or {} on error.
    """
    if not USE_FUTURES:
        return {}
    try:
        r = requests.get(
            f"{BASE_URL}/fapi/v1/openInterest",
            params={"symbol": symbol},
            timeout=5,
        )
        if r.status_code == 200:
            data = r.json()
            return {
                "openInterest": float(data.get("openInterest", 0)),
                "symbol":       data.get("symbol", symbol),
                "time":         data.get("time", 0),
            }
    except Exception:
        pass
    return {}


# ─── Long / Short Ratio ───────────────────────────────────────────────────────

def get_long_short_ratio(symbol: str = SYMBOL, period: str = "5m") -> dict:
    """
    Fetch Global Long/Short Account Ratio for a futures symbol.
    Returns {'longAccount': float, 'shortAccount': float, 'longShortRatio': float} or {}.
    period: '5m' | '15m' | '30m' | '1h' | '2h' | '4h' | '6h' | '12h' | '1d'
    """
    if not USE_FUTURES:
        return {}
    try:
        base = BASE_URL
        r = requests.get(
            f"{base}/futures/data/globalLongShortAccountRatio",
            params={"symbol": symbol, "period": period, "limit": 1},
            timeout=5,
        )
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list) and len(data) > 0:
                latest    = data[-1]
                long_acct  = float(latest.get("longAccount",  0.5))
                short_acct = float(latest.get("shortAccount", 0.5))
                ratio      = float(latest.get("longShortRatio", 1.0))
                return {
                    "longAccount":    long_acct,
                    "shortAccount":   short_acct,
                    "longShortRatio": ratio,
                    "longRatio":      long_acct / max(long_acct + short_acct, 1e-10),
                }
    except Exception:
        pass
    return {}
