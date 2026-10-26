"""HTTP facade tests (no network)."""

from __future__ import annotations

import os
from pathlib import Path

from predator.api.app import handle_request  # noqa: E402


def test_health():
    code, _, body = handle_request("GET", "/health")
    assert code == 200
    assert body["status"] == "ok"


def test_openapi_has_paths():
    code, _, body = handle_request("GET", "/openapi.json")
    assert code == 200
    assert body["openapi"].startswith("3.")
    assert "/v1/audit" in body["paths"]
    assert "/v1/plan" in body["paths"]


def test_plan_validation_error():
    code, _, body = handle_request("POST", "/v1/plan", {"graph": {"n": 2, "edges": [[0, 5]]}})
    assert code == 400
    assert body["error"] == "validation_error"


def test_plan_ok():
    code, _, body = handle_request(
        "POST",
        "/v1/plan",
        {
            "graph": {"n": 4, "edges": [[0, 1], [1, 2], [2, 3]]},
            "method": "auto",
            "budget_ms": 20,
            "seed": 1,
        },
    )
    assert code == 200
    assert body["verified"] is True
    assert body["size"] == len(body["nodes"])
    assert "resolved" in body["trace"]


def test_audit_signed_when_secret_set():
    os.environ["ZTGE_HMAC_SECRET"] = "hex:" + "ab" * 32
    code, _, body = handle_request(
        "POST",
        "/v1/audit",
        {
            "graph": {"n": 5, "edges": [[0, 1], [1, 2], [2, 3]]},
            "method": "auto",
            "budget_ms": 20,
            "sign": True,
        },
    )
    assert code == 200
    assert body["report"]["schema_version"] == "ztge.audit.v1"
    assert body["signed"] is True
    assert body["envelope"]["envelope_version"] == "ztge.envelope.v1"
    assert body["envelope"]["producer"]["service"] == "predator"
