"""
CCXT Client — Drop-in Binance order executor
=============================================
Replaces raw HTTP calls in binance_client.py with CCXT.

Why CCXT?
  fetchOrder()     → order_id, status, filled, remaining, timestamp [OK]
  fetchMyTrades()  → trade_id, order_id, real fill price, real fee, cost [OK]
  createOrder()    → place market/limit/SL/TP orders [OK]
  fetchBalance()   → wallet balances [OK]
  fetchTicker()    → current price [OK]

Public API (same names as binance_client.py for drop-in use):
  place_market_order(symbol, side, quantity, reduce_only=False) → parsed dict
  place_limit_order(symbol, side, quantity, price) → parsed dict
  place_stop_loss_order(symbol, side, quantity, stop_price) → parsed dict
  place_take_profit_order(symbol, side, quantity, stop_price) → parsed dict
  fetch_order(symbol, order_id) → parsed dict
  fetch_my_trades(symbol, order_id, limit) → list of trade dicts
  get_balance() → dict  (usdt_free, usdt_total, …)
  get_price(symbol) → float
  cancel_order(symbol, order_id) → dict
  cancel_all_orders(symbol) → list
  get_account_positions() → list  (futures positionRisk equivalent)
  parse_order_response(resp) → standardised dict  (backward-compat)

CCXT-specific extras:
  enrich_order_with_trades(symbol, order_id) → fills from fetchMyTrades
"""
from __future__ import annotations

import time
import uuid
import logging
from typing import Optional
from urllib.parse import urlparse

import ccxt

from config import API_KEY, SECRET_KEY, USE_TESTNET, USE_FUTURES, SYMBOL, BINANCE_FUTURES_BASE_URL

log = logging.getLogger(__name__)

# ─── Build CCXT exchange instance ────────────────────────────────────────────

def _build_exchange() -> ccxt.Exchange:
    options: dict = {
        'defaultType': 'future' if USE_FUTURES else 'spot',
        'adjustForTimeDifference': True,   # auto-sync server clock
    }

    # Spot-only sandbox. Futures sandbox/testnet is deprecated by Binance/CCXT.
    if USE_TESTNET and not USE_FUTURES:
        options['sandboxMode'] = True

    exchange = ccxt.binance({
        'apiKey': API_KEY,
        'secret': SECRET_KEY,
        'options': options,
        'enableRateLimit': True,
    })

    # Enable sandbox (testnet) URLs for spot only.
    if USE_TESTNET and not USE_FUTURES:
        exchange.set_sandbox_mode(True)

    if USE_FUTURES:
        _apply_custom_futures_urls(exchange, BINANCE_FUTURES_BASE_URL)

    return exchange


def _apply_custom_futures_urls(exchange: ccxt.Exchange, base_url: str) -> None:
    """Rewrite all CCXT futures endpoints to a custom base URL (e.g. demo trading)."""
    try:
        target_host = urlparse(base_url).netloc.lower()
        if not target_host:
            return
    except Exception:
        return

    api_urls = exchange.urls.get('api')
    if not isinstance(api_urls, dict):
        return

    def _rewrite(obj):
        if isinstance(obj, str):
            if 'fapi.binance.com' in obj:
                return obj.replace('https://fapi.binance.com', base_url.rstrip('/'))
            return obj
        if isinstance(obj, dict):
            return {k: _rewrite(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_rewrite(v) for v in obj]
        return obj

    exchange.urls['api'] = _rewrite(api_urls)


# Singleton (lazy init so import doesn't blow up without network)
_exchange: Optional[ccxt.Exchange] = None

def get_exchange() -> ccxt.Exchange:
    global _exchange
    if _exchange is None:
        _exchange = _build_exchange()
    return _exchange


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _ccxt_symbol(symbol: str) -> str:
    """Convert 'BTCUSDT' → 'BTC/USDT' or 'BTC/USDT:USDT' for futures."""
    if '/' in symbol:
        return symbol
    base = symbol[:-4]   # strip 'USDT'
    if USE_FUTURES:
        return f"{base}/USDT:USDT"
    return f"{base}/USDT"


def _safe_float(v, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


# ─── Parse order → standardised dict ─────────────────────────────────────────

def parse_order_response(resp: dict) -> dict:
    """
    Normalise a CCXT order dict (or the raw Binance dict we store in _raw)
    into the same shape that main.py + database.py expect.

    Keys produced:
      order_id, client_order_id, symbol, side, type, status,
      fill_price, fill_qty, commission, commission_asset, fills_count, raw

    Idempotent: if resp is already parsed (has 'fill_price') it is returned as-is.
    """
    # Already parsed — pass through (idempotent call from main.py after place_*_order)
    if 'fill_price' in resp and 'order_id' in resp:
        return resp

    # If called with a raw Binance dict (backward compat) delegate to legacy parser
    if 'orderId' in resp or '_http_status' in resp:
        return _parse_binance_raw(resp)

    # CCXT-normalised order
    filled    = _safe_float(resp.get('filled'))
    cost      = _safe_float(resp.get('cost'))
    avg_price = (cost / filled) if filled > 0 else _safe_float(resp.get('average') or resp.get('price'))

    # Commission from trades (may be attached by enrich_order_with_trades)
    trades    = resp.get('_trades', [])
    commission      = sum(_safe_float(t.get('fee', {}).get('cost')) for t in trades)
    commission_asset = (trades[0].get('fee', {}).get('currency') or 'USDT') if trades else 'USDT'

    return {
        'order_id':         resp.get('id') or resp.get('orderId'),
        'client_order_id':  resp.get('clientOrderId') or resp.get('info', {}).get('clientOrderId'),
        'symbol':           resp.get('symbol'),
        'side':             (resp.get('side') or '').upper(),
        'type':             (resp.get('type') or '').upper(),
        'status':           (resp.get('status') or '').upper(),
        'fill_price':       round(avg_price, 8),
        'fill_qty':         round(filled, 8),
        'commission':       round(commission, 8),
        'commission_asset': commission_asset,
        'fills_count':      len(trades),
        'raw':              resp,
    }


def _parse_binance_raw(resp: dict) -> dict:
    """Legacy parser for raw Binance HTTP responses (backward compat)."""
    fills = resp.get('fills', [])
    total_qty = total_cost = total_comm = 0.0
    comm_asset = ''
    for f in fills:
        qty = float(f.get('qty', 0))
        price = float(f.get('price', 0))
        total_qty  += qty
        total_cost += qty * price
        total_comm += float(f.get('commission', 0))
        comm_asset  = f.get('commissionAsset', '')
    avg_price = total_cost / total_qty if total_qty > 0 else float(resp.get('price', 0) or 0)
    return {
        'order_id':         resp.get('orderId'),
        'client_order_id':  resp.get('clientOrderId') or resp.get('_client_oid'),
        'symbol':           resp.get('symbol'),
        'side':             (resp.get('side') or '').upper(),
        'type':             (resp.get('type') or '').upper(),
        'status':           (resp.get('status') or '').upper(),
        'fill_price':       round(avg_price, 8),
        'fill_qty':         round(total_qty, 8),
        'commission':       round(total_comm, 8),
        'commission_asset': comm_asset,
        'fills_count':      len(fills),
        'raw':              resp,
    }


# ─── Order placement ─────────────────────────────────────────────────────────

def place_market_order(symbol: str, side: str, quantity: float,
                       reduce_only: bool = False) -> dict:
    """
    Place a MARKET order, then fetch real fills via fetchMyTrades.
    Returns parse_order_response()-compatible dict.
    """
    ex = get_exchange()
    sym = _ccxt_symbol(symbol)
    params: dict = {'newOrderRespType': 'FULL'}
    if reduce_only and USE_FUTURES:
        params['reduceOnly'] = True

    try:
        order = ex.create_order(sym, 'market', side.lower(), quantity, params=params)
        # Enrich with real trade fills (fees, exact prices)
        order = enrich_order_with_trades(symbol, order['id'], order)
        parsed = parse_order_response(order)
        log.info(f"Market {side} {quantity} {symbol} → fill={parsed['fill_price']} "
                 f"fee={parsed['commission']} {parsed['commission_asset']}")
        return parsed
    except ccxt.BaseError as e:
        log.error(f"place_market_order error: {e}")
        return {'error': str(e), 'fill_price': 0, 'fill_qty': 0, 'commission': 0,
                'commission_asset': 'USDT', 'status': 'FAILED', 'raw': {}}


def place_limit_order(symbol: str, side: str, quantity: float, price: float,
                      time_in_force: str = 'GTC') -> dict:
    ex = get_exchange()
    sym = _ccxt_symbol(symbol)
    params = {'timeInForce': time_in_force, 'newOrderRespType': 'FULL'}
    try:
        order = ex.create_order(sym, 'limit', side.lower(), quantity, price, params=params)
        return parse_order_response(order)
    except ccxt.BaseError as e:
        log.error(f"place_limit_order error: {e}")
        return {'error': str(e), 'fill_price': 0, 'status': 'FAILED', 'raw': {}}


def place_stop_loss_order(symbol: str, side: str, quantity: float,
                          stop_price: float) -> dict:
    ex = get_exchange()
    sym = _ccxt_symbol(symbol)
    if USE_FUTURES:
        params = {'stopPrice': stop_price, 'closePosition': False, 'newOrderRespType': 'FULL'}
        order_type = 'STOP_MARKET'
    else:
        params = {'stopPrice': stop_price, 'timeInForce': 'GTC', 'newOrderRespType': 'FULL'}
        order_type = 'stop_loss_limit'
        # Limit price slightly worse than stop
        stop_price_limit = stop_price * (0.999 if side.upper() == 'SELL' else 1.001)
        try:
            order = ex.create_order(sym, order_type, side.lower(), quantity,
                                    round(stop_price_limit, 2), params=params)
            return parse_order_response(order)
        except ccxt.BaseError as e:
            log.error(f"place_stop_loss_order (spot) error: {e}")
            return {'error': str(e), 'fill_price': 0, 'status': 'FAILED', 'raw': {}}

    try:
        # Futures STOP_MARKET uses createOrder with stopPrice
        order = ex.create_order(sym, 'stop_market', side.lower(), quantity, params=params)
        return parse_order_response(order)
    except ccxt.BaseError as e:
        log.error(f"place_stop_loss_order (futures) error: {e}")
        return {'error': str(e), 'fill_price': 0, 'status': 'FAILED', 'raw': {}}


def place_take_profit_order(symbol: str, side: str, quantity: float,
                            stop_price: float) -> dict:
    ex = get_exchange()
    sym = _ccxt_symbol(symbol)
    if USE_FUTURES:
        params = {'stopPrice': stop_price, 'closePosition': False, 'newOrderRespType': 'FULL'}
        try:
            order = ex.create_order(sym, 'take_profit_market', side.lower(), quantity, params=params)
            return parse_order_response(order)
        except ccxt.BaseError as e:
            log.error(f"place_take_profit_order (futures) error: {e}")
            return {'error': str(e), 'fill_price': 0, 'status': 'FAILED', 'raw': {}}
    else:
        params = {'stopPrice': stop_price, 'timeInForce': 'GTC', 'newOrderRespType': 'FULL'}
        stop_price_limit = stop_price * (1.001 if side.upper() == 'SELL' else 0.999)
        try:
            order = ex.create_order(sym, 'take_profit_limit', side.lower(), quantity,
                                    round(stop_price_limit, 2), params=params)
            return parse_order_response(order)
        except ccxt.BaseError as e:
            log.error(f"place_take_profit_order (spot) error: {e}")
            return {'error': str(e), 'fill_price': 0, 'status': 'FAILED', 'raw': {}}


# ─── Fetch order & trades ────────────────────────────────────────────────────

def fetch_order(symbol: str, order_id) -> dict:
    """
    Fetch order details by ID.
    Returns parse_order_response()-compatible dict.
    """
    ex = get_exchange()
    sym = _ccxt_symbol(symbol)
    try:
        order = ex.fetch_order(str(order_id), sym)
        order = enrich_order_with_trades(symbol, order_id, order)
        return parse_order_response(order)
    except ccxt.BaseError as e:
        log.error(f"fetch_order error: {e}")
        return {'error': str(e), 'order_id': order_id}


def fetch_my_trades(symbol: str, order_id=None, limit: int = 50) -> list[dict]:
    """
    Fetch recent trade fills via CCXT fetchMyTrades.
    If order_id given, filters to only that order's fills.

    Each item contains:
      trade_id, order_id, side, price, qty, cost, fee_cost, fee_currency, timestamp
    """
    ex = get_exchange()
    sym = _ccxt_symbol(symbol)
    try:
        trades = ex.fetch_my_trades(sym, limit=limit)
        result = []
        for t in trades:
            if order_id and str(t.get('order')) != str(order_id):
                continue
            result.append({
                'trade_id':      t.get('id'),
                'order_id':      t.get('order'),
                'symbol':        symbol,
                'side':          (t.get('side') or '').upper(),
                'price':         _safe_float(t.get('price')),
                'qty':           _safe_float(t.get('amount')),
                'cost':          _safe_float(t.get('cost')),
                'fee_cost':      _safe_float((t.get('fee') or {}).get('cost')),
                'fee_currency':  (t.get('fee') or {}).get('currency', 'USDT'),
                'timestamp':     t.get('timestamp'),
                'datetime':      t.get('datetime'),
                'raw':           t,
            })
        return result
    except ccxt.BaseError as e:
        log.error(f"fetch_my_trades error: {e}")
        return []


def enrich_order_with_trades(symbol: str, order_id, order: dict) -> dict:
    """
    Attach real trade fills to an order dict.
    Waits briefly for fills to settle on Binance, then calls fetchMyTrades.
    Returns the order dict with '_trades' key added.
    """
    if order.get('_trades'):
        return order  # already enriched

    # Brief wait for fills to settle (Binance usually fills instantly for market orders)
    time.sleep(0.3)
    try:
        trades = fetch_my_trades(symbol, order_id=order_id, limit=20)
        order['_trades'] = trades
    except Exception as e:
        log.warning(f"enrich_order_with_trades: {e}")
        order['_trades'] = []
    return order


# ─── Account info ────────────────────────────────────────────────────────────

def get_balance() -> dict:
    """
    Fetch account balance. Returns normalised dict:
      usdt_free, usdt_total, usdt_locked, margin_balance, available_balance,
      unrealized_pnl, margin_ratio, balances
    """
    ex = get_exchange()
    try:
        bal = ex.fetch_balance()
        usdt = bal.get('USDT', {})
        info  = bal.get('info', {})

        if USE_FUTURES:
            # For futures, totalMarginBalance and available come from account info
            total_mb  = _safe_float(info.get('totalMarginBalance') or usdt.get('total'))
            available = _safe_float(info.get('availableBalance')   or usdt.get('free'))
            unrealised = _safe_float(info.get('totalUnrealizedProfit'))
            maint_margin = _safe_float(info.get('totalMaintMargin'))
            margin_ratio = maint_margin / total_mb if total_mb > 0 else 0.0
            return {
                'usdt_free':        available,
                'usdt_locked':      _safe_float(usdt.get('used')),
                'usdt_total':       _safe_float(usdt.get('total')),
                'margin_balance':   total_mb,
                'available_balance': available,
                'unrealized_pnl':   unrealised,
                'margin_ratio':     margin_ratio,
                'balances':         {k: v for k, v in bal.items()
                                     if isinstance(v, dict) and _safe_float(v.get('total')) > 0},
                'account_type':     'FUTURES',
            }
        else:
            return {
                'usdt_free':    _safe_float(usdt.get('free')),
                'usdt_locked':  _safe_float(usdt.get('used')),
                'usdt_total':   _safe_float(usdt.get('total')),
                'balances':     {k: v for k, v in bal.items()
                                 if isinstance(v, dict) and _safe_float(v.get('total')) > 0},
                'account_type': 'SPOT',
            }
    except ccxt.BaseError as e:
        log.error(f"get_balance error: {e}")
        return {'error': str(e), 'usdt_free': 0, 'usdt_total': 0}


def get_price(symbol: str = SYMBOL) -> float:
    """Fetch current mid-price for symbol."""
    ex = get_exchange()
    sym = _ccxt_symbol(symbol)
    try:
        ticker = ex.fetch_ticker(sym)
        return _safe_float(ticker.get('last') or ticker.get('close') or ticker.get('bid'))
    except ccxt.BaseError as e:
        log.error(f"get_price error: {e}")
        return 0.0


def get_account_positions() -> list[dict]:
    """
    Fetch open futures positions (equivalent to /fapi/v2/positionRisk).
    Returns list of position dicts with: symbol, direction, quantity,
    entry_price, mark_price, unrealized_pnl, leverage, margin_type.
    """
    if not USE_FUTURES:
        return []
    ex = get_exchange()
    try:
        positions = ex.fetch_positions()
        result = []
        for p in positions:
            qty = _safe_float(p.get('contracts') or p.get('contractSize'))
            notional = _safe_float(p.get('notional'))
            if abs(qty) < 1e-8 and abs(notional) < 0.01:
                continue  # skip zero positions

            side_sign = p.get('side', '')   # 'long' or 'short'
            direction = 'LONG' if side_sign == 'long' else 'SHORT'

            info = p.get('info', {})
            result.append({
                'symbol':         p.get('symbol', '').replace('/', '').replace(':USDT', ''),
                'direction':      direction,
                'quantity':       abs(qty),
                'entry_price':    _safe_float(p.get('entryPrice')),
                'mark_price':     _safe_float(p.get('markPrice')),
                'unrealized_pnl': _safe_float(p.get('unrealizedPnl')),
                'leverage':       _safe_float(p.get('leverage')),
                'margin_type':    info.get('marginType', 'cross'),
                'notional':       abs(notional),
            })
        return result
    except ccxt.BaseError as e:
        log.error(f"get_account_positions error: {e}")
        return []


def cancel_order(symbol: str, order_id) -> dict:
    ex = get_exchange()
    sym = _ccxt_symbol(symbol)
    try:
        return ex.cancel_order(str(order_id), sym)
    except ccxt.BaseError as e:
        log.error(f"cancel_order error: {e}")
        return {'error': str(e)}


def cancel_all_orders(symbol: str = SYMBOL) -> list:
    ex = get_exchange()
    sym = _ccxt_symbol(symbol)
    try:
        return ex.cancel_all_orders(sym)
    except ccxt.BaseError as e:
        log.error(f"cancel_all_orders error: {e}")
        return []


def get_order(symbol: str, order_id) -> dict:
    """
    Fetch a single order by ID — used by monitor.py for SL/TP fill detection.
    Returns a dict with CCXT fields + Binance-compat 'status', 'orderId' aliases.
    """
    ex = get_exchange()
    sym = _ccxt_symbol(symbol)
    try:
        order = ex.fetch_order(str(order_id), sym)
        # Mirror Binance raw field names so monitor.py works unchanged
        info = order.get('info', {})
        return {
            'orderId':     order.get('id'),
            'status':      (info.get('status') or order.get('status', '')).upper(),
            'executedQty': str(order.get('filled', 0)),
            'price':       str(order.get('average') or order.get('price') or 0),
            'fills':       [],   # enriched separately via get_order_trades
            **order,             # keep all CCXT fields
        }
    except ccxt.BaseError as e:
        log.error(f"get_order error: {e}")
        return {}


def get_order_trades(symbol: str, order_id) -> list:
    """
    Fetch individual fills for an order — used by monitor.py for accurate commission.
    Returns Binance-compat list of {price, qty, commission, commissionAsset}.
    """
    trades = fetch_my_trades(symbol, order_id=order_id, limit=20)
    # Re-map to Binance field names expected by monitor.py
    return [
        {
            'price':           str(t['price']),
            'qty':             str(t['qty']),
            'commission':      str(t['fee_cost']),
            'commissionAsset': t['fee_currency'],
            'id':              t['trade_id'],
            'orderId':         t['order_id'],
        }
        for t in trades
    ]


def ping() -> bool:
    """Check connectivity to Binance."""
    try:
        get_exchange().fetch_time()
        return True
    except Exception:
        return False


def server_time() -> int:
    """Return Binance server time in ms."""
    try:
        return get_exchange().fetch_time()
    except Exception:
        return int(time.time() * 1000)


# ─── OHLCV ───────────────────────────────────────────────────────────────────

def get_klines(symbol: str = SYMBOL, interval: str = '1h', limit: int = 200) -> list:
    """Fetch OHLCV bars via CCXT."""
    ex = get_exchange()
    sym = _ccxt_symbol(symbol)
    tf_map = {'1m': '1m', '5m': '5m', '15m': '15m', '1h': '1h', '4h': '4h', '1d': '1d'}
    tf = tf_map.get(interval, interval)
    try:
        return ex.fetch_ohlcv(sym, tf, limit=limit)
    except ccxt.BaseError as e:
        log.error(f"get_klines error: {e}")
        return []


# ─── Functions not natively in CCXT — shim for drop-in compat ───────────────

def get_usdt_balance() -> float:
    """Return USDT free balance."""
    bal = get_balance()
    return _safe_float(bal.get('usdt_free'))


def get_mark_price(symbol: str = SYMBOL) -> dict:
    """
    Return mark price dict with markPrice, lastFundingRate, nextFundingTime.
    Delegates to raw binance_client (uses /fapi/v1/premiumIndex) since CCXT
    doesn't expose funding rate in a standard way.
    Falls back to a float-only dict if binance_client fails.
    """
    try:
        import data.binance_client as _raw
        result = _raw.get_mark_price(symbol)
        if result:
            return result
    except Exception:
        pass
    # Fallback: price only
    price = get_price(symbol)
    return {'markPrice': str(price), 'lastFundingRate': '0', 'nextFundingTime': 0}


def test_connection() -> dict:
    """Quick connectivity + balance check. Used at startup."""
    try:
        t = server_time()
        bal = get_balance()
        return {
            'ping': True,
            'server_time': t,
            'account': {
                'connected': True,
                'balances': bal.get('balances', {}),
                'usdt_free': bal.get('usdt_free', 0),
            },
        }
    except Exception as e:
        return {'ping': False, 'error': str(e), 'account': {'connected': False}}


def set_leverage(symbol: str, leverage: int) -> dict:
    """Set futures leverage via CCXT."""
    ex = get_exchange()
    sym = _ccxt_symbol(symbol)
    try:
        return ex.set_leverage(leverage, sym)
    except ccxt.BaseError as e:
        log.warning(f"set_leverage {symbol} x{leverage}: {e}")
        return {'error': str(e)}


def set_margin_type(symbol: str, margin_type: str) -> dict:
    """Set futures margin type (ISOLATED / CROSSED) via CCXT."""
    ex = get_exchange()
    sym = _ccxt_symbol(symbol)
    ccxt_margin = 'isolated' if margin_type.upper() == 'ISOLATED' else 'cross'
    try:
        return ex.set_margin_mode(ccxt_margin, sym)
    except ccxt.BaseError as e:
        # -4046 = already that margin type — safe to ignore
        if '-4046' in str(e) or 'No need to change' in str(e):
            return {'status': 'already_set', 'margin_type': margin_type}
        log.warning(f"set_margin_type {symbol} {margin_type}: {e}")
        return {'error': str(e)}


def get_position_risk(symbol: str = SYMBOL) -> list:
    """Futures positionRisk equivalent — delegates to get_account_positions."""
    positions = get_account_positions()
    sym_clean = symbol.replace('/', '').replace(':USDT', '')
    return [p for p in positions if p.get('symbol') == sym_clean]


def get_futures_account() -> dict:
    """Return futures account summary (balance + positions)."""
    bal = get_balance()
    positions = get_account_positions()
    return {
        'totalMarginBalance':    bal.get('margin_balance', 0),
        'availableBalance':      bal.get('available_balance', 0),
        'totalUnrealizedProfit': bal.get('unrealized_pnl', 0),
        'positions':             positions,
    }


# ─── Open Orders & Trade History ─────────────────────────────────────────────

def get_all_open_orders(symbol: str = None) -> list:
    """
    Fetch all open orders (across all symbols or for a specific symbol).
    Returns list of CCXT order dicts.
    """
    ex = get_exchange()
    sym = _ccxt_symbol(symbol) if symbol else None
    try:
        if sym:
            return ex.fetch_open_orders(sym)
        else:
            return ex.fetch_open_orders()
    except ccxt.BaseError as e:
        log.error(f"get_all_open_orders error: {e}")
        return []


def get_position_history(symbol: str = None, start_time: int = None,
                         end_time: int = None, limit: int = 100) -> list:
    """
    Fetch recent trade history (filled orders).
    Mirrors binance_client.get_position_history — returns Binance-compat trade dicts.
    start_time / end_time in milliseconds.
    """
    ex = get_exchange()
    sym = _ccxt_symbol(symbol) if symbol else _ccxt_symbol(SYMBOL)
    try:
        trades = ex.fetch_my_trades(sym, since=start_time, limit=limit)
        result = []
        for t in trades:
            ts = t.get('timestamp', 0)
            if end_time and ts > end_time:
                continue
            result.append({
                'symbol':          symbol or SYMBOL,
                'id':              t.get('id'),
                'orderId':         t.get('order'),
                'side':            (t.get('side') or '').upper(),
                'price':           str(_safe_float(t.get('price'))),
                'qty':             str(_safe_float(t.get('amount'))),
                'quoteQty':        str(_safe_float(t.get('cost'))),
                'commission':      str(_safe_float((t.get('fee') or {}).get('cost'))),
                'commissionAsset': (t.get('fee') or {}).get('currency', 'USDT'),
                'time':            ts,
                'realizedPnl':     str(_safe_float(t.get('info', {}).get('realizedPnl'))),
                'raw':             t,
            })
        return result
    except ccxt.BaseError as e:
        log.error(f"get_position_history error: {e}")
        return []


# ─── Funding Rate ────────────────────────────────────────────────────────────

def get_funding_rate(symbol: str = SYMBOL, limit: int = 1) -> list:
    """
    Fetch funding rate history via CCXT fetch_funding_rate_history.
    Returns list of dicts with Binance-compatible keys:
      fundingTime (ms), fundingRate (str), symbol (str)
    """
    ex = get_exchange()
    sym = _ccxt_symbol(symbol)
    try:
        history = ex.fetch_funding_rate_history(sym, limit=limit)
        result = []
        for r in history:
            result.append({
                'symbol':      symbol,
                'fundingTime': r.get('timestamp', 0),
                'fundingRate': str(r.get('fundingRate', 0)),
            })
        return result
    except ccxt.BaseError as e:
        log.error(f"get_funding_rate error: {e}")
        # Fallback to raw binance_client
        try:
            import data.binance_client as _raw
            return _raw.get_funding_rate(symbol, limit)
        except Exception:
            return []


# ─── OI / Long-Short Ratio — no CCXT support, delegate to binance_client ─────

def get_open_interest(symbol: str = SYMBOL) -> dict:
    """Thin wrapper so ccxt_client is fully drop-in for callers that use bnb directly."""
    try:
        import data.binance_client as _raw
        return _raw.get_open_interest(symbol)
    except Exception:
        return {}


def get_long_short_ratio(symbol: str = SYMBOL, period: str = '5m') -> dict:
    try:
        import data.binance_client as _raw
        return _raw.get_long_short_ratio(symbol, period)
    except Exception:
        return {}
