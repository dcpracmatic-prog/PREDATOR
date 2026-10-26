"""HTTP request handlers for PREDATOR.

Works without FastAPI: ``handle_request(method, path, body)`` returns
``(status_code, headers, body_dict)``. Optional ``create_app()`` returns a
FastAPI application when the package is installed.
"""

import json
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
from .security import is_authorized, max_request_bytes, origin_is_allowed
from .validation import validate_audit_request, validate_plan_request

ENGINE = "predator"
ENGINE_VERSION = "0.2.0"

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
