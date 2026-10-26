"""Shared authentication and CORS policy for the HTTP adapters."""
from __future__ import annotations

import hmac
import os
from typing import Mapping


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
