"""
HTTP API Server
================
Port 8081 — exposes trading engine data to the Next.js dashboard.

Endpoints:
  GET  /health
  GET  /manual-positions    — all Binance positions + bot Redis positions
  GET  /cleanup-ghosts      — remove stale Redis positions not on Binance
  POST /adopt-position      — let bot manage a manually-opened Binance position
  POST /close-position      — close a position via Binance market order
"""
import json
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
import threading

import data.binance_client as bnb
from data.monitor import (
    get_open_positions_from_redis,
    publish_position_open,
    publish_position_close,
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

            # ── /adopt-position ──────────────────────────────────────────────
            elif self.path == '/adopt-position':
                symbol      = body.get('symbol', '')
                direction   = body.get('direction', '')
                quantity    = float(body.get('quantity', 0))
                entry_price = float(body.get('entry_price', 0))

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

                # Unique ID based on timestamp
                pos_id = int(time.time() * 1000)
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
                    'entry_time':      datetime.utcnow().isoformat(),
                    'tp1_hit':         False,
                    'tp2_hit':         False,
                    'composite_score': 0.0,
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
# Ghost position cleanup
# ══════════════════════════════════════════════════════════════════════════════

def _cleanup_ghost_positions() -> list:
    """
    Remove Redis positions that no longer exist on Binance.
    Returns list of removed position IDs.
    """
    removed = []
    try:
        bot_positions   = get_open_positions_from_redis()
        binance_live    = bnb.get_account_positions()          # actual open positions

        # Build set of (symbol, direction) pairs that actually exist on Binance
        live_keys = {(p['symbol'], p['direction']) for p in binance_live}

        for pos in bot_positions:
            # Only reconcile LIVE / MANUAL_ADOPTED positions — skip paper/backtest
            if pos.get('source') not in ('LIVE', 'MANUAL', 'MANUAL_ADOPTED'):
                continue
            key = (pos.get('symbol'), pos.get('direction'))
            if key not in live_keys:
                pid = pos.get('id')
                publish_position_close(int(pid), {
                    'exit_price': 0,
                    'reason':     'Ghost cleanup (not found on Binance)',
                    'pnl':        0,
                })
                removed.append(pid)
                print(f"🧹 Ghost position removed: #{pid} {key}")
    except Exception as e:
        print(f"⚠️ cleanup_ghost_positions: {e}")
    return removed


# ══════════════════════════════════════════════════════════════════════════════
# Server runner
# ══════════════════════════════════════════════════════════════════════════════

def run_http_server(port: int = 8081):
    server = HTTPServer(('0.0.0.0', port), RequestHandler)

    def start():
        print(f"🌐 HTTP API server started on http://0.0.0.0:{port}")
        server.serve_forever()

    thread = threading.Thread(target=start, daemon=True)
    thread.start()
    return thread
