"""
HTTP API Server for Manual Positions
=====================================
Simple HTTP server to expose manual positions from Binance
"""
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
import threading

from data.monitor import get_manual_positions_from_binance, get_open_positions_from_redis


class RequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/manual-positions':
            try:
                manual = get_manual_positions_from_binance()
                bot_positions = get_open_positions_from_redis()
                
                response = {
                    "bot_positions": bot_positions,
                    "manual_positions": manual,
                    "timestamp": datetime.utcnow().isoformat(),
                }
                
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps(response).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
        
        elif self.path == '/health':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        
        else:
            self.send_response(404)
            self.end_headers()
    
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
    
    def log_message(self, format, *args):
        pass  # Suppress logging


def run_http_server(port=8081):
    """Run HTTP server in a separate thread."""
    server = HTTPServer(('0.0.0.0', port), RequestHandler)
    
    def start():
        print(f"🌐 HTTP API server started on http://0.0.0.0:{port}")
        server.serve_forever()
    
    thread = threading.Thread(target=start, daemon=True)
    thread.start()
    return thread
