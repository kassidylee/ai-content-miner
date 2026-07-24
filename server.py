# server.py
import http.server
import socketserver
import os

PORT = 8000

class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/reports/'):
            local_path = self.path[8:]
            if not local_path:
                self.send_error(404, "No file specified")
                return
            safe_path = os.path.normpath(local_path)
            if safe_path.startswith('..') or os.path.isabs(safe_path):
                self.send_error(403, "Forbidden")
                return
            full_path = os.path.join(os.getcwd(), 'reports', safe_path)
            if not os.path.exists(full_path) or os.path.isdir(full_path):
                self.send_error(404, "File not found")
                return
            with open(full_path, 'rb') as f:
                self.send_response(200)
                if full_path.endswith('.html'):
                    self.send_header('Content-Type', 'text/html; charset=utf-8')
                elif full_path.endswith('.txt'):
                    self.send_header('Content-Type', 'text/plain; charset=utf-8')
                else:
                    self.send_header('Content-Type', 'application/octet-stream')
                self.end_headers()
                self.wfile.write(f.read())
        else:
            self.send_error(404, "Only /reports/ is served")

if __name__ == '__main__':
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        print(f"静态服务运行于 http://localhost:{PORT}/reports/")
        httpd.serve_forever()
