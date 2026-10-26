"""Serve only the rendered report on a private loopback endpoint for visual review."""
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

page = (Path(__file__).parent / 'presentation-09e-node24/index.html').read_bytes()

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in ('/', '/index.html'):
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(page)))
        self.end_headers()
        self.wfile.write(page)

    def log_message(self, *args):
        pass

server = HTTPServer(('127.0.0.1', 0), Handler)
print('http://127.0.0.1:' + str(server.server_port) + '/index.html', flush=True)
server.serve_forever()
