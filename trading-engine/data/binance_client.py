"""
Binance Client - Real Order Management
========================================
Places real orders, queries fills, tracks commissions.
Every order response is stored raw in MySQL for audit.
"""
import time
import hmac
import hashlib
import json
import uuid
import requests
from urllib.parse import urlencode
from typing import Optional
from config import API_KEY, SECRET_KEY, BASE_URL, SYMBOL


def _sign(params: dict) -> str:
    q = urlencode(params)
    sig = hmac.new(SECRET_KEY.encode(), q.encode(), hashlib.sha256).hexdigest()
    return q + "&signature=" + sig


def _headers():
    return {"X-MBX-APIKEY": API_KEY}


def _ts():
    return int(time.time() * 1000)


# ═══════════════════════════════════════
# ACCOUNT / INFO
# ═══════════════════════════════════════

def ping() -> bool:
    try:
        r = requests.get(f"{BASE_URL}/api/v3/ping", timeout=5)
        return r.status_code == 200
    except Exception:
        return False


def server_time() -> int:
    r = requests.get(f"{BASE_URL}/api/v3/time", timeout=5)
    return r.json()["serverTime"]


def account_info() -> dict:
    params = {"timestamp": _ts(), "recvWindow": 10000}
    r = requests.get(f"{BASE_URL}/api/v3/account?{_sign(params)}",
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
    r = requests.get(f"{BASE_URL}/api/v3/ticker/price",
                     params={"symbol": symbol}, timeout=5)
    return float(r.json()["price"])


def get_symbol_info(symbol: str = SYMBOL) -> dict:
    """Get trading rules: min qty, step size, tick size, etc."""
    r = requests.get(f"{BASE_URL}/api/v3/exchangeInfo",
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
    r = requests.post(f"{BASE_URL}/api/v3/order?{_sign(params)}",
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
    r = requests.post(f"{BASE_URL}/api/v3/order?{_sign(params)}",
                      headers=_headers(), timeout=10)
    resp = r.json()
    resp["_http_status"] = r.status_code
    resp["_client_oid"] = client_oid
    return resp


def place_stop_loss_order(symbol: str, side: str, quantity: float,
                          stop_price: float) -> dict:
    """Place a STOP_LOSS_LIMIT to act as our SL."""
    client_oid = f"regime_sl_{uuid.uuid4().hex[:12]}"
    # Stop loss limit needs a price slightly worse than stopPrice
    offset = stop_price * 0.001  # 0.1% slippage allowance
    limit_price = stop_price - offset if side == "SELL" else stop_price + offset
    params = {
        "symbol": symbol,
        "side": side,
        "type": "STOP_LOSS_LIMIT",
        "quantity": f"{quantity:.6f}",
        "price": f"{limit_price:.2f}",
        "stopPrice": f"{stop_price:.2f}",
        "timeInForce": "GTC",
        "newClientOrderId": client_oid,
        "newOrderRespType": "FULL",
        "timestamp": _ts(),
        "recvWindow": 10000,
    }
    r = requests.post(f"{BASE_URL}/api/v3/order?{_sign(params)}",
                      headers=_headers(), timeout=10)
    resp = r.json()
    resp["_http_status"] = r.status_code
    resp["_client_oid"] = client_oid
    return resp


def place_take_profit_order(symbol: str, side: str, quantity: float,
                            stop_price: float) -> dict:
    client_oid = f"regime_tp_{uuid.uuid4().hex[:12]}"
    offset = stop_price * 0.001
    limit_price = stop_price + offset if side == "SELL" else stop_price - offset
    params = {
        "symbol": symbol,
        "side": side,
        "type": "TAKE_PROFIT_LIMIT",
        "quantity": f"{quantity:.6f}",
        "price": f"{limit_price:.2f}",
        "stopPrice": f"{stop_price:.2f}",
        "timeInForce": "GTC",
        "newClientOrderId": client_oid,
        "newOrderRespType": "FULL",
        "timestamp": _ts(),
        "recvWindow": 10000,
    }
    r = requests.post(f"{BASE_URL}/api/v3/order?{_sign(params)}",
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
    r = requests.get(f"{BASE_URL}/api/v3/order?{_sign(params)}",
                     headers=_headers(), timeout=10)
    return r.json()


def get_order_trades(symbol: str, order_id: int) -> list:
    """Get individual fills/trades for an order."""
    params = {"symbol": symbol, "orderId": order_id,
              "timestamp": _ts(), "recvWindow": 10000}
    r = requests.get(f"{BASE_URL}/api/v3/myTrades?{_sign(params)}",
                     headers=_headers(), timeout=10)
    return r.json() if r.status_code == 200 else []


def get_open_orders(symbol: str = SYMBOL) -> list:
    params = {"symbol": symbol, "timestamp": _ts(), "recvWindow": 10000}
    r = requests.get(f"{BASE_URL}/api/v3/openOrders?{_sign(params)}",
                     headers=_headers(), timeout=10)
    return r.json() if r.status_code == 200 else []


def cancel_order(symbol: str, order_id: int) -> dict:
    params = {"symbol": symbol, "orderId": order_id,
              "timestamp": _ts(), "recvWindow": 10000}
    r = requests.delete(f"{BASE_URL}/api/v3/order?{_sign(params)}",
                        headers=_headers(), timeout=10)
    return r.json()


def cancel_all_orders(symbol: str = SYMBOL) -> dict:
    params = {"symbol": symbol, "timestamp": _ts(), "recvWindow": 10000}
    r = requests.delete(f"{BASE_URL}/api/v3/openOrders?{_sign(params)}",
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
