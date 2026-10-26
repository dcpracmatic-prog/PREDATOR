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


def test_health_status_contracts_list_is_included():
    code, _, body = handle_request("GET", "/v1/status")
    assert code == 200
    assert {"clique.yaml", "independent_set.yaml"} <= set(body["contracts"])


def test_audit_report_payload_uses_predator_engine_name():
    code, _, body = handle_request("POST", "/v1/audit", {
        "graph": {"n": 3, "edges": [[0, 1], [1, 2]]}, "method": "gwmin", "sign": False,
    })
    assert code == 200
    assert body["report"]["engine"]["name"] == "predator"
    assert body["report"]["schema_version"] == "ztge.audit.v1"


import pytest

@pytest.mark.parametrize("graph", [
    {"n": 2.9, "edges": [[0, 1]]},
    {"n": True, "edges": [[0, 1]]},
    {"n": "2", "edges": [[0, 1]]},
    {"n": 2, "edges": [[0.9, 1]]},
    {"n": 2, "edges": [[False, 1]]},
    {"n": 2, "edges": [["0", 1]]},
])
def test_plan_rejects_non_json_integer_graph_fields(graph):
    code, _, body = handle_request("POST", "/v1/plan", {"graph": graph, "method": "gwmin"})
    assert code == 400
    assert body["error"] == "validation_error"

@pytest.mark.parametrize("field,value", [
    ("budget_ms", 1.5), ("budget_ms", True),
    ("seed", "4"), ("seed", False),
    ("auto_n_threshold", 2.5), ("auto_n_threshold", True),
])
def test_plan_rejects_non_integer_planner_parameters(field, value):
    body = {"graph": {"n": 2, "edges": [[0, 1]]}, "method": "gwmin", field: value}
    code, _, response = handle_request("POST", "/v1/plan", body)
    assert code == 400
    assert response["error"] == "validation_error"


def test_plan_rejects_non_boolean_directed():
    code, _, body = handle_request("POST", "/v1/plan", {
        "graph": {"n": 2, "edges": [[0, 1]], "directed": "false"},
        "method": "gwmin",
    })
    assert code == 400
    assert body["error"] == "validation_error"

def test_plan_rejects_graph_over_native_vertex_limit(monkeypatch):
    monkeypatch.setattr("predator.api.validation.max_graph_vertices", lambda: 2)
    code, _, body = handle_request("POST", "/v1/plan", {"graph": {"n": 3, "edges": []}})
    assert code == 400
    assert "resource-aware limit" in body["details"][0]


def test_plan_rejects_negative_seed():
    code, _, body = handle_request("POST", "/v1/plan", {
        "graph": {"n": 2, "edges": [[0, 1]]}, "method": "gwmin", "seed": -1,
    })
    assert code == 400
    assert "seed must be >= 0" in body["details"]

def test_plan_rejects_edges_over_memory_aware_limit(monkeypatch):
    monkeypatch.setattr("predator.api.validation.max_graph_edges", lambda: 1)
    code, _, body = handle_request("POST", "/v1/plan", {
        "graph": {"n": 3, "edges": [[0, 1], [1, 2]]}, "method": "gwmin",
    })
    assert code == 400
    assert "resource-aware/native limit" in body["details"][0]


def test_explicit_budget_overrides_profile_recommendation(monkeypatch):
    monkeypatch.setattr("predator.api.validation.recommended_morph_budget_ms", lambda n: 250)
    code, _, body = handle_request("POST", "/v1/plan", {
        "graph": {"n": 4, "edges": [[0, 1], [1, 2], [2, 3]]},
        "method": "morph", "budget_ms": 20,
    })
    assert code == 200
    assert body["trace"]["budget_ms_source"] == "request"


def test_profile_budget_used_only_for_implicit_morph_request(monkeypatch):
    from predator.api import app
    observed = {}
    def fake_plan(graph, *, method, budget_ms, seed, trace_out, auto_n_threshold):
        observed.update(method=method, budget_ms=budget_ms)
        trace_out.append({"requested": method, "resolved": method, "fallback": False, "morph": {"budget_ms": budget_ms}})
        return [0, 2]
    monkeypatch.setattr("predator.api.validation.recommended_morph_budget_ms", lambda n: 250)
    monkeypatch.setattr(app, "plan_independent", fake_plan)
    code, _, body = handle_request("POST", "/v1/plan", {
        "graph": {"n": 4, "edges": [[0, 1], [1, 2], [2, 3]]}, "method": "morph",
    })
    assert code == 200
    assert observed == {"method": "morph", "budget_ms": 250}
    assert body["trace"]["budget_ms_source"] == "hardware_profile"
    assert body["trace"]["morph"]["budget_ms"] == 250


def test_implicit_auto_small_graph_does_not_use_morph_profile_budget(monkeypatch):
    monkeypatch.setattr("predator.api.validation.recommended_morph_budget_ms", lambda n: 250)
    code, _, body = handle_request("POST", "/v1/plan", {
        "graph": {"n": 4, "edges": [[0, 1], [1, 2], [2, 3]]}, "method": "auto",
    })
    assert code == 200
    assert body["trace"]["budget_ms_source"] == "default"
    assert body["trace"]["resolved"] == "gwmin"


@pytest.mark.parametrize("field,value", [("k_core_k", 2.5), ("k_core_k", True), ("sign", "false"), ("include_dense", 0), ("graph_source", 123)])
def test_audit_rejects_wrong_json_types(field, value):
    body = {"graph": {"n": 2, "edges": [[0, 1]]}, "sign": False}
    body[field] = value
    code, _, response = handle_request("POST", "/v1/audit", body)
    assert code == 400
    assert response["error"] == "validation_error"

def test_explicit_null_budget_is_not_silently_treated_as_omitted():
    code, _, body = handle_request("POST", "/v1/plan", {
        "graph": {"n": 2, "edges": [[0, 1]]}, "method": "gwmin", "budget_ms": None,
    })
    assert code == 400
    assert "budget_ms must be an integer" in body["details"][0]
