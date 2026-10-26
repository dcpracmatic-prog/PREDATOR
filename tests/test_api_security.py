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


def test_fastapi_adapter_auth_cors_and_request_size(monkeypatch):
    fastapi = pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from predator.api.app import create_app

    monkeypatch.setenv("PREDATOR_API_TOKEN", "asgi-secret")
    monkeypatch.setenv("PREDATOR_CORS_ORIGINS", "https://ui.example")
    client = TestClient(create_app())
    assert client.get("/health").status_code == 200
    assert client.get("/v1/status").status_code == 401
    good = client.get("/v1/status", headers={"Authorization": "Bearer asgi-secret", "Origin": "https://ui.example"})
    assert good.status_code == 200
    assert good.headers.get("Access-Control-Allow-Origin") == "https://ui.example"
    bad = client.get("/v1/status", headers={"Authorization": "Bearer asgi-secret", "Origin": "https://bad.example"})
    assert bad.status_code == 403
    oversized = client.post("/v1/plan", content=b" " * (1_048_577), headers={"Authorization": "Bearer asgi-secret"})
    assert oversized.status_code == 413
