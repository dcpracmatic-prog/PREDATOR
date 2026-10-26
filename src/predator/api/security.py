"""Shared authentication and CORS policy for the HTTP adapters."""
from __future__ import annotations

import hmac
import os
from typing import Mapping

from predator.hardware import MAX_REQUEST_BYTES, recommended_max_request_bytes


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
            "Access-Control-Allow-Headers": "Authorization, Content-Type",
        }
    return {}


def max_request_bytes() -> int:
    """Return the configured request cap, or a host-memory-aware default.

    The dynamic limit reserves a conservative 128x body expansion budget. It is
    not an RSS guarantee; representative graph workloads should be profiled. The
    hard cap prevents accidental/unbounded allocation. Set
    PREDATOR_MAX_REQUEST_BYTES to a positive value no larger than 64 MiB to
    override the recommended default for a known workload.
    """
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
