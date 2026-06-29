#!/usr/bin/env python3
import json
from http.server import HTTPServer, SimpleHTTPRequestHandler

MOCK_ECONOMY = {
    "central_bank": {
        "fee_rate": "2.5%",
        "p2p_tax": "1.0%",
        "reserves_wp": 142500
    },
    "bondholders": [
        {"user_id": "111", "name": "Slax", "avatar_url": "", "locked": 5000, "maturity": "2026-07-15T00:00:00", "yield": 500},
        {"user_id": "222", "name": "Kieren", "avatar_url": "", "locked": 3200, "maturity": "2026-08-01T00:00:00", "yield": 320},
        {"user_id": "333", "name": "WaveStaff", "avatar_url": "", "locked": 1800, "maturity": "2026-07-01T00:00:00", "yield": 180},
    ],
    "leaderboard": [
        {"user_id": "111", "name": "Slax", "avatar_url": "", "wp": 12400},
        {"user_id": "222", "name": "Kieren", "avatar_url": "", "wp": 9800},
        {"user_id": "333", "name": "WaveStaff", "avatar_url": "", "wp": 7100},
        {"user_id": "444", "name": "DropMapper", "avatar_url": "", "wp": 5400},
        {"user_id": "555", "name": "SurgeKing", "avatar_url": "", "wp": 3200},
    ],
    "vbucks_leaderboard": [
        {"user_id": "111", "name": "Slax", "avatar_url": "", "vbucks": 800},
        {"user_id": "222", "name": "Kieren", "avatar_url": "", "vbucks": 650},
        {"user_id": "333", "name": "WaveStaff", "avatar_url": "", "vbucks": 420},
    ]
}

class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/api/economy':
            body = json.dumps(MOCK_ECONOMY).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', len(body))
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(body)
        else:
            super().do_GET()

    def log_message(self, fmt, *args):
        pass  # suppress logs

if __name__ == '__main__':
    import os
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    print("Mock server running at http://localhost:8080")
    HTTPServer(('', 8080), Handler).serve_forever()
