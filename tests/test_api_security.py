from __future__ import annotations

import os
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from predator.api.security import cors_headers, is_authorized, max_request_bytes, origin_is_allowed
from predator.api.server import PredatorHandler, main


def test_bearer_authentication_and_exact_origin_allowlist(monkeypatch):
    monkeypatch.setenv("PREDATOR_API_TOKEN", "secret-value")
    monkeypatch.setenv("PREDATOR_CORS_ORIGINS", "https://trusted.example, https://second.example")
    assert is_authorized({"Authorization": "Bearer secret-value"})
    assert not is_authorized({"Authorization": "Bearer wrong"})
    assert is_authorized({}, public=True)
    assert origin_is_allowed("https://trusted.example")
    assert not origin_is_allowed("https://evil.example")
    assert cors_headers("https://evil.example") == {}
    assert cors_headers("https://trusted.example")["Access-Control-Allow-Origin"] == "https://trusted.example"


def test_server_rejects_non_loopback_without_bearer_token(monkeypatch):
    monkeypatch.delenv("PREDATOR_API_TOKEN", raising=False)
    with pytest.raises(SystemExit):
        main(["--host", "0.0.0.0", "--port", "0"])


def test_fastapi_origin_auth_and_body_size_limits(monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from predator.api.app import create_app

    monkeypatch.setenv("PREDATOR_CORS_ORIGINS", "https://trusted.example")
    monkeypatch.setenv("PREDATOR_API_TOKEN", "integration-secret")
    monkeypatch.setenv("PREDATOR_MAX_REQUEST_BYTES", str(1_048_576))
    with TestClient(create_app()) as client:
        denied_origin = client.post("/v1/plan", headers={"Origin": "https://evil.example", "Authorization": "Bearer integration-secret"}, json={})
        assert denied_origin.status_code == 403

        unauthorized = client.post("/v1/plan", headers={"Origin": "https://trusted.example"}, json={})
        assert unauthorized.status_code == 401

        accepted = client.post("/v1/plan", headers={"Origin": "https://trusted.example", "Authorization": "Bearer integration-secret"}, json={
            "graph": {"n": 3, "edges": [[0, 1], [1, 2]]}, "method": "gwmin"
        })
        assert accepted.status_code == 200
        assert accepted.headers["access-control-allow-origin"] == "https://trusted.example"

        oversized = client.post("/v1/plan", headers={"Authorization": "Bearer integration-secret"}, content=b"x" * (1_048_576 + 1))
        assert oversized.status_code == 413


def test_http_handler_authentication_gate_without_network(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock

    monkeypatch.setenv("PREDATOR_API_TOKEN", "integration-secret")
    fake = SimpleNamespace(headers={}, _write=Mock())
    assert PredatorHandler._authorized(fake, "POST", "/v1/plan") is False
    fake._write.assert_called_once()
    assert fake._write.call_args.args[0] == 401
    fake._write.reset_mock()
    fake.headers = {"Authorization": "Bearer integration-secret"}
    assert PredatorHandler._authorized(fake, "POST", "/v1/plan") is True
    fake._write.assert_not_called()


def test_request_limit_can_be_configured_and_is_bounded(monkeypatch):
    from predator.hardware import MAX_REQUEST_BYTES
    monkeypatch.setenv("PREDATOR_MAX_REQUEST_BYTES", "33554432")
    assert max_request_bytes() == 33_554_432
    monkeypatch.setenv("PREDATOR_MAX_REQUEST_BYTES", str(MAX_REQUEST_BYTES + 1))
    with pytest.raises(ValueError, match="must be in"):
        max_request_bytes()
    monkeypatch.setenv("PREDATOR_MAX_REQUEST_BYTES", "not-a-number")
    with pytest.raises(ValueError, match="must be an integer"):
        max_request_bytes()

def test_recommended_request_limit_tracks_memory_and_has_cap(monkeypatch):
    from predator.hardware import MAX_REQUEST_BYTES, MiB, recommended_max_request_bytes
    monkeypatch.setattr("predator.hardware.available_memory_bytes", lambda: None)
    assert recommended_max_request_bytes() == MiB
    assert recommended_max_request_bytes(32 * MiB) == 256 * 1024
    assert recommended_max_request_bytes(1024) == 64 * 1024
    assert recommended_max_request_bytes(0) == 64 * 1024
    assert recommended_max_request_bytes(1024 * MiB) == 8 * MiB
    assert recommended_max_request_bytes(16 * 1024 * MiB) == MAX_REQUEST_BYTES


def test_stdlib_http_enforces_configured_request_limit(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock

    monkeypatch.setenv("PREDATOR_MAX_REQUEST_BYTES", "4")
    fake = SimpleNamespace(
        headers={"Content-Length": "5"}, path="/v1/plan",
        _origin_allowed=lambda: True, _authorized=lambda *_: True, _write=Mock(),
    )
    PredatorHandler.do_POST(fake)
    fake._write.assert_called_once()
    assert fake._write.call_args.args[0] == 413
    assert fake._write.call_args.args[2]["error"] == "request_too_large"


def test_stdlib_rejects_malformed_or_duplicate_content_length(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock
    monkeypatch.delenv("PREDATOR_MAX_REQUEST_BYTES", raising=False)
    for headers in ({"Content-Length": "-1"}, {"Content-Length": "1.5"},
                    {"Content-Length": "4, 4"}, {"Content-Length": ""}):
        fake = SimpleNamespace(headers=headers, path="/v1/plan",
                               _origin_allowed=lambda: True, _authorized=lambda *_: True, _write=Mock())
        PredatorHandler.do_POST(fake)
        fake._write.assert_called_once()
        assert fake._write.call_args.args[0] == 400
        assert fake._write.call_args.args[2]["error"] == "invalid_content_length"


def test_stdlib_rejects_missing_content_length_and_chunked_transfer(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock
    monkeypatch.delenv("PREDATOR_MAX_REQUEST_BYTES", raising=False)
    for headers, expected in (({}, "invalid_content_length"),
                              ({"Transfer-Encoding": "chunked"}, "unsupported_transfer_encoding")):
        fake = SimpleNamespace(headers=headers, path="/v1/plan",
                               _origin_allowed=lambda: True, _authorized=lambda *_: True, _write=Mock())
        PredatorHandler.do_POST(fake)
        fake._write.assert_called_once()
        assert fake._write.call_args.args[0] == 400
        assert fake._write.call_args.args[2]["error"] == expected


def test_fastapi_rejects_malformed_content_length(monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from predator.api.app import create_app
    monkeypatch.setenv("PREDATOR_MAX_REQUEST_BYTES", "100")
    with TestClient(create_app()) as client:
        response = client.post("/v1/plan", headers={"content-length": "-1"}, content=b"{}")
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_content_length"


def test_audit_request_rejects_coercive_types():
    from predator.api.validation import validate_audit_request
    base = {"graph": {"n": 0, "edges": []}}
    for field, value in (("k_core_k", 2.5), ("k_core_k", True), ("sign", "false"), ("include_dense", 0)):
        parsed, errors = validate_audit_request({**base, field: value})
        assert parsed is None and errors


def test_resource_estimates_respect_cgroup_available_memory(monkeypatch):
    from pathlib import Path
    from predator.hardware import available_memory_bytes, max_graph_vertices
    leaf = Path("/sys/fs/cgroup/job/worker")
    monkeypatch.setattr("predator.hardware._cgroup_dirs", lambda controller: [leaf, leaf.parent, Path("/sys/fs/cgroup")])
    values = {
        "/sys/fs/cgroup/job/worker/memory.max": None,
        "/sys/fs/cgroup/job/worker/memory.current": None,
        "/sys/fs/cgroup/job/memory.max": 1024 * 1024 * 1024,
        "/sys/fs/cgroup/job/memory.current": 768 * 1024 * 1024,
        "/sys/fs/cgroup/memory.max": None,
        "/sys/fs/cgroup/memory.current": None,
        "/sys/fs/cgroup/memory/memory.limit_in_bytes": None,
        "/sys/fs/cgroup/memory/memory.usage_in_bytes": None,
    }
    monkeypatch.setattr("predator.hardware._read_int", lambda path: values.get(path))
    monkeypatch.setattr(Path, "read_text", lambda self, *args, **kwargs: "")
    assert available_memory_bytes() == 256 * 1024 * 1024
    assert max_graph_vertices(8 * 1024 * 1024) == 256


def test_graph_edge_limit_adapts_to_available_memory():
    from predator.hardware import max_graph_edges
    assert max_graph_edges(1024 * 1024) == 256
    assert max_graph_edges(64 * 1024 * 1024 * 1024) == 10_000_000


def test_unknown_memory_falls_back_to_conservative_graph_bounds(monkeypatch):
    from predator.hardware import max_graph_edges, max_graph_vertices
    monkeypatch.setattr("predator.hardware.available_memory_bytes", lambda: None)
    assert max_graph_vertices() == 2_048
    assert max_graph_edges() == 10_000
