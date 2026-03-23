"""
Socket.IO Server - Real-time updates for Dashboard
===================================================
- Runs alongside the trading engine
- Publishes real-time events to connected dashboard clients
- Events: balance_update, position_update, stats_update, regime_update, equity_update
"""
import json
import threading
import socketio
import eventlet
from datetime import datetime
from config import REDIS_HOST, REDIS_PORT

# Create Socket.IO server
sio = socketio.Server(cors_allowed_origins="*")

def get_socket_server():
    """Get the Socket.IO server instance."""
    return sio


# ═══════════════════════════════════════
# EVENT EMITTERS
# ═══════════════════════════════════════

def emit_balance_update(data: dict):
    """Emit balance update event to all connected clients."""
    sio.emit('balance_update', {
        'type': 'balance_update',
        'data': data,
        'timestamp': datetime.utcnow().isoformat(),
    })


def emit_position_update(event: str, data: dict):
    """Emit position update event (open/close/update)."""
    sio.emit('position_update', {
        'type': 'position_update',
        'event': event,
        'data': data,
        'timestamp': datetime.utcnow().isoformat(),
    })


def emit_stats_update(data: dict):
    """Emit stats update event."""
    sio.emit('stats_update', {
        'type': 'stats_update',
        'data': data,
        'timestamp': datetime.utcnow().isoformat(),
    })


def emit_regime_update(data: dict):
    """Emit regime update event."""
    sio.emit('regime_update', {
        'type': 'regime_update',
        'data': data,
        'timestamp': datetime.utcnow().isoformat(),
    })


def emit_equity_update(data: dict):
    """Emit equity update event."""
    sio.emit('equity_update', {
        'type': 'equity_update',
        'data': data,
        'timestamp': datetime.utcnow().isoformat(),
    })


# ═══════════════════════════════════════
# SOCKET.IO EVENT HANDLERS
# ═══════════════════════════════════════

@sio.event
def connect(sid, environ):
    print(f"[SOCKET] Client connected: {sid}")


@sio.event
def disconnect(sid):
    print(f"[SOCKET] Client disconnected: {sid}")


@sio.event
def subscribe(sid, data):
    """Client subscribes to specific channels."""
    rooms = data.get('rooms', [])
    for room in rooms:
        sio.enter_room(sid, room)
        print(f"[SIGNAL] Client {sid} subscribed to {room}")


# ═══════════════════════════════════════
# THREAD FOR RUNNING SOCKET.IO SERVER
# ═══════════════════════════════════════

def run_socket_server(host='0.0.0.0', port=8080):
    """Run Socket.IO server in a separate thread."""
    
    socketio_app = socketio.WSGIApp(sio)
    
    def start_server():
        try:
            listener = eventlet.listen((host, port))
            print(f"[START] Socket.IO server started on http://{host}:{port}")
            eventlet.wsgi.server(listener, socketio_app)
        except Exception as e:
            print(f"[ERROR] Socket.IO server error: {e}")
    
    thread = threading.Thread(target=start_server, daemon=True)
    thread.start()
    return thread
