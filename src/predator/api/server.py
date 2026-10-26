"""stdlib HTTP server for PREDATOR API (no third-party deps).

Usage
-----
    python -m predator.api.server --host 127.0.0.1 --port 8080

Or after install::

    predator-api --port 8080
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
import tempfile
import time
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address
from urllib.parse import urlparse

from predator.api.app import (  # noqa: E402
    _NATIVE_UPLOAD_LIMIT,
    _NATIVE_UPLOAD_SLOTS,
    handle_request,
)
from predator.api.security import (auth_configured, cors_headers, is_authorized,
                                   max_native_request_bytes, max_request_bytes,
                                   native_upload_slots, origin_is_allowed)


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
        if path == "/v1/plan/native-file":
            self._do_native_json_file()
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

    def _do_native_json_file(self) -> None:
        """Stream a JSON request to disk, verify SHA-256, then delegate to MORPH."""
        try:
            upload_slots = native_upload_slots()
        except ValueError:
            self._write(500, {"Content-Type": "application/json; charset=utf-8"}, {"error": "invalid_server_configuration"})
            return
        if upload_slots != _NATIVE_UPLOAD_LIMIT:
            self._write(500, {"Content-Type": "application/json; charset=utf-8"},
                        {"error": "invalid_server_configuration", "details": ["Native upload concurrency must be set before server startup; restart after changing it"]})
            return
        if not _NATIVE_UPLOAD_SLOTS.acquire(blocking=False):
            self._write(503, {"Content-Type": "application/json; charset=utf-8"}, {"error": "native_upload_busy"})
            return
        try:
            self._stream_native_json_file()
        finally:
            _NATIVE_UPLOAD_SLOTS.release()

    def _stream_native_json_file(self) -> None:
        if self.headers.get("Transfer-Encoding"):
            self._write(400, {"Content-Type": "application/json; charset=utf-8"},
                        {"error": "unsupported_transfer_encoding"})
            return
        lengths = self.headers.get_all("Content-Length", []) if hasattr(self.headers, "get_all") else [self.headers.get("Content-Length")]
        if len(lengths) != 1 or not str(lengths[0]).isdecimal():
            self._write(400, {"Content-Type": "application/json; charset=utf-8"}, {"error": "invalid_content_length"})
            return
        length = int(lengths[0])
        try:
            body_limit = max_native_request_bytes()
        except ValueError as exc:
            self._write(500, {"Content-Type": "application/json; charset=utf-8"},
                        {"error": "invalid_server_configuration", "details": [str(exc)]})
            return
        if length <= 0 or length > body_limit:
            self._write(413 if length > body_limit else 400,
                        {"Content-Type": "application/json; charset=utf-8"},
                        {"error": "request_too_large" if length > body_limit else "invalid_content_length"})
            return
        if self.headers.get_content_type() != "application/json":
            self._write(415, {"Content-Type": "application/json; charset=utf-8"}, {"error": "content_type_must_be_application_json"})
            return
        expected = self.headers.get("X-Content-SHA256", "").strip().lower()
        if len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
            self._write(400, {"Content-Type": "application/json; charset=utf-8"},
                        {"error": "invalid_sha256", "details": ["X-Content-SHA256 must be 64 hexadecimal characters"]})
            return
        digest = hashlib.sha256()
        received = 0
        started = time.perf_counter()
        try:
            with tempfile.NamedTemporaryFile(prefix="predator-native-", suffix=".json", delete=False) as handle:
                temp_path = handle.name
                while received < length:
                    chunk = self.rfile.read(min(1024 * 1024, length - received))
                    if not chunk:
                        raise ConnectionError("incomplete request body")
                    received += len(chunk)
                    digest.update(chunk)
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
                os.fchmod(handle.fileno(), 0o400)
            upload_hash_verify_s = time.perf_counter() - started
            actual = digest.hexdigest()
            if not hmac.compare_digest(actual, expected):
                self._write(400, {"Content-Type": "application/json; charset=utf-8"},
                            {"error": "sha256_mismatch", "expected": expected, "actual": actual})
                return
            from predator.api.app import native_json_plan_file
            status, headers, body = native_json_plan_file(temp_path, input_sha256=actual, byte_length=received)
            body.setdefault("trace", {})
            if isinstance(body["trace"], dict):
                body["trace"].update({"upload_hash_verify_s": round(upload_hash_verify_s, 6),
                                      "request_process_s": round(time.perf_counter() - started, 6),
                                      "streamed_bytes": received})
            self._write(status, headers, body)
        except (OSError, ConnectionError) as exc:
            self._write(400, {"Content-Type": "application/json; charset=utf-8"},
                        {"error": "request_body_read_failed", "details": [str(exc)]})
        finally:
            if "temp_path" in locals():
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass


class _InvalidJSON:
    pass


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="PREDATOR HTTP API (stdlib)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8080)
    args = p.parse_args(argv)
    try:
        max_request_bytes()  # fail fast on invalid operator overrides
        max_native_request_bytes()
        native_upload_slots()
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
