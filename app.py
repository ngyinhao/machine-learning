import argparse
import json
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from dashboard_api import DashboardSession, training_hyperparameters, warehouse_payload


WEB = Path(__file__).resolve().parent / "web"
ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/episode-grid.js": ("episode-grid.js", "text/javascript; charset=utf-8"),
    "/warehouse-map.js": ("warehouse-map.js", "text/javascript; charset=utf-8"),
    "/dashboard.js": ("dashboard.js", "text/javascript; charset=utf-8"),
}


class DashboardServer(ThreadingHTTPServer):
    def __init__(self, address):
        self.assets = {
            route: ((WEB / filename).read_bytes(), media_type)
            for route, (filename, media_type) in ASSETS.items()
        }
        super().__init__(address, DashboardHandler)
        self.session = DashboardSession()
        self.lock = threading.Lock()


class DashboardHandler(BaseHTTPRequestHandler):
    def _respond(self, status, content, media_type):
        self.send_response(status)
        self.send_header("Content-Type", media_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(content)

    def _json(self, data, status=HTTPStatus.OK):
        self._respond(status, json.dumps(data).encode(), "application/json; charset=utf-8")

    def do_GET(self):
        if self.path == "/api/hyperparameters":
            self._json(training_hyperparameters())
        elif self.path == "/api/warehouse":
            self._json(warehouse_payload())
        elif self.path in self.server.assets:
            content, media_type = self.server.assets[self.path]
            self._respond(HTTPStatus.OK, content, media_type)
        else:
            self._json({"error": "Page not found."}, HTTPStatus.NOT_FOUND)

    def do_POST(self):
        if self.path not in ("/api/start", "/api/advance", "/api/replay"):
            self._json({"error": "Action not found."}, HTTPStatus.NOT_FOUND)
            return
        if self.headers.get_content_type() != "application/json":
            self._json({"error": "Send a JSON request."}, HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 4096:
                raise ValueError("The request body must be between 1 and 4,096 bytes.")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("Send a JSON object.")
            with self.server.lock:
                response = self.server.session.dispatch(self.path.removeprefix("/api/"), payload)
        except (ValueError, UnicodeError) as error:
            self._json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
            return
        except LookupError:
            self._json({"error": "This run has ended or was replaced. Start a new run."}, HTTPStatus.CONFLICT)
            return
        self._json(response)

    def log_message(self, format_string, *arguments):
        if self.path.startswith("/api/") and arguments[1] == "200":
            return
        super().log_message(format_string, *arguments)


def main():
    parser = argparse.ArgumentParser(description="Run the local warehouse training dashboard.")
    parser.add_argument("--port", type=int, default=8765, help="HTTP port (default: 8765); use 0 for a free port.")
    options = parser.parse_args()
    with DashboardServer(("127.0.0.1", options.port)) as server:
        print(f"Warehouse training dashboard at http://127.0.0.1:{server.server_port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
