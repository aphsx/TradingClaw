"""
Position Monitor - Real-time position tracking via Redis + Binance
===================================================================
- Stores live position state in Redis for instant dashboard reads
- Periodically syncs with Binance to get actual order status
- Detects SL/TP fills and updates MySQL
- Emits real-time events via Socket.IO
"""
import json
import time
import redis
import traceback
from datetime import datetime
from typing import Optional

from config import SYMBOL
from data import binance_client as bnb
from data.socket_server import emit_balance_update, emit_position_update, emit_equity_update, emit_regime_update

import os
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

_redis = None

def get_redis():
    global _redis
    if _redis is None:
        _redis = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0,
                             decode_responses=True, socket_connect_timeout=5)
    return _redis


# ═══════════════════════════════════════
# REDIS KEYS
# ═══════════════════════════════════════
# pos:open:{pos_id}        → JSON of open position
# pos:open_ids             → SET of open position IDs
# monitor:last_price       → latest price
# monitor:last_check       → timestamp of last sync
# monitor:equity           → current equity snapshot
# monitor:regime           → current regime info
# monitor:status           → "running" / "stopped" / "error"
# monitor:margin_ratio     → current margin ratio
# monitor:funding_rate     → current funding rate per symbol
# monitor:liquidation      → liquidation prices per position


def publish_position_open(pos_id: int, data: dict):
    """Write a new open position to Redis."""
    r = get_redis()
    key = f"pos:open:{pos_id}"
    r.set(key, json.dumps(data, default=str))
    r.sadd("pos:open_ids", pos_id)
    r.publish("positions", json.dumps({"event": "open", "id": pos_id, **data}, default=str))
    
    # Emit position open via Socket.IO
    emit_position_update('open', {"id": pos_id, **data})


def publish_position_close(pos_id: int, data: dict):
    """Mark position as closed in Redis."""
    r = get_redis()
    key = f"pos:open:{pos_id}"
    r.delete(key)
    r.srem("pos:open_ids", pos_id)
    r.publish("positions", json.dumps({"event": "close", "id": pos_id, **data}, default=str))
    
    # Emit position close via Socket.IO
    emit_position_update('close', {"id": pos_id, **data})


def get_open_positions_from_redis() -> list:
    """Get all open positions from Redis (fast, no DB hit)."""
    r = get_redis()
    ids = r.smembers("pos:open_ids")
    positions = []
    for pid in ids:
        data = r.get(f"pos:open:{pid}")
        if data:
            pos = json.loads(data)
            pos["id"] = int(pid)
            positions.append(pos)
    return positions


def get_manual_positions_from_binance() -> list:
    """
    Get manual positions from Binance (not opened by this bot).
    Returns both open orders and current holdings.
    """
    try:
        # Get all open orders
        open_orders = bnb.get_all_open_orders()
        
        # Get account balances/positions
        account_positions = bnb.get_account_positions()
        
        # Get recent trade history (last 24 hours)
        now = int(time.time() * 1000)
        yesterday = now - (24 * 60 * 60 * 1000)
        trade_history = bnb.get_position_history(start_time=yesterday, end_time=now, limit=50)
        
        return {
            "open_orders": open_orders,
            "account_positions": account_positions,
            "recent_trades": trade_history,
            "source": "binance",
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        print(f"⚠️ Error fetching manual positions: {e}")
        return {"open_orders": [], "account_positions": [], "recent_trades": [], "error": str(e)}


def update_price(price: float):
    """Update latest price and recalc unrealized PnL for all open positions."""
    r = get_redis()
    r.set("monitor:last_price", str(price))
    r.set("monitor:last_check", datetime.utcnow().isoformat())

    # Update unrealized PnL for each open position
    positions = get_open_positions_from_redis()
    total_unrealized = 0.0
    for pos in positions:
        entry = float(pos.get("entry_fill_price") or pos.get("entry_price", 0))
        qty = float(pos.get("quantity", 0))
        if pos.get("direction") == "LONG":
            upnl = (price - entry) * qty
        else:
            upnl = (entry - price) * qty
        pos["unrealized_pnl"] = round(upnl, 4)
        pos["current_price"] = price
        pos["pnl_pct"] = round(upnl / (entry * qty) * 100, 2) if entry * qty > 0 else 0
        total_unrealized += upnl
        # Re-save with updated unrealized
        r.set(f"pos:open:{pos['id']}", json.dumps(pos, default=str))
        
        # Emit position update via Socket.IO
        emit_position_update('update', pos)

    return total_unrealized


def update_equity(equity: float, capital: float, unrealized: float, n_open: int):
    r = get_redis()
    data = {
        "equity": round(equity, 2),
        "capital": round(capital, 2),
        "unrealized": round(unrealized, 2),
        "open_positions": n_open,
        "timestamp": datetime.utcnow().isoformat(),
    }
    r.set("monitor:equity", json.dumps(data))
    
    # Emit equity update via Socket.IO
    emit_equity_update(data)


def update_regime(regime_name: str, confidence: float, probs: dict):
    r = get_redis()
    data = {
        "regime": regime_name,
        "confidence": round(confidence, 4),
        "probabilities": probs,
        "timestamp": datetime.utcnow().isoformat(),
    }
    r.set("monitor:regime", json.dumps(data))
    
    # Emit regime update via Socket.IO
    emit_regime_update(data)


def set_status(status: str, message: str = ""):
    r = get_redis()
    r.set("monitor:status", json.dumps({
        "status": status,
        "message": message,
        "timestamp": datetime.utcnow().isoformat(),
    }))


def get_status() -> dict:
    r = get_redis()
    data = r.get("monitor:status")
    return json.loads(data) if data else {"status": "unknown"}


# ═══════════════════════════════════════
# BINANCE SYNC - check if SL/TP orders filled
# ═══════════════════════════════════════

def sync_open_positions_with_binance(db_module) -> list:
    """
    Check each open LIVE position's exit orders on Binance.
    If an SL or TP order has been FILLED, close the position in DB + Redis.
    Returns list of newly closed position IDs.
    """
    closed = []
    positions = get_open_positions_from_redis()

    for pos in positions:
        # Sync LIVE and MANUAL_ADOPTED (both have real SL/TP orders on Binance)
        if pos.get("source") not in ("LIVE", "MANUAL_ADOPTED"):
            continue

        try:
            # Check SL order
            sl_oid = pos.get("sl_order_id")
            if sl_oid:
                sl_status = bnb.get_order(pos["symbol"], int(sl_oid))
                if sl_status.get("status") == "FILLED":
                    _handle_exit_fill(pos, sl_status, "Stop Loss", db_module)
                    closed.append(pos["id"])
                    continue

            # Check TP order
            tp_oid = pos.get("tp_order_id")
            if tp_oid:
                tp_status = bnb.get_order(pos["symbol"], int(tp_oid))
                if tp_status.get("status") == "FILLED":
                    _handle_exit_fill(pos, tp_status, "Take Profit", db_module)
                    closed.append(pos["id"])
                    continue

        except Exception as e:
            print(f"⚠️ Sync error for position {pos.get('id')}: {e}")

    return closed


def _handle_exit_fill(pos: dict, order_resp: dict, reason: str, db_module):
    """Process a filled exit order: update MySQL, remove from Redis, cancel other side."""
    parsed = bnb.parse_order_response(order_resp) if order_resp.get("fills") else {
        "order_id": order_resp.get("orderId"),
        "fill_price": float(order_resp.get("price", 0)),
        "fill_qty": float(order_resp.get("executedQty", 0)),
        "commission": 0,
        "commission_asset": "",
        "status": order_resp.get("status"),
    }

    # Get actual trades for accurate commission
    if parsed.get("order_id"):
        trades = bnb.get_order_trades(pos["symbol"], parsed["order_id"])
        total_comm = sum(float(t.get("commission", 0)) for t in trades)
        comm_asset = trades[0].get("commissionAsset", "") if trades else ""
        avg_price = (sum(float(t["price"]) * float(t["qty"]) for t in trades)
                     / sum(float(t["qty"]) for t in trades)) if trades else parsed.get("fill_price", 0)
        parsed["commission"] = total_comm
        parsed["commission_asset"] = comm_asset
        parsed["fill_price"] = avg_price

    # Calculate PnL
    entry = float(pos.get("entry_fill_price") or pos.get("entry_price", 0))
    exit_p = parsed.get("fill_price", 0)
    qty = float(pos.get("quantity", 0))
    entry_comm = float(pos.get("entry_commission") or 0)
    exit_comm = parsed.get("commission", 0)

    if pos.get("direction") == "LONG":
        raw_pnl = (exit_p - entry) * qty
    else:
        raw_pnl = (entry - exit_p) * qty

    net_pnl = raw_pnl - entry_comm - exit_comm
    pnl_pct = net_pnl / (entry * qty) * 100 if entry * qty > 0 else 0

    # Update MySQL
    db_module.close_position_live(
        position_id=pos["id"],
        exit_price=exit_p,
        exit_time=datetime.utcnow(),
        exit_reason=reason,
        exit_order_id=parsed.get("order_id"),
        exit_client_oid=parsed.get("client_order_id"),
        exit_fill_price=exit_p,
        exit_fill_qty=parsed.get("fill_qty"),
        exit_commission=exit_comm,
        exit_commission_asset=parsed.get("commission_asset"),
        exit_status=parsed.get("status"),
        exit_raw=order_resp,
        pnl=net_pnl,
        pnl_pct=pnl_pct,
        total_fees=entry_comm + exit_comm,
    )

    # Cancel the other side order
    try:
        if reason == "Stop Loss" and pos.get("tp_order_id"):
            bnb.cancel_order(pos["symbol"], int(pos["tp_order_id"]))
        elif reason == "Take Profit" and pos.get("sl_order_id"):
            bnb.cancel_order(pos["symbol"], int(pos["sl_order_id"]))
    except Exception:
        pass

    # Remove from Redis
    publish_position_close(pos["id"], {
        "exit_price": exit_p, "reason": reason,
        "pnl": round(net_pnl, 4), "pnl_pct": round(pnl_pct, 2),
        "commission": round(exit_comm, 6),
    })

    print(f"✅ Position #{pos['id']} closed: {reason} @ ${exit_p:,.2f} "
          f"PnL=${net_pnl:.2f} Fee=${exit_comm:.6f} {parsed.get('commission_asset','')}")


def update_margin_ratio(account_data: dict):
    """Store margin ratio in Redis for dashboard."""
    r = get_redis()
    total_margin = float(account_data.get("totalMaintainMargin", 0))
    total_balance = float(account_data.get("totalMarginBalance", 0))
    ratio = total_margin / total_balance if total_balance > 0 else 0
    data = {
        "margin_ratio": round(ratio, 4),
        "total_wallet": round(float(account_data.get("totalWalletBalance", 0)), 2),
        "total_unrealized": round(float(account_data.get("totalUnrealizedProfit", 0)), 2),
        "total_margin_balance": round(total_balance, 2),
        "total_initial_margin": round(float(account_data.get("totalInitialMargin", 0)), 2),
        "total_maint_margin": round(total_margin, 2),
        "available_balance": round(float(account_data.get("availableBalance", 0)), 2),
        "timestamp": datetime.utcnow().isoformat(),
    }
    r.set("monitor:margin", json.dumps(data))


def update_funding_rates(funding_data: dict):
    """Store funding rates in Redis."""
    r = get_redis()
    r.set("monitor:funding", json.dumps({
        **funding_data,
        "timestamp": datetime.utcnow().isoformat(),
    }))


def cleanup_ghost_positions() -> list:
    """
    Remove Redis positions whose symbol/direction no longer exists on Binance.
    Only checks LIVE and MANUAL_ADOPTED positions.
    Returns list of removed position IDs.
    """
    removed = []
    try:
        from data import binance_client as bnb
        bot_positions = get_open_positions_from_redis()
        if not bot_positions:
            return []

        binance_live = bnb.get_account_positions()   # actual open on Binance
        live_keys = {(p["symbol"], p["direction"]) for p in binance_live}

        for pos in bot_positions:
            if pos.get("source") not in ("LIVE", "MANUAL", "MANUAL_ADOPTED"):
                continue
            key = (pos.get("symbol"), pos.get("direction"))
            if key not in live_keys:
                pid = pos.get("id")
                publish_position_close(int(pid), {
                    "exit_price": 0,
                    "reason":     "Ghost cleanup (not found on Binance)",
                    "pnl":        0,
                })
                removed.append(pid)
                print(f"🧹 Ghost position removed: #{pid} {key}")
    except Exception as e:
        print(f"⚠️ cleanup_ghost_positions: {e}")
    return removed
