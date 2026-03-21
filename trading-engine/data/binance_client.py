"""
Binance Client - Real Order Management
========================================
Places real orders, queries fills, tracks commissions.
Every order response is stored raw in MySQL for audit.

Supports both Spot and Futures:
- Spot: /api/v3/* (testnet.binance.vision or api.binance.com)
- Futures: /fapi/v1/* (testnet.binancefuture.com or fapi.binance.com)
"""
import time
import hmac
import hashlib
import json
import uuid
import requests
from urllib.parse import urlencode
from typing import Optional
from config import API_KEY, SECRET_KEY, BASE_URL, SYMBOL, USE_FUTURES


# API version prefix based on market type
API_PREFIX = "/fapi/v1" if USE_FUTURES else "/api/v3"


def _sign(params: dict) -> str:
    q = urlencode(params)
    sig = hmac.new(SECRET_KEY.encode(), q.encode(), hashlib.sha256).hexdigest()
    return q + "&signature=" + sig


def _headers():
    return {"X-MBX-APIKEY": API_KEY}


# Global server time offset for clock skew correction
_server_time_offset = 0
_last_offset_sync = 0


def _sync_server_time():
    """Sync local time with Binance server time. Cache offset for 60s."""
    global _server_time_offset, _last_offset_sync
    now = time.time()
    if now - _last_offset_sync > 60:  # Resync every 60s
        try:
            local_before = int(time.time() * 1000)
            r = requests.get(f"{BASE_URL}{API_PREFIX}/time", timeout=5)
            local_after = int(time.time() * 1000)
            server_time = r.json()["serverTime"]
            latency = (local_after - local_before) // 2
            _server_time_offset = server_time - local_before - latency
            _last_offset_sync = now
        except Exception:
            pass  # Keep existing offset if sync fails


def _ts():
    """Get current timestamp with server time offset correction."""
    _sync_server_time()
    return int(time.time() * 1000) + _server_time_offset


# ═══════════════════════════════════════
# ACCOUNT / INFO
# ═══════════════════════════════════════

def ping() -> bool:
    try:
        r = requests.get(f"{BASE_URL}{API_PREFIX}/ping", timeout=5)
        return r.status_code == 200
    except Exception:
        return False


def server_time() -> int:
    r = requests.get(f"{BASE_URL}{API_PREFIX}/time", timeout=5)
    return r.json()["serverTime"]


def account_info() -> dict:
    params = {"timestamp": _ts(), "recvWindow": 10000}
    r = requests.get(f"{BASE_URL}{API_PREFIX}/account?{_sign(params)}",
                     headers=_headers(), timeout=10)
    return r.json()


def get_balances() -> dict:
    """Return {asset: {free, locked}} for non-zero balances."""
    info = account_info()
    balances = {}
    for b in info.get("balances", []):
        free = float(b["free"])
        locked = float(b["locked"])
        if free > 0 or locked > 0:
            balances[b["asset"]] = {"free": free, "locked": locked}
    return balances


def get_price(symbol: str = SYMBOL) -> float:
    r = requests.get(f"{BASE_URL}{API_PREFIX}/ticker/price",
                     params={"symbol": symbol}, timeout=5)
    return float(r.json()["price"])


def get_symbol_info(symbol: str = SYMBOL) -> dict:
    """Get trading rules: min qty, step size, tick size, etc."""
    r = requests.get(f"{BASE_URL}{API_PREFIX}/exchangeInfo",
                     params={"symbol": symbol}, timeout=10)
    for s in r.json().get("symbols", []):
        if s["symbol"] == symbol:
            return s
    return {}


# ═══════════════════════════════════════
# ORDER PLACEMENT
# ═══════════════════════════════════════

def place_market_order(symbol: str, side: str, quantity: float) -> dict:
    """
    Place a MARKET order. Returns full Binance response including:
    orderId, clientOrderId, fills (with price, qty, commission, commissionAsset)
    """
    client_oid = f"regime_{uuid.uuid4().hex[:16]}"
    params = {
        "symbol": symbol,
        "side": side,             # BUY or SELL
        "type": "MARKET",
        "quantity": f"{quantity:.6f}",
        "newClientOrderId": client_oid,
        "newOrderRespType": "FULL",   # ← get fills in response
        "timestamp": _ts(),
        "recvWindow": 10000,
    }
    r = requests.post(f"{BASE_URL}{API_PREFIX}/order?{_sign(params)}",
                      headers=_headers(), timeout=10)
    resp = r.json()
    resp["_http_status"] = r.status_code
    resp["_client_oid"] = client_oid
    return resp


def place_limit_order(symbol: str, side: str, quantity: float,
                      price: float, time_in_force: str = "GTC") -> dict:
    client_oid = f"regime_{uuid.uuid4().hex[:16]}"
    params = {
        "symbol": symbol,
        "side": side,
        "type": "LIMIT",
        "quantity": f"{quantity:.6f}",
        "price": f"{price:.2f}",
        "timeInForce": time_in_force,
        "newClientOrderId": client_oid,
        "newOrderRespType": "FULL",
        "timestamp": _ts(),
        "recvWindow": 10000,
    }
    r = requests.post(f"{BASE_URL}{API_PREFIX}/order?{_sign(params)}",
                      headers=_headers(), timeout=10)
    resp = r.json()
    resp["_http_status"] = r.status_code
    resp["_client_oid"] = client_oid
    return resp


def place_stop_loss_order(symbol: str, side: str, quantity: float,
                          stop_price: float) -> dict:
    """Place stop loss. Uses STOP_MARKET for futures (better fills, no limit price needed)."""
    client_oid = f"regime_sl_{uuid.uuid4().hex[:12]}"
    if USE_FUTURES:
        params = {
            "symbol": symbol, "side": side, "type": "STOP_MARKET",
            "quantity": f"{quantity:.6f}", "stopPrice": f"{stop_price:.2f}",
            "newClientOrderId": client_oid, "timestamp": _ts(), "recvWindow": 10000,
        }
    else:
        # Spot: STOP_LOSS_LIMIT (keep existing logic)
        offset = stop_price * 0.001
        limit_price = stop_price - offset if side == "SELL" else stop_price + offset
        params = {
            "symbol": symbol, "side": side, "type": "STOP_LOSS_LIMIT",
            "quantity": f"{quantity:.6f}", "price": f"{limit_price:.2f}",
            "stopPrice": f"{stop_price:.2f}", "timeInForce": "GTC",
            "newClientOrderId": client_oid, "newOrderRespType": "FULL",
            "timestamp": _ts(), "recvWindow": 10000,
        }
    r = requests.post(f"{BASE_URL}{API_PREFIX}/order?{_sign(params)}", headers=_headers(), timeout=10)
    resp = r.json()
    resp["_http_status"] = r.status_code
    resp["_client_oid"] = client_oid
    return resp


def place_take_profit_order(symbol: str, side: str, quantity: float,
                            stop_price: float) -> dict:
    """Place take profit. Uses TAKE_PROFIT_MARKET for futures."""
    client_oid = f"regime_tp_{uuid.uuid4().hex[:12]}"
    if USE_FUTURES:
        params = {
            "symbol": symbol, "side": side, "type": "TAKE_PROFIT_MARKET",
            "quantity": f"{quantity:.6f}", "stopPrice": f"{stop_price:.2f}",
            "newClientOrderId": client_oid, "timestamp": _ts(), "recvWindow": 10000,
        }
    else:
        # Spot: TAKE_PROFIT_LIMIT (keep existing logic)
        offset = stop_price * 0.001
        limit_price = stop_price + offset if side == "SELL" else stop_price - offset
        params = {
            "symbol": symbol, "side": side, "type": "TAKE_PROFIT_LIMIT",
            "quantity": f"{quantity:.6f}", "price": f"{limit_price:.2f}",
            "stopPrice": f"{stop_price:.2f}", "timeInForce": "GTC",
            "newClientOrderId": client_oid, "newOrderRespType": "FULL",
            "timestamp": _ts(), "recvWindow": 10000,
        }
    r = requests.post(f"{BASE_URL}{API_PREFIX}/order?{_sign(params)}",
                      headers=_headers(), timeout=10)
    resp = r.json()
    resp["_http_status"] = r.status_code
    resp["_client_oid"] = client_oid
    return resp


# ═══════════════════════════════════════
# ORDER QUERIES
# ═══════════════════════════════════════

def get_order(symbol: str, order_id: int) -> dict:
    """Query a specific order by orderId."""
    params = {"symbol": symbol, "orderId": order_id,
              "timestamp": _ts(), "recvWindow": 10000}
    r = requests.get(f"{BASE_URL}{API_PREFIX}/order?{_sign(params)}",
                     headers=_headers(), timeout=10)
    return r.json()


def get_order_trades(symbol: str, order_id: int) -> list:
    """Get individual fills/trades for an order."""
    params = {"symbol": symbol, "orderId": order_id,
              "timestamp": _ts(), "recvWindow": 10000}
    r = requests.get(f"{BASE_URL}{API_PREFIX}/myTrades?{_sign(params)}",
                     headers=_headers(), timeout=10)
    return r.json() if r.status_code == 200 else []


def get_open_orders(symbol: str = SYMBOL) -> list:
    params = {"symbol": symbol, "timestamp": _ts(), "recvWindow": 10000}
    r = requests.get(f"{BASE_URL}{API_PREFIX}/openOrders?{_sign(params)}",
                     headers=_headers(), timeout=10)
    return r.json() if r.status_code == 200 else []


def get_all_open_orders(symbol: str = None) -> list:
    """Get all open orders across all symbols (or specific symbol)."""
    params = {"timestamp": _ts(), "recvWindow": 10000}
    if symbol:
        params["symbol"] = symbol
    r = requests.get(f"{BASE_URL}{API_PREFIX}/openOrders?{_sign(params)}",
                     headers=_headers(), timeout=10)
    return r.json() if r.status_code == 200 else []


def get_position_history(symbol: str = None, start_time: int = None,
                         end_time: int = None, limit: int = 100) -> list:
    """
    Get position/trading history from Binance.
    This returns filled orders that resulted in position changes.
    """
    params = {
        "timestamp": _ts(),
        "recvWindow": 10000,
        "limit": limit,
    }
    if symbol:
        params["symbol"] = symbol
    if start_time:
        params["startTime"] = start_time
    if end_time:
        params["endTime"] = end_time

    r = requests.get(f"{BASE_URL}{API_PREFIX}/myTrades?{_sign(params)}",
                     headers=_headers(), timeout=10)
    return r.json() if r.status_code == 200 else []


def get_account_positions() -> list:
    """Get current positions. Uses /fapi/v2/positionRisk for futures."""
    if USE_FUTURES:
        risks = get_position_risk()
        positions = []
        for r in risks:
            amt = float(r.get("positionAmt", 0))
            if amt != 0:
                positions.append({
                    "symbol": r["symbol"],
                    "direction": "LONG" if amt > 0 else "SHORT",
                    "quantity": abs(amt),
                    "entry_price": float(r.get("entryPrice", 0)),
                    "mark_price": float(r.get("markPrice", 0)),
                    "liquidation_price": float(r.get("liquidationPrice", 0)),
                    "unrealized_pnl": float(r.get("unRealizedProfit", 0)),
                    "leverage": int(r.get("leverage", 1)),
                    "margin_type": r.get("marginType", ""),
                    "isolated_margin": float(r.get("isolatedMargin", 0)),
                })
        return positions
    else:
        # Spot logic: derive from balances
        balances = get_balances()
        positions = []

        # Get current prices
        try:
            prices = {}
            r = requests.get(f"{BASE_URL}{API_PREFIX}/ticker/price", timeout=5)
            if r.status_code == 200:
                for p in r.json():
                    prices[p["symbol"]] = float(p["price"])
        except:
            prices = {}

        for asset, bal in balances.items():
            if bal["free"] > 0 or bal["locked"] > 0:
                symbol = f"{asset}USDT"
                price = prices.get(symbol, 0)
                positions.append({
                    "asset": asset,
                    "free": bal["free"],
                    "locked": bal["locked"],
                    "total": bal["free"] + bal["locked"],
                    "price_usd": price,
                    "value_usd": price * (bal["free"] + bal["locked"])
                })

        return positions


def cancel_order(symbol: str, order_id: int) -> dict:
    params = {"symbol": symbol, "orderId": order_id,
              "timestamp": _ts(), "recvWindow": 10000}
    r = requests.delete(f"{BASE_URL}{API_PREFIX}/order?{_sign(params)}",
                        headers=_headers(), timeout=10)
    return r.json()


def cancel_all_orders(symbol: str = SYMBOL) -> dict:
    params = {"symbol": symbol, "timestamp": _ts(), "recvWindow": 10000}
    r = requests.delete(f"{BASE_URL}{API_PREFIX}/openOrders?{_sign(params)}",
                        headers=_headers(), timeout=10)
    return r.json()


# ═══════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════

def parse_order_response(resp: dict) -> dict:
    """
    Extract key fields from Binance order response.
    Works for both FULL and RESULT response types.
    """
    fills = resp.get("fills", [])

    total_qty = 0.0
    total_cost = 0.0
    total_commission = 0.0
    commission_asset = ""

    for f in fills:
        qty = float(f["qty"])
        price = float(f["price"])
        comm = float(f["commission"])
        total_qty += qty
        total_cost += qty * price
        total_commission += comm
        commission_asset = f.get("commissionAsset", "")

    avg_price = total_cost / total_qty if total_qty > 0 else float(resp.get("price", 0))

    return {
        "order_id": resp.get("orderId"),
        "client_order_id": resp.get("clientOrderId") or resp.get("_client_oid"),
        "symbol": resp.get("symbol"),
        "side": resp.get("side"),
        "type": resp.get("type"),
        "status": resp.get("status"),
        "fill_price": round(avg_price, 8),
        "fill_qty": round(total_qty, 8),
        "commission": round(total_commission, 8),
        "commission_asset": commission_asset,
        "fills_count": len(fills),
        "raw": resp,
    }


def test_connection() -> dict:
    """Full connection test: ping + account + price."""
    result = {}
    result["ping"] = ping()

    try:
        bal = get_balances()
        result["account"] = {"connected": True, "balances": bal}
    except Exception as e:
        result["account"] = {"connected": False, "error": str(e)}

    try:
        p = get_price()
        result["price"] = {SYMBOL: p}
    except Exception as e:
        result["price"] = {"error": str(e)}

    return result


# ═══════════════════════════════════════
# FUTURES SPECIFIC
# ═══════════════════════════════════════

def set_leverage(symbol: str, leverage: int) -> dict:
    """Set leverage for a symbol. Must be called before opening position."""
    params = {"symbol": symbol, "leverage": leverage, "timestamp": _ts(), "recvWindow": 10000}
    r = requests.post(f"{BASE_URL}/fapi/v1/leverage?{_sign(params)}", headers=_headers(), timeout=10)
    return r.json()


def set_margin_type(symbol: str, margin_type: str = "ISOLATED") -> dict:
    """Set margin type for a symbol. ISOLATED or CROSSED."""
    params = {"symbol": symbol, "marginType": margin_type, "timestamp": _ts(), "recvWindow": 10000}
    r = requests.post(f"{BASE_URL}/fapi/v1/marginType?{_sign(params)}", headers=_headers(), timeout=10)
    resp = r.json()
    # Binance returns error -4046 if margin type already set — that's OK
    if resp.get("code") == -4046:
        return {"success": True, "msg": "Already set"}
    return resp


def get_position_risk(symbol: str = None) -> list:
    """Get position risk info including liquidation price, margin ratio, leverage.
    Returns list of position dicts with: symbol, positionAmt, entryPrice, markPrice,
    unRealizedProfit, liquidationPrice, leverage, marginType, isolatedMargin, etc.
    """
    params = {"timestamp": _ts(), "recvWindow": 10000}
    if symbol:
        params["symbol"] = symbol
    r = requests.get(f"{BASE_URL}/fapi/v2/positionRisk?{_sign(params)}", headers=_headers(), timeout=10)
    return r.json() if r.status_code == 200 else []


def get_futures_account() -> dict:
    """Get full futures account info: totalWalletBalance, totalUnrealizedProfit,
    totalMarginBalance, totalInitialMargin, totalMaintainMargin, etc."""
    params = {"timestamp": _ts(), "recvWindow": 10000}
    r = requests.get(f"{BASE_URL}/fapi/v2/account?{_sign(params)}", headers=_headers(), timeout=10)
    return r.json()


def get_funding_rate(symbol: str = SYMBOL, limit: int = 1) -> list:
    """Get funding rate history. Latest first."""
    params = {"symbol": symbol, "limit": limit}
    r = requests.get(f"{BASE_URL}/fapi/v1/fundingRate", params=params, timeout=5)
    return r.json() if r.status_code == 200 else []


def get_mark_price(symbol: str = SYMBOL) -> dict:
    """Get mark price, funding rate, and next funding time."""
    r = requests.get(f"{BASE_URL}/fapi/v1/premiumIndex", params={"symbol": symbol}, timeout=5)
    return r.json() if r.status_code == 200 else {}


def get_futures_balance() -> list:
    """Get futures account balance for all assets."""
    params = {"timestamp": _ts(), "recvWindow": 10000}
    r = requests.get(f"{BASE_URL}/fapi/v2/balance?{_sign(params)}", headers=_headers(), timeout=10)
    return r.json() if r.status_code == 200 else []
