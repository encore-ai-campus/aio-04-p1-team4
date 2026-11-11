"""Local example server. Exposes only the demo and optional public JS SDK key."""
import http.server
import json
import pathlib
import urllib.parse
from walk_routes import RouteError, walking_route

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(HERE), **kwargs)

    def do_GET(self):
        if urllib.parse.urlsplit(self.path).path == '/config.json':
            key = ''
            if (ROOT / '.env').exists():
                for line in (ROOT / '.env').read_text(encoding='utf-8-sig').splitlines():
                    if line.strip().startswith('KAKAO_JAVASCRIPT_KEY='):
                        key = line.split('=',1)[1].strip().strip('\"\'')
            body = json.dumps({'javascriptKey': key}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            super().do_GET()

    def do_POST(self):
        if urllib.parse.urlsplit(self.path).path != '/api/walking-route':
            self.send_error(404)
            return
        origin = self.headers.get('Origin')
        if origin and origin not in {'http://localhost:5500', 'http://127.0.0.1:5500'}:
            self.send_error(403)
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 4096:
                raise RouteError('요청 크기를 확인해주세요.', 400)
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError()
            result, status = walking_route(body, ROOT), 200
        except RouteError as error:
            result, status = {'error': error.message}, error.status
        except (ValueError, TypeError):
            result, status = {'error': '출발지와 도착지를 확인해주세요.'}, 400
        encoded = json.dumps(result, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, *args):
        pass

if __name__ == '__main__':
    print('Local: http://localhost:5500', flush=True)
    http.server.ThreadingHTTPServer(('127.0.0.1', 5500), Handler).serve_forever()
