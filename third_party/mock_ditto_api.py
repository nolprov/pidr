#!/usr/bin/env python3
import base64
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

HOST = "0.0.0.0"
PORT = 8080

THINGS = {}
AUTH_USER = "ditto"
AUTH_PASS = "ditto"
ALT_USER = "devops"
ALT_PASS = "foobar"


def _is_authorized(header_value: str | None) -> bool:
    if not header_value:
        return False
    if not header_value.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(header_value.split(" ", 1)[1]).decode("utf-8")
    except Exception:
        return False
    return decoded in {
        f"{AUTH_USER}:{AUTH_PASS}",
        f"{ALT_USER}:{ALT_PASS}",
    }


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, code: int, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _unauthorized(self):
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="ditto"')
        self.end_headers()

    def _read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length > 0 else b"{}"
        return json.loads(raw.decode("utf-8"))

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, {"status": "UP"})
            return

        if not self.headers.get("x-ditto-pre-authenticated") and not _is_authorized(self.headers.get("Authorization")):
            self._unauthorized()
            return

        if self.path == "/api/2/things":
            out = [{"thingId": k, "attributes": v} for k, v in sorted(THINGS.items())]
            self._send_json(200, out)
            return

        self._send_json(404, {"error": "not found"})

    def do_PUT(self):
        if not self.headers.get("x-ditto-pre-authenticated") and not _is_authorized(self.headers.get("Authorization")):
            self._unauthorized()
            return

        prefix = "/api/2/things/"
        if not self.path.startswith(prefix):
            self._send_json(404, {"error": "not found"})
            return

        thing_id = unquote(self.path[len(prefix):])
        try:
            data = self._read_json()
            attrs = data.get("attributes", {})
            if not isinstance(attrs, dict):
                raise ValueError("attributes must be an object")
            THINGS[thing_id] = attrs
            self._send_json(201, {"thingId": thing_id})
        except Exception as exc:
            self._send_json(400, {"error": str(exc)})

    def log_message(self, fmt, *args):
        return


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"[*] Mock Ditto API listening on http://{HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
