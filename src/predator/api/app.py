"""HTTP request handlers for PREDATOR.

Works without FastAPI: ``handle_request(method, path, body)`` returns
``(status_code, headers, body_dict)``. Optional ``create_app()`` returns a
FastAPI application when the package is installed.
"""

import hashlib
import hmac
import json
import os
import time
import shutil
import subprocess
import tempfile
import threading
from importlib.resources import files
from typing import Any, Dict, List, Optional, Tuple

from clan_subnet_detector import (  # noqa: E402
    Graph,
    __version__ as clan_version,
    is_independent,
    morph_status,
    plan_independent,
    run_audit,
    sign_report_hmac,
    validate_report,
)
from clan_subnet_detector.audit.signing import secret_from_env  # noqa: E402

from .openapi_doc import load_openapi
from predator.hardware import system_profile
from .security import (MAX_NATIVE_REQUEST_BYTES, is_authorized, max_native_request_bytes,
                       max_request_bytes, native_graph_limits, native_solver_environment,
                       native_upload_slots, origin_is_allowed)
from .validation import validate_audit_request, validate_plan_request

ENGINE = "predator"
ENGINE_VERSION = "0.2.0"
def _native_slot_limit() -> int:
    try:
        return max(1, min(16, int(os.getenv("PREDATOR_NATIVE_MAX_CONCURRENT", "1"))))
    except ValueError:
        return 1


def _native_upload_limit() -> int:
    return native_upload_slots()


# Limits are fixed when the API process imports this module. Do not replace these
# semaphores at request time: concurrent replacement can allow oversubscription.
_NATIVE_SLOT_LIMIT = _native_slot_limit()
_NATIVE_UPLOAD_LIMIT = _native_upload_limit()
_NATIVE_SLOTS = threading.BoundedSemaphore(_NATIVE_SLOT_LIMIT)
_NATIVE_UPLOAD_SLOTS = threading.BoundedSemaphore(_NATIVE_UPLOAD_LIMIT)


def _native_limits_match_startup(native_slots: int, upload_slots: int) -> bool:
    return native_slots == _NATIVE_SLOT_LIMIT and upload_slots == _NATIVE_UPLOAD_LIMIT


def _native_output_limit(name: str, default: int, hard_max: int) -> int:
    raw = os.getenv(name, str(default))
    if not raw.isdecimal():
        raise ValueError(f"{name} must be a positive integer")
    value = int(raw)
    if value < 1 or value > hard_max:
        raise ValueError(f"{name} must be in [1, {hard_max}]")
    return value


def _run_native_bounded(binary: str, path: str, timeout_s: float) -> tuple[int, str, str, bool, float]:
    """Capture native output with fixed memory bounds; kill on overflow/timeout."""
    stdout_limit = _native_output_limit("PREDATOR_NATIVE_MAX_STDOUT_BYTES", 32 * 1024 * 1024, 128 * 1024 * 1024)
    stderr_limit = _native_output_limit("PREDATOR_NATIVE_MAX_STDERR_BYTES", 1024 * 1024, 8 * 1024 * 1024)
    child_env = os.environ.copy()
    child_env.update(native_solver_environment())
    process = subprocess.Popen([binary, "--json", path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=child_env)
    native_started = time.perf_counter()
    overflow = threading.Event()
    captured: dict[str, bytearray] = {"stdout": bytearray(), "stderr": bytearray()}

    def drain(name: str, stream, limit: int) -> None:
        while True:
            chunk = stream.read(65536)
            if not chunk:
                return
            if len(captured[name]) + len(chunk) > limit:
                remaining = max(0, limit + 1 - len(captured[name]))
                captured[name].extend(chunk[:remaining])
                overflow.set()
                try:
                    process.kill()
                except OSError:
                    pass
                return
            captured[name].extend(chunk)

    readers = [
        threading.Thread(target=drain, args=("stdout", process.stdout, stdout_limit), daemon=True),
        threading.Thread(target=drain, args=("stderr", process.stderr, stderr_limit), daemon=True),
    ]
    for reader in readers:
        reader.start()
    try:
        process.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        for reader in readers:
            reader.join()
        raise
    for reader in readers:
        reader.join()
    return (process.returncode, captured["stdout"].decode("utf-8", errors="replace"),
            captured["stderr"].decode("utf-8", errors="replace"), overflow.is_set(),
            time.perf_counter() - native_started)

JsonDict = Dict[str, Any]
HandlerResult = Tuple[int, Dict[str, str], JsonDict]


def _json_headers() -> Dict[str, str]:
    return {"Content-Type": "application/json; charset=utf-8"}


def _error(status: int, message: str, details: Optional[List[str]] = None) -> HandlerResult:
    body: JsonDict = {"error": message}
    if details:
        body["details"] = details
    return status, _json_headers(), body


def _graph_from(req: JsonDict) -> Graph:
    gspec = req["graph"]
    return Graph.from_edges(
        gspec["n"],
        gspec["edges"],
        directed=bool(gspec.get("directed", False)),
    )


def handle_health() -> HandlerResult:
    return 200, _json_headers(), {"status": "ok", "engine": ENGINE}


def handle_status() -> HandlerResult:
    contracts = sorted(p.name for p in files("predator").joinpath("contracts").iterdir() if p.name.endswith(".yaml"))
    return (
        200,
        _json_headers(),
        {
            "engine": ENGINE,
            "version": ENGINE_VERSION,
            "clan_version": clan_version,
            "morph": morph_status(),
            "resources": system_profile(),
            "max_request_bytes": max_request_bytes(),
            "contracts": contracts,
        },
    )


def handle_openapi() -> HandlerResult:
    return 200, _json_headers(), load_openapi()


def handle_plan(body: Any) -> HandlerResult:
    req, errs = validate_plan_request(body)
    if errs or req is None:
        return _error(400, "validation_error", errs)
    g = _graph_from(req)
    trace: List[dict] = []
    nodes = plan_independent(
        g,
        method=req["method"],
        budget_ms=req["budget_ms"],
        seed=req["seed"],
        trace_out=trace,
        auto_n_threshold=req["auto_n_threshold"],
    )
    verified = is_independent(g, nodes)
    return (
        200,
        _json_headers(),
        {
            "nodes": list(nodes),
            "size": len(nodes),
            "verified": verified,
            "trace": {**(trace[0] if trace else {}), "budget_ms_source": req.get("budget_ms_source", "default")},
        },
    )


def native_json_plan_file(path: str, *, input_sha256: str, byte_length: int) -> HandlerResult:
    """Run MORPH directly on a validated JSON file, avoiding Python graph objects."""
    try:
        vertex_limit, edge_limit = native_graph_limits()
    except ValueError as exc:
        return _error(500, "invalid_server_configuration", [str(exc)])
    # The streaming adapters already admitted this staged file against the
    # free-space budget before writing it. Rechecking disk usage here would
    # subtract the staged upload twice and can reject a valid near-limit body.
    if byte_length <= 0 or byte_length > MAX_NATIVE_REQUEST_BYTES:
        return _error(413, "request_too_large")
    if len(input_sha256) != 64 or any(c not in "0123456789abcdef" for c in input_sha256.lower()):
        return _error(400, "invalid_sha256", ["X-Content-SHA256 must be 64 hexadecimal characters"])
    binary = os.getenv("MORPH_DUMP_BIN") or shutil.which("dump_morph")
    if not binary or not os.path.isfile(binary) or not os.access(binary, os.X_OK):
        return _error(503, "native_solver_unavailable", ["Build dump_morph and set MORPH_DUMP_BIN"])
    try:
        native_slots = int(os.getenv("PREDATOR_NATIVE_MAX_CONCURRENT", "1"))
        timeout_s = float(os.getenv("PREDATOR_NATIVE_TIMEOUT_S", "300"))
    except ValueError:
        return _error(500, "invalid_server_configuration", ["Native concurrency and timeout must be valid numbers"])
    try:
        upload_slots = int(os.getenv("PREDATOR_NATIVE_MAX_UPLOADS", "2"))
    except ValueError:
        return _error(500, "invalid_server_configuration", ["Native upload concurrency must be a valid integer"])
    if native_slots < 1 or native_slots > 16 or not 1 <= timeout_s <= 3600 or upload_slots < 1 or upload_slots > 8:
        return _error(500, "invalid_server_configuration", ["Native concurrency must be 1–16, uploads 1–8, and timeout 1–3600 seconds"])
    if not _native_limits_match_startup(native_slots, upload_slots):
        return _error(500, "invalid_server_configuration", ["Native concurrency limits must be set before API startup; restart the process after changing them"])
    if not _NATIVE_SLOTS.acquire(blocking=False):
        return _error(503, "native_solver_busy", ["Native solver concurrency limit reached; retry later"])
    try:
        try:
            returncode, stdout, stderr, oversized, native_wall_s = _run_native_bounded(binary, path, timeout_s)
        except subprocess.TimeoutExpired:
            return _error(504, "native_solver_timeout", [f"Native MORPH exceeded {timeout_s:g} seconds"])
        except (OSError, ValueError) as exc:
            return _error(500, "native_solver_launch_failed", [str(exc)])
        if oversized:
            return _error(502, "native_solver_output_too_large", ["Native solver stdout/stderr exceeded configured output bound"])
        if returncode != 0:
            return _error(400, "native_solver_rejected_input", [stderr[-2000:]])
        try:
            native = json.loads(stdout)
        except (TypeError, ValueError):
            return _error(502, "invalid_native_solver_response")
        if not isinstance(native, dict):
            return _error(502, "invalid_native_solver_response")
        nodes = native.get("nodes")
        if (type(native.get("n")) is not int or type(native.get("m")) is not int
                or type(native.get("budget_ms")) is not int or type(native.get("seed")) is not int
                or native.get("n") < 1 or native.get("m") < 0
                or native.get("n") > vertex_limit or native.get("m") > edge_limit
                or native.get("budget_ms") < 1 or native.get("seed") < 0
                or not isinstance(nodes, list) or any(type(v) is not int or v < 0 for v in nodes)
                or len(set(nodes)) != len(nodes) or native.get("verified") is not True
                or type(native.get("size")) is not int or len(nodes) != native.get("size")
                or any(v >= native["n"] for v in nodes)
                or type(native.get("verified")) is not bool or native.get("verified") is not True
                or any(type(native.get(k)) not in (int, float) for k in
                       ("json_parse_ms", "graph_build_ms", "solver_ms", "verification_ms", "total_ms"))):
            return _error(502, "native_solver_verification_failed")
        return (200, _json_headers(), {
            "nodes": nodes, "size": len(nodes), "verified": True,
            "trace": {"requested": "morph", "resolved": "morph", "native_json": True,
                      "input_sha256": input_sha256.lower(), "input_bytes": byte_length,
                      "n": native.get("n"), "m": native.get("m"),
                      "json_parse_ms": native.get("json_parse_ms"),
                      "graph_build_ms": native.get("graph_build_ms"),
                      "solver_ms": native.get("solver_ms"),
                      "verification_ms": native.get("verification_ms"),
                      "native_total_ms": native.get("total_ms"),
                      "native_process_wall_s": round(native_wall_s, 6),
                      "solver_budget_ms": native.get("budget_ms"),
                      "seed": native.get("seed"), "budget_ms_source": "request"},
        })
    finally:
        _NATIVE_SLOTS.release()


def handle_audit(body: Any) -> HandlerResult:
    req, errs = validate_audit_request(body)
    if errs or req is None:
        return _error(400, "validation_error", errs)
    g = _graph_from(req)
    report = run_audit(
        g,
        method=req["method"],
        budget_ms=req["budget_ms"],
        seed=req["seed"],
        include_dense=req["include_dense"],
        k_core_k=req["k_core_k"],
        graph_source=req.get("graph_source"),
    )
    v1 = report.to_v1_dict()
    ok, verrs = validate_report(v1)
    if not ok:
        return _error(500, "report_schema_failed", verrs)

    envelope = None
    signed = False
    if req["sign"]:
        secret = secret_from_env()
        if secret:
            envelope = sign_report_hmac(
                v1,
                secret,
                key_id=req["key_id"],
                producer={"organization": "dcpracmatic-prog", "service": "predator"},
            )
            signed = True

    return (
        200,
        _json_headers(),
        {"report": v1, "envelope": envelope, "signed": signed},
    )


def handle_request(
    method: str,
    path: str,
    body: Any = None,
) -> HandlerResult:
    """Route a single HTTP-like call. ``path`` without query string."""
    method = method.upper()
    # normalize
    if not path.startswith("/"):
        path = "/" + path
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")

    if method == "GET" and path == "/health":
        return handle_health()
    if method == "GET" and path == "/v1/status":
        return handle_status()
    if method == "GET" and path in ("/openapi.json", "/v1/openapi.json"):
        return handle_openapi()
    if method == "POST" and path == "/v1/plan":
        return handle_plan(body)
    if method == "POST" and path == "/v1/audit":
        return handle_audit(body)
    return _error(404, "not_found", [f"{method} {path}"])


def create_app():
    """Return a FastAPI app when fastapi is installed; else raise ImportError."""
    try:
        from fastapi import FastAPI, Request
        from fastapi.responses import JSONResponse
    except ImportError as e:
        raise ImportError(
            "FastAPI is optional. Use `predator-api` (stdlib) "
            "or `pip install fastapi uvicorn`."
        ) from e

    try:
        max_request_bytes()  # validate resource-limit configuration at startup
        max_native_request_bytes()
        native_graph_limits()
        native_upload_slots()
    except ValueError as exc:
        raise ValueError(f"invalid API request-size configuration: {exc}") from exc

    app = FastAPI(
        title="PREDATOR HTTP API",
        version=ENGINE_VERSION,
        license_info={"name": "AGPL-3.0"},
    )

    @app.middleware("http")
    async def security_middleware(request: Request, call_next):
        origin = request.headers.get("origin")
        if origin and not origin_is_allowed(origin):
            return JSONResponse({"error": "origin_not_allowed"}, status_code=403)
        if request.method != "OPTIONS" and not is_authorized(
            request.headers, public=request.method == "GET" and request.url.path == "/health"
        ):
            return JSONResponse({"error": "unauthorized"}, status_code=401,
                                headers={"WWW-Authenticate": "Bearer"})
        response = await call_next(request)
        if origin_is_allowed(origin):
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
        return response

    @app.options("/{path:path}")
    async def preflight(path: str, request: Request):
        origin = request.headers.get("origin")
        if origin and not origin_is_allowed(origin):
            return JSONResponse({"error": "origin_not_allowed"}, status_code=403)
        return JSONResponse({}, status_code=204)

    @app.get("/health")
    async def health():
        code, _, body = handle_health()
        return JSONResponse(body, status_code=code)

    @app.get("/v1/status")
    async def status():
        code, _, body = handle_status()
        return JSONResponse(body, status_code=code)

    @app.get("/openapi.json")
    async def openapi_json():
        code, _, body = handle_openapi()
        return JSONResponse(body, status_code=code)

    @app.post("/v1/plan")
    async def plan(request: Request):
        try:
            body = await request.json()
        except Exception:
            return JSONResponse(
                {"error": "invalid_json", "details": ["body must be JSON"]},
                status_code=400,
            )
        code, _, body_out = handle_plan(body)
        return JSONResponse(body_out, status_code=code)

    @app.post("/v1/plan/native-file")
    async def native_plan_file(request: Request):
        if not _NATIVE_UPLOAD_SLOTS.acquire(blocking=False):
            return JSONResponse({"error": "native_upload_busy"}, status_code=503)
        try:
            return await _native_plan_file_stream(request)
        finally:
            _NATIVE_UPLOAD_SLOTS.release()

    async def _native_plan_file_stream(request: Request):
        if request.headers.get("transfer-encoding", "").lower() not in ("", "identity"):
            return JSONResponse({"error": "unsupported_transfer_encoding"}, status_code=400)
        raw_length = request.headers.get("content-length")
        if raw_length is None or not raw_length.isdecimal() or int(raw_length) <= 0:
            return JSONResponse({"error": "invalid_content_length"}, status_code=400)
        expected = request.headers.get("x-content-sha256", "").strip().lower()
        if len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
            return JSONResponse({"error": "invalid_sha256"}, status_code=400)
        if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            return JSONResponse({"error": "content_type_must_be_application_json"}, status_code=415)
        try:
            native_body_limit = max_native_request_bytes()
        except ValueError as exc:
            return JSONResponse({"error": "invalid_server_configuration", "details": [str(exc)]}, status_code=500)
        if int(raw_length) > native_body_limit:
            return JSONResponse({"error": "request_too_large"}, status_code=413)
        digest = hashlib.sha256()
        total = 0
        temp_path = None
        upload_started = time.perf_counter()
        try:
            with tempfile.NamedTemporaryFile(prefix="predator-native-", suffix=".json", delete=False) as handle:
                temp_path = handle.name
                async for chunk in request.stream():
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > native_body_limit:
                        return JSONResponse({"error": "request_too_large"}, status_code=413)
                    digest.update(chunk)
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
                os.fchmod(handle.fileno(), 0o400)
            actual = digest.hexdigest()
            if not hmac.compare_digest(actual, expected):
                return JSONResponse({"error": "sha256_mismatch", "actual": actual}, status_code=400)
            from starlette.concurrency import run_in_threadpool
            pipeline_started = time.perf_counter()
            status_code, _, result = await run_in_threadpool(
                native_json_plan_file, temp_path, input_sha256=actual, byte_length=total
            )
            if isinstance(result.get("trace"), dict):
                result["trace"].update({"upload_hash_verify_s": round(pipeline_started - upload_started, 6),
                                        "request_process_s": round(time.perf_counter() - upload_started, 6),
                                        "streamed_bytes": total})
            return JSONResponse(result, status_code=status_code)
        except OSError as exc:
            return JSONResponse({"error": "request_body_read_failed", "details": [str(exc)]}, status_code=400)
        finally:
            if temp_path:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass

    @app.post("/v1/audit")
    async def audit(request: Request):
        try:
            body = await request.json()
        except Exception:
            return JSONResponse(
                {"error": "invalid_json", "details": ["body must be JSON"]},
                status_code=400,
            )
        code, _, body_out = handle_audit(body)
        return JSONResponse(body_out, status_code=code)

    class RequestSizeLimitASGI:
        """Bound buffered request bodies for the optional FastAPI adapter."""

        def __init__(self, wrapped, max_bytes: int):
            self.wrapped = wrapped
            self.max_bytes = max_bytes

        async def __call__(self, scope, receive, send):
            if scope["type"] != "http":
                return await self.wrapped(scope, receive, send)
            # Keep the native file endpoint streamed end-to-end; its handler
            # enforces the same byte cap while hashing/writing each chunk.
            if scope.get("path") == "/v1/plan/native-file":
                headers = {key.lower(): value for key, value in scope.get("headers", [])}
                length = headers.get(b"content-length")
                if length is None:
                    response = JSONResponse({"error": "invalid_content_length"}, status_code=400)
                    return await response(scope, receive, send)
                if length is not None:
                    if not length.isdigit():
                        response = JSONResponse({"error": "invalid_content_length"}, status_code=400)
                        return await response(scope, receive, send)
                    try:
                        endpoint_limit = max_native_request_bytes()
                    except ValueError as exc:
                        response = JSONResponse({"error": "invalid_server_configuration", "details": [str(exc)]}, status_code=500)
                        return await response(scope, receive, send)
                    if int(length) > endpoint_limit:
                        response = JSONResponse({"error": "request_too_large"}, status_code=413)
                        return await response(scope, receive, send)
                return await self.wrapped(scope, receive, send)
            headers = {key.lower(): value for key, value in scope.get("headers", [])}
            length = headers.get(b"content-length")
            if length is not None:
                try:
                    if not length.isdigit():
                        raise ValueError("Content-Length must be a non-negative decimal integer")
                    declared_length = int(length)
                    if declared_length > self.max_bytes:
                        response = JSONResponse({"error": "request_too_large"}, status_code=413)
                        return await response(scope, receive, send)
                except ValueError:
                    response = JSONResponse({"error": "invalid_content_length"}, status_code=400)
                    return await response(scope, receive, send)
            chunks = []
            total = 0
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                chunk = message.get("body", b"")
                total += len(chunk)
                if total > self.max_bytes:
                    response = JSONResponse({"error": "request_too_large"}, status_code=413)
                    return await response(scope, receive, send)
                chunks.append(chunk)
                if not message.get("more_body", False):
                    break
            body = b"".join(chunks)
            sent = False

            async def replay_body():
                nonlocal sent
                if not sent:
                    sent = True
                    return {"type": "http.request", "body": body, "more_body": False}
                return {"type": "http.request", "body": b"", "more_body": False}

            await self.wrapped(scope, replay_body, send)

    try:
        request_limit = max_request_bytes()
    except ValueError as exc:
        raise ValueError(f"invalid API request-size configuration: {exc}") from exc
    return RequestSizeLimitASGI(app, max_bytes=request_limit)
