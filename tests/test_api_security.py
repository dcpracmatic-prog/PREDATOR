from __future__ import annotations

import os
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from predator.api.security import cors_headers, is_authorized, origin_is_allowed
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
