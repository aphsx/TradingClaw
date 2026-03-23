"""
HTTP API Server
================
Port 8081 — exposes trading engine data to the Next.js dashboard.

Endpoints:
  GET  /health
  GET  /manual-positions    — all Binance positions + bot Redis positions
  GET  /sync-binance        — sync Binance positions to bot (import unmanaged)
  GET  /cleanup-ghosts      — remove stale Redis positions not on Binance
  POST /adopt-position      — let bot manage a manually-opened Binance position
  POST /close-position      — close a position via Binance market order
"""
import json
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
import threading

import data.ccxt_client as bnb    # CCXT: place_market_order, get_account_positions, get_price
from data.monitor import (
    get_open_positions_from_redis,
    publish_position_open,
    publish_position_close,
    cleanup_ghost_positions as _cleanup_ghost_positions,
)


class RequestHandler(BaseHTTPRequestHandler):

    # ── CORS helper ────────────────────────────────────────────────────────────
    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def _json(self, code: int, body: dict):
        data = json.dumps(body, default=str).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self._cors()
        self.end_headers()
        self.wfile.write(data)

    def _read_body(self) -> dict:
        length = int(self.headers.get('Content-Length', 0))
        return json.loads(self.rfile.read(length)) if length else {}

    def log_message(self, *args):
        pass  # suppress access log noise

    # ── OPTIONS (preflight) ────────────────────────────────────────────────────
    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    # ══════════════════════════════════════════════════════════════════════════
    # GET
    # ══════════════════════════════════════════════════════════════════════════
    def do_GET(self):
        try:
            if self.path == '/health':
                self._json(200, {'status': 'ok'})

            elif self.path == '/balance':
                bal = bnb.get_balance()
                self._json(200, bal)

            elif self.path == '/manual-positions':
                bot_positions = get_open_positions_from_redis()
                binance_positions = bnb.get_account_positions()   # /fapi/v2/positionRisk

                # Tag each Binance position: is the bot already managing it?
                bot_keys = {
                    (p.get('symbol'), p.get('direction'))
                    for p in bot_positions
                }
                for pos in binance_positions:
                    key = (pos.get('symbol'), pos.get('direction'))
                    pos['bot_managed'] = key in bot_keys
                    pos['bot_position_id'] = next(
                        (p.get('id') for p in bot_positions
                         if p.get('symbol') == pos['symbol']
                         and p.get('direction') == pos['direction']),
                        None,
                    )

                self._json(200, {
                    'bot_positions': bot_positions,
                    'binance_positions': binance_positions,
                    'timestamp': datetime.utcnow().isoformat(),
                })

            elif self.path == '/cleanup-ghosts':
                removed = _cleanup_ghost_positions()
                self._json(200, {'removed': removed})

            elif self.path == '/sync-binance':
                # Import all unmanaged Binance positions to bot
                bot_positions = get_open_positions_from_redis()
                binance_positions = bnb.get_account_positions()

                bot_keys = {
                    (p.get('symbol'), p.get('direction'))
                    for p in bot_positions
                }

                imported = []
                for pos in binance_positions:
                    key = (pos.get('symbol'), pos.get('direction'))
                    if key not in bot_keys and float(pos.get('quantity', 0)) > 0:
                        # Import this position
                        pos_id = _import_binance_position(pos)
                        imported.append({
                            'position_id': pos_id,
                            'symbol': pos['symbol'],
                            'direction': pos['direction'],
                            'quantity': pos['quantity'],
                            'entry_price': pos['entry_price'],
                        })

                self._json(200, {
                    'imported': imported,
                    'count': len(imported),
                    'message': f'Imported {len(imported)} position(s)'
                })

            else:
                self._json(404, {'error': 'Not found'})

        except Exception as e:
            self._json(500, {'error': str(e)})

    # ══════════════════════════════════════════════════════════════════════════
    # POST
    # ══════════════════════════════════════════════════════════════════════════
    def do_POST(self):
        try:
            body = self._read_body()

            # ── /close-position ──────────────────────────────────────────────
            if self.path == '/close-position':
                symbol    = body.get('symbol', '')
                direction = body.get('direction', '')
                quantity  = float(body.get('quantity', 0))
                pos_id    = body.get('position_id')

                if not symbol or not direction or quantity <= 0:
                    return self._json(400, {'error': 'symbol / direction / quantity required'})

                close_side = 'SELL' if direction == 'LONG' else 'BUY'
                order = bnb.place_market_order(
                    symbol, close_side, quantity, reduce_only=True
                )

                if pos_id is not None:
                    try:
                        price = bnb.get_price(symbol)
                        publish_position_close(int(pos_id), {
                            'exit_price': price,
                            'reason': 'Manual Close (Dashboard)',
                            'pnl': 0,
                        })
                    except Exception:
                        pass

                self._json(200, {'success': True, 'order': order})

            # ── /test-order ──────────────────────────────────────────────────
            elif self.path == '/test-order':
                symbol   = body.get('symbol', 'BTCUSDT')
                side     = body.get('side', 'BUY')
                quantity = float(body.get('quantity', 0.001))
                
                order = bnb.place_market_order(symbol, side, quantity)
                if order.get('status') == 'FAILED':
                    return self._json(400, {'error': order.get('error', 'Trade failed')})
                self._json(200, {'success': True, 'order': order})

            # ── /adopt-position ──────────────────────────────────────────────
            elif self.path == '/adopt-position':
                symbol      = body.get('symbol', '')
                direction   = body.get('direction', '')
                quantity    = float(body.get('quantity', 0))
                entry_price = float(body.get('entry_price', 0))
                confidence  = float(body.get('confidence', 0.5))

                if not symbol or not direction or quantity <= 0 or entry_price <= 0:
                    return self._json(400, {
                        'error': 'symbol / direction / quantity / entry_price required'
                    })

                # Simple default SL/TP: 2 % SL, 4 % TP (2 R), 6 % TP2 (3 R)
                if direction == 'LONG':
                    stop_loss    = round(entry_price * 0.98, 2)
                    take_profit  = round(entry_price * 1.04, 2)
                    take_profit2 = round(entry_price * 1.06, 2)
                else:
                    stop_loss    = round(entry_price * 1.02, 2)
                    take_profit  = round(entry_price * 0.96, 2)
                    take_profit2 = round(entry_price * 0.94, 2)

                # Save to DB
                import data.database as db
                now = datetime.utcnow()
                pos_id = db.open_position_live(
                    signal_id=None, symbol=symbol,
                    direction=direction, strategy='MANUAL_ADOPTED',
                    regime=0, entry_price=entry_price,
                    entry_time=now, quantity=quantity,
                    order_data={'fill_price': entry_price, 'status': 'MANUAL'},
                    stop_loss=stop_loss, take_profit=take_profit,
                    risk_reward=2.0, confidence=confidence,
                )

                # Also publish to Redis for monitor
                pos_data = {
                    'symbol':          symbol,
                    'direction':       direction,
                    'quantity':        quantity,
                    'entry_price':     entry_price,
                    'entry_fill_price': entry_price,
                    'stop_loss':       stop_loss,
                    'take_profit':     take_profit,
                    'take_profit_2':   take_profit2,
                    'strategy':        'MANUAL_ADOPTED',
                    'regime':          'Unknown',
                    'source':          'MANUAL',
                    'entry_time':      now.isoformat(),
                    'tp1_hit':         False,
                    'tp2_hit':         False,
                    'composite_score': 0.0,
                    'confidence':      confidence,
                }
                publish_position_open(pos_id, pos_data)

                self._json(200, {
                    'success':      True,
                    'position_id':  pos_id,
                    'stop_loss':    stop_loss,
                    'take_profit':  take_profit,
                    'take_profit_2': take_profit2,
                })

            else:
                self._json(404, {'error': 'Not found'})

        except Exception as e:
            self._json(500, {'error': str(e)})


# ══════════════════════════════════════════════════════════════════════════════
# Binance position import
# ══════════════════════════════════════════════════════════════════════════════

def _import_binance_position(pos: dict) -> int:
    """
    Import a Binance position into bot management.
    Creates DB record and publishes to Redis.
    """
    import data.database as db
    
    symbol = pos['symbol']
    direction = pos['direction']
    quantity = float(pos['quantity'])
    entry_price = float(pos['entry_price'])
    mark_price = float(pos.get('mark_price', entry_price))
    
    # Default SL/TP: 2% SL, 4% TP (2R), 6% TP2 (3R)
    if direction == 'LONG':
        stop_loss = round(entry_price * 0.98, 2)
        take_profit = round(entry_price * 1.04, 2)
        take_profit2 = round(entry_price * 1.06, 2)
    else:
        stop_loss = round(entry_price * 1.02, 2)
        take_profit = round(entry_price * 0.96, 2)
        take_profit2 = round(entry_price * 0.94, 2)
    
    now = datetime.utcnow()
    
    # Save to DB
    pos_id = db.open_position_live(
        signal_id=None, symbol=symbol,
        direction=direction, strategy='MANUAL_IMPORTED',
        regime=0, entry_price=entry_price,
        entry_time=now, quantity=quantity,
        order_data={'fill_price': entry_price, 'status': 'IMPORTED'},
        stop_loss=stop_loss, take_profit=take_profit,
        risk_reward=2.0, confidence=0.5,
    )
    
    # Publish to Redis for monitor
    pos_data = {
        'symbol': symbol,
        'direction': direction,
        'quantity': quantity,
        'entry_price': entry_price,
        'entry_fill_price': entry_price,
        'stop_loss': stop_loss,
        'take_profit': take_profit,
        'take_profit_2': take_profit2,
        'strategy': 'MANUAL_IMPORTED',
        'regime': 'Unknown',
        'source': 'MANUAL',
        'entry_time': now.isoformat(),
        'tp1_hit': False,
        'tp2_hit': False,
        'composite_score': 0.0,
        'confidence': 0.5,
        'unrealized_pnl': float(pos.get('unrealized_pnl', 0)),
        'current_price': mark_price,
    }
    publish_position_open(pos_id, pos_data)
    
    print(f"[OK] Imported position: #{pos_id} {direction} {symbol} qty={quantity}")
    return pos_id


# ══════════════════════════════════════════════════════════════════════════════
# Server runner
# ══════════════════════════════════════════════════════════════════════════════

def run_http_server(port: int = 8081):
    server = HTTPServer(('0.0.0.0', port), RequestHandler)

    def start():
        print(f"[HTTP] HTTP API server started on http://0.0.0.0:{port}")
        server.serve_forever()

    thread = threading.Thread(target=start, daemon=True)
    thread.start()
    return thread
