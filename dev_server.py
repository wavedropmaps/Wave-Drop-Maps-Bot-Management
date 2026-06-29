#!/usr/bin/env python3
"""Local dev server — serves website/ and mocks /api/<key> from website/data/<key>.json"""
import http.server, json, os
from pathlib import Path

PORT = int(os.environ.get('PORT', 8080))
WEBSITE_DIR = Path(__file__).parent / "website"

class DevHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEBSITE_DIR), **kwargs)

    def do_GET(self):
        if self.path.startswith('/api/') or self.path.startswith('/__admin/'):
            key = self.path.replace('/__admin/', '/api/')[5:].split('?')[0]
            f = WEBSITE_DIR / "data" / f"{key}.json"
            if f.exists():
                data = f.read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            elif key == "admin/profile/customization":
                # Mock customization API so user is always owner locally for debugging
                data = json.dumps({"settings": {}, "is_owner": True}).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            else:
                self.send_error(404, f"No data file for: {key}")
            return
        super().do_GET()

    def do_POST(self):
        if self.path == '/api/admin/profile/customization':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(b'{"saved": true}')
            return

        if self.path.startswith('/api/admin/profile/upload'):
            import cgi
            import time
            ctype, pdict = cgi.parse_header(self.headers.get('content-type'))
            pdict['boundary'] = bytes(pdict['boundary'], "utf-8")
            pdict['CONTENT-LENGTH'] = int(self.headers.get('Content-Length'))
            form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ={'REQUEST_METHOD': 'POST', 'CONTENT_TYPE': self.headers['Content-Type']})
            file_item = form['file']
            
            ext = os.path.splitext(file_item.filename)[1].lower()
            safe_name = f"dev_{int(time.time())}{ext}"
            
            uploads_dir = WEBSITE_DIR / "assets" / "uploads"
            os.makedirs(uploads_dir, exist_ok=True)
            
            filepath = uploads_dir / safe_name
            with open(filepath, 'wb') as f:
                f.write(file_item.file.read())
                
            data = json.dumps({"url": f"/assets/uploads/{safe_name}"}).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
            
        if self.path == '/api/duty_needs' or self.path == '/__admin/duty_needs':
            content_length = int(self.headers.get('Content-Length', 0))
            if content_length > 0:
                post_data = self.rfile.read(content_length)
                try:
                    payload = json.loads(post_data)
                    f = WEBSITE_DIR / "data" / "duty_needs.json"
                    f.write_text(json.dumps(payload, indent=2))
                except Exception as e:
                    print(f"Error saving duty needs: {e}")
            
            data = json.dumps({"ok": True}).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
            
        if self.path.startswith('/api/') or self.path.startswith('/__admin/'):
            # Mock success for any other API POST request
            data = json.dumps({"ok": True}).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self.send_error(405, "Method Not Allowed")

    def log_message(self, fmt, *args):
        print(f"  {args[0]} {args[1]}")

if __name__ == '__main__':
    print(f"Dev server -> http://localhost:{PORT}")
    print(f"Ctrl+C to stop\n")
    with http.server.ThreadingHTTPServer(('', PORT), DevHandler) as s:
        s.serve_forever()
