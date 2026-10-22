"""stdlib HTTP server for ZTGE API (no third-party deps).

Usage
-----
    PYTHONPATH=src:vendor/clan_src python -m ztge.api.server --host 127.0.0.1 --port 8080

Or after install::

    ztge-api --port 8080
"""

from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Tuple
from urllib.parse import urlparse

# bootstrap path for repo layout
_ROOT = Path(__file__).resolve().parents[3]
for p in (_ROOT / "src", _ROOT / "vendor" / "clan_src"):
    if p.is_dir() and str(p) not in sys.path:
        sys.path.insert(0, str(p))

from ztge.api.app import handle_request  # noqa: E402


class ZTGEHandler(BaseHTTPRequestHandler):
    server_version = "ZTGE/0.1"

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
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        status, headers, body = handle_request("GET", path)
        self._write(status, headers, body)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
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
    p = argparse.ArgumentParser(description="ZTGE HTTP API (stdlib)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8080)
    args = p.parse_args(argv)
    httpd = ThreadingHTTPServer((args.host, args.port), ZTGEHandler)
    print(f"ZTGE API listening on http://{args.host}:{args.port}", flush=True)
    print("  GET  /health  /v1/status  /openapi.json", flush=True)
    print("  POST /v1/plan  /v1/audit", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nshutdown", flush=True)
        httpd.server_close()


if __name__ == "__main__":
    main()
