"""Shared authentication and CORS policy for the HTTP adapters."""
from __future__ import annotations

import hmac
import os
import shutil
import tempfile
from typing import Mapping

from predator.hardware import MAX_REQUEST_BYTES, recommended_max_request_bytes

MAX_NATIVE_REQUEST_BYTES = 50 * 1024**3


def allowed_origins() -> frozenset[str]:
    """Origins allowed by PREDATOR_CORS_ORIGINS (comma-separated exact origins)."""
    return frozenset(item.strip() for item in os.getenv("PREDATOR_CORS_ORIGINS", "").split(",") if item.strip())


def origin_is_allowed(origin: str | None) -> bool:
    return origin is not None and origin in allowed_origins()


def auth_configured() -> bool:
    return bool(os.getenv("PREDATOR_API_TOKEN", ""))


def is_authorized(headers: Mapping[str, str], *, public: bool = False) -> bool:
    """Require Bearer token when configured; allow only explicit public paths unauthenticated."""
    expected = os.getenv("PREDATOR_API_TOKEN", "")
    if not expected:
        return True
    if public:
        return True
    supplied = headers.get("Authorization", "")
    scheme, _, token = supplied.partition(" ")
    return scheme.lower() == "bearer" and bool(token) and hmac.compare_digest(token, expected)


def cors_headers(origin: str | None) -> dict[str, str]:
    if origin_is_allowed(origin):
        return {
            "Access-Control-Allow-Origin": origin or "",
            "Vary": "Origin",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Authorization, Content-Type, X-Content-SHA256",
        }
    return {}


def max_request_bytes() -> int:
    """Return the conventional buffered JSON endpoint cap (memory-aware, <=64 MiB)."""
    raw = os.getenv("PREDATOR_MAX_REQUEST_BYTES")
    if raw is None or not raw.strip():
        return recommended_max_request_bytes()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError("PREDATOR_MAX_REQUEST_BYTES must be an integer") from exc
    if value < 1 or value > MAX_REQUEST_BYTES:
        raise ValueError(f"PREDATOR_MAX_REQUEST_BYTES must be in [1, {MAX_REQUEST_BYTES}]")
    return value


def native_upload_slots() -> int:
    """Number of simultaneous disk staging uploads (bounded at startup)."""
    raw = os.getenv("PREDATOR_NATIVE_MAX_UPLOADS", "2")
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError("PREDATOR_NATIVE_MAX_UPLOADS must be an integer") from exc
    if value < 1 or value > 8:
        raise ValueError("PREDATOR_NATIVE_MAX_UPLOADS must be in [1, 8]")
    return value


def _native_staging_budget_bytes() -> int:
    """Reserve JSON staging plus worst-case native edge spool for each upload.

    The parser's spool stores 8 bytes per edge and the executable has a 10M
    edge hard cap (80 MiB). Subtract that per active upload before admitting
    a request; otherwise an upload can fill the staging filesystem while MORPH
    writes its second copy of the edge stream.
    """
    try:
        free = shutil.disk_usage(tempfile.gettempdir()).free
    except OSError:
        # Filesystem capacity cannot be verified: allow only a modest bounded path.
        # The actual spool's disk path cannot be budgeted if filesystem stats
        # are unavailable; keep both staged input and spool modest.
        return 32 * 1024 * 1024
    try:
        uploads = native_upload_slots()
    except ValueError:
        uploads = 2
    per_upload = (free * 4 // 5) // uploads
    spool_reserve = 80 * 1024 * 1024
    if per_upload <= spool_reserve:
        return 1
    return min(MAX_NATIVE_REQUEST_BYTES, per_upload - spool_reserve)


def max_native_request_bytes() -> int:
    """Dynamic streamed-body cap from staging storage (80% / upload slots; 50 GiB max).

    PREDATOR_NATIVE_MAX_REQUEST_BYTES may reduce the limit, but never raises the
    available-space-derived cap. The limit is checked initially and while streaming.
    """
    raw = os.getenv("PREDATOR_NATIVE_MAX_REQUEST_BYTES")
    if raw is not None and raw.strip():
        try:
            configured = int(raw)
        except ValueError as exc:
            raise ValueError("PREDATOR_NATIVE_MAX_REQUEST_BYTES must be an integer") from exc
        if configured < 1 or configured > MAX_NATIVE_REQUEST_BYTES:
            raise ValueError(f"PREDATOR_NATIVE_MAX_REQUEST_BYTES must be in [1, {MAX_NATIVE_REQUEST_BYTES}]")
        return min(configured, _native_staging_budget_bytes())
    return _native_staging_budget_bytes()


def native_graph_limits(memory_bytes: int | None = None) -> tuple[int, int]:
    """Conservative RAM-adaptive native parser limits; absolute MORPH caps still apply.

    One quarter of available RAM is provisionally budgeted independently at 512
    bytes per vertex and 128 bytes per edge (so their combined budget is about half
    of RAM). This heuristic is not a peak-RSS guarantee; explicit
    PREDATOR_NATIVE_MAX_VERTICES/EDGES values can only lower the calculated caps.
    """
    from predator.hardware import available_memory_bytes

    memory = available_memory_bytes() if memory_bytes is None else memory_bytes
    budget = 128 * 1024 * 1024 if memory is None else max(0, int(memory) // 4)
    limits = {
        "PREDATOR_NATIVE_MAX_VERTICES": min(2_000_000, budget // 512),
        "PREDATOR_NATIVE_MAX_EDGES": min(10_000_000, budget // 128),
    }
    hard_limits = {"PREDATOR_NATIVE_MAX_VERTICES": 2_000_000, "PREDATOR_NATIVE_MAX_EDGES": 10_000_000}
    for key, calculated in tuple(limits.items()):
        raw = os.getenv(key)
        if raw is None or not raw.strip():
            continue
        try:
            configured = int(raw)
        except ValueError as exc:
            raise ValueError(f"{key} must be an integer") from exc
        if configured < 1 or configured > hard_limits[key]:
            raise ValueError(f"{key} must be in [1, {hard_limits[key]}]")
        limits[key] = min(calculated, configured)
    return max(1, limits["PREDATOR_NATIVE_MAX_VERTICES"]), max(1, limits["PREDATOR_NATIVE_MAX_EDGES"])


def native_solver_environment() -> dict[str, str]:
    """Return current host-specific parser caps for the native MORPH subprocess."""
    vertices, edges = native_graph_limits()
    return {"PREDATOR_NATIVE_MAX_VERTICES": str(vertices), "PREDATOR_NATIVE_MAX_EDGES": str(edges)}
