"""stdlib HTTP server for PREDATOR API (no third-party deps).

Usage
-----
    python -m predator.api.server --host 127.0.0.1 --port 8080

Or after install::

    predator-api --port 8080
"""

from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address
from urllib.parse import urlparse

from predator.api.app import handle_request  # noqa: E402
from predator.api.security import auth_configured, cors_headers, is_authorized, max_request_bytes, origin_is_allowed


class PredatorHandler(BaseHTTPRequestHandler):
    server_version = "PREDATOR/0.2"

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return None
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return _InvalidJSON()

    def _write(self, status: int, headers: dict, body: dict) -> None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        for name, value in cors_headers(self.headers.get("Origin")).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)

    def _authorized(self, method: str, path: str) -> bool:
        public = method == "GET" and path == "/health"
        if is_authorized(self.headers, public=public):
            return True
        self._write(401, {"Content-Type": "application/json; charset=utf-8", "WWW-Authenticate": "Bearer"},
                    {"error": "unauthorized"})
        return False

    def do_OPTIONS(self) -> None:  # noqa: N802
        origin = self.headers.get("Origin")
        if origin and not origin_is_allowed(origin):
            self._write(403, {"Content-Type": "application/json; charset=utf-8"}, {"error": "origin_not_allowed"})
            return
        self.send_response(204)
        for name, value in cors_headers(origin).items():
            self.send_header(name, value)
        self.end_headers()

    def _origin_allowed(self) -> bool:
        origin = self.headers.get("Origin")
        if origin and not origin_is_allowed(origin):
            self._write(403, {"Content-Type": "application/json; charset=utf-8"},
                        {"error": "origin_not_allowed"})
            return False
        return True

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if not self._origin_allowed():
            return
        if not self._authorized("GET", path):
            return
        status, headers, body = handle_request("GET", path)
        self._write(status, headers, body)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if not self._origin_allowed():
            return
        if not self._authorized("POST", path):
            return
        # BaseHTTPRequestHandler does not decode chunked request bodies. Refuse
        # transfer encodings explicitly rather than treating them as an empty body.
        transfer_encoding = self.headers.get("Transfer-Encoding")
        if transfer_encoding:
            self._write(400, {"Content-Type": "application/json; charset=utf-8"},
                        {"error": "unsupported_transfer_encoding"})
            return
        if hasattr(self.headers, "get_all"):
            lengths = self.headers.get_all("Content-Length", [])
        else:  # simple mapping in direct handler unit tests
            value = self.headers.get("Content-Length")
            lengths = [] if value is None else [value]
        if len(lengths) != 1 or not str(lengths[0]).isdecimal():
            self._write(400, {"Content-Type": "application/json; charset=utf-8"},
                        {"error": "invalid_content_length"})
            return
        try:
            length = int(lengths[0])
        except ValueError:
            length = -1
        try:
            body_limit = max_request_bytes()
        except ValueError as exc:
            self._write(500, {"Content-Type": "application/json; charset=utf-8"},
                        {"error": "invalid_server_configuration", "details": [str(exc)]})
            return
        if length < 0 or length > body_limit:
            self._write(413 if length > body_limit else 400,
                        {"Content-Type": "application/json; charset=utf-8"},
                        {"error": "request_too_large" if length > body_limit else "invalid_content_length"})
            return
        payload = self._read_json()
        if isinstance(payload, _InvalidJSON):
            self._write(
                400,
                {"Content-Type": "application/json; charset=utf-8"},
                {"error": "invalid_json", "details": ["body must be JSON"]},
            )
            return
        status, headers, body = handle_request("POST", path, payload)
        self._write(status, headers, body)


class _InvalidJSON:
    pass


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="PREDATOR HTTP API (stdlib)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8080)
    args = p.parse_args(argv)
    try:
        max_request_bytes()  # fail fast on an invalid operator override
    except ValueError as exc:
        p.error(str(exc))
    try:
        is_loopback = ip_address(args.host).is_loopback
    except ValueError:
        is_loopback = args.host.lower() == "localhost"
    if not is_loopback and not auth_configured():
        p.error("non-loopback binds require PREDATOR_API_TOKEN to be configured")
    httpd = ThreadingHTTPServer((args.host, args.port), PredatorHandler)
    print(f"PREDATOR API listening on http://{args.host}:{args.port}", flush=True)
    print("  GET  /health  /v1/status  /openapi.json", flush=True)
    print("  POST /v1/plan  /v1/audit", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nshutdown", flush=True)
        httpd.server_close()


if __name__ == "__main__":
    main()
