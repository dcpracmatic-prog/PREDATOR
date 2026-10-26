from __future__ import annotations

import hashlib
import json
import os
import subprocess
from email.message import Message
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from predator.api import app as api_app
from predator.api.server import PredatorHandler


def _request(body: bytes, sha: str | None = None) -> Message:
    headers = Message()
    headers["Content-Length"] = str(len(body))
    headers["Content-Type"] = "application/json"
    if sha is not None:
        headers["X-Content-SHA256"] = sha
    return headers


def _fake_solver(tmp_path: Path) -> Path:
    solver = tmp_path / "fake_dump_morph.py"
    solver.write_text(
        "#!/usr/bin/env python3\n"
        "import json,sys\n"
        "from pathlib import Path\n"
        "p=json.loads(Path(sys.argv[2]).read_text())\n"
        "n=p['graph']['n']; e=p['graph']['edges']; chosen=[]\n"
        "for v in range(n):\n"
        " if all(not (a==v and b in chosen or b==v and a in chosen) for a,b in e): chosen.append(v)\n"
        "print(json.dumps({'n':n,'m':len(e),'size':len(chosen),'verified':True,'budget_ms':p.get('budget_ms',100),'seed':p.get('seed',1),'json_parse_ms':0.1,'graph_build_ms':0.2,'solver_ms':0.25,'verification_ms':0.03,'serialization_ms':0.01,'total_ms':0.59,'nodes':chosen}))\n",
        encoding="utf-8",
    )
    solver.chmod(0o755)
    return solver


def _handler(body: bytes, headers: Message):
    return SimpleNamespace(headers=headers, rfile=BytesIO(body), _write=Mock())


def test_native_stream_route_checks_hash_and_delegates_without_python_graph(monkeypatch, tmp_path):
    payload = json.dumps({"graph": {"n": 3, "edges": [[0, 1], [1, 2]]},
                          "method": "morph", "budget_ms": 10, "seed": 3}).encode()
    sha = hashlib.sha256(payload).hexdigest()
    solver = _fake_solver(tmp_path)
    monkeypatch.setenv("PREDATOR_NATIVE_JSON_ENABLED", "1")
    monkeypatch.setenv("MORPH_DUMP_BIN", str(solver))
    monkeypatch.setenv("PREDATOR_NATIVE_MAX_REQUEST_BYTES", "100000")

    # If route accidentally materializes Python graph or calls planner, fail.
    monkeypatch.setattr(api_app, "_graph_from", lambda *_: (_ for _ in ()).throw(AssertionError("Python graph path used")))
    monkeypatch.setattr(api_app, "plan_independent", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("Python planner used")))
    request = _handler(payload, _request(payload, sha))
    PredatorHandler._stream_native_json_file(request)
    request._write.assert_called_once()
    status, _, response = request._write.call_args.args
    assert status == 200
    assert response["verified"] is True
    assert response["trace"]["native_json"] is True
    assert response["trace"]["input_sha256"] == sha
    assert response["trace"]["streamed_bytes"] == len(payload)


def test_native_stream_rejects_mismatched_hash_before_solver(monkeypatch, tmp_path):
    payload = b'{"graph":{"n":1,"edges":[]},"method":"morph"}'
    solver = _fake_solver(tmp_path)
    called = []
    monkeypatch.setenv("PREDATOR_NATIVE_JSON_ENABLED", "1")
    monkeypatch.setenv("MORPH_DUMP_BIN", str(solver))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: called.append(True))
    request = _handler(payload, _request(payload, "0" * 64))
    PredatorHandler._stream_native_json_file(request)
    assert called == []
    assert request._write.call_args.args[0] == 400
    assert request._write.call_args.args[2]["error"] == "sha256_mismatch"


def test_native_stream_route_is_available_by_default(monkeypatch, tmp_path):
    monkeypatch.delenv("PREDATOR_NATIVE_JSON_ENABLED", raising=False)
    payload = b'{"graph":{"n":2,"edges":[[0,1]]},"method":"morph"}'
    solver = _fake_solver(tmp_path)
    monkeypatch.setenv("MORPH_DUMP_BIN", str(solver))
    request = _handler(payload, _request(payload, hashlib.sha256(payload).hexdigest()))
    PredatorHandler._stream_native_json_file(request)
    assert request._write.call_args.args[0] == 200
    assert request._write.call_args.args[2]["verified"] is True
    assert "native_json_disabled" not in request._write.call_args.args[2]
    assert "PREDATOR_NATIVE_JSON_ENABLED" not in request._write.call_args.args[2].get("details", [])


def test_native_upload_capacity_adapts_to_disk_and_concurrency(monkeypatch):
    from types import SimpleNamespace
    from predator.api.security import MAX_NATIVE_REQUEST_BYTES, max_native_request_bytes
    monkeypatch.delenv("PREDATOR_NATIVE_MAX_REQUEST_BYTES", raising=False)
    monkeypatch.setenv("PREDATOR_NATIVE_MAX_UPLOADS", "4")
    monkeypatch.setattr("predator.api.security.shutil.disk_usage", lambda _path: SimpleNamespace(free=1000 * 1024**3))
    assert max_native_request_bytes() == MAX_NATIVE_REQUEST_BYTES
    monkeypatch.setattr("predator.api.security.shutil.disk_usage", lambda _path: SimpleNamespace(free=100 * 1024**2))
    assert max_native_request_bytes() == 1


def test_native_upload_cap_fallback_override_and_ceiling(monkeypatch):
    from types import SimpleNamespace
    from predator.api.security import MAX_NATIVE_REQUEST_BYTES, max_native_request_bytes
    monkeypatch.delenv("PREDATOR_NATIVE_MAX_REQUEST_BYTES", raising=False)
    monkeypatch.setenv("PREDATOR_NATIVE_MAX_UPLOADS", "2")
    monkeypatch.setattr("predator.api.security.shutil.disk_usage", lambda _path: (_ for _ in ()).throw(OSError("unavailable")))
    assert max_native_request_bytes() == 32 * 1024**2
    monkeypatch.setenv("PREDATOR_NATIVE_MAX_REQUEST_BYTES", "1048576")
    assert max_native_request_bytes() == 1048576
    monkeypatch.setenv("PREDATOR_NATIVE_MAX_REQUEST_BYTES", str(MAX_NATIVE_REQUEST_BYTES))
    assert max_native_request_bytes() == 32 * 1024**2
    monkeypatch.setattr("predator.api.security.shutil.disk_usage", lambda _path: SimpleNamespace(free=1000 * 1024**3))
    assert max_native_request_bytes() == MAX_NATIVE_REQUEST_BYTES
    monkeypatch.setenv("PREDATOR_NATIVE_MAX_REQUEST_BYTES", str(MAX_NATIVE_REQUEST_BYTES + 1))
    import pytest
    with pytest.raises(ValueError):
        max_native_request_bytes()


def test_native_graph_limits_are_memory_adaptive_and_operator_can_only_lower(monkeypatch):
    from predator.api.security import native_graph_limits
    monkeypatch.delenv("PREDATOR_NATIVE_MAX_VERTICES", raising=False)
    monkeypatch.delenv("PREDATOR_NATIVE_MAX_EDGES", raising=False)
    assert native_graph_limits(1024 * 1024 * 1024) == (524_288, 2_097_152)
    monkeypatch.setenv("PREDATOR_NATIVE_MAX_VERTICES", "100")
    assert native_graph_limits(1024 * 1024 * 1024) == (100, 2_097_152)
    monkeypatch.setenv("PREDATOR_NATIVE_MAX_EDGES", "10000001")
    import pytest
    with pytest.raises(ValueError):
        native_graph_limits(1024 * 1024 * 1024)


def test_native_stream_limit_rejects_early_without_reading_body(monkeypatch):
    monkeypatch.setenv("PREDATOR_NATIVE_MAX_REQUEST_BYTES", "32")
    request = _handler(b"x" * 128, _request(b"x" * 128, "0" * 64))
    PredatorHandler._stream_native_json_file(request)
    assert request._write.call_args.args[0] == 413
    assert request._write.call_args.args[2]["error"] == "request_too_large"
    assert request.rfile.tell() == 0


def test_native_stream_large_payload_over_one_mib_reaches_solver(monkeypatch, tmp_path):
    solver = _fake_solver(tmp_path)
    # Keep the graph tiny while adding ignored JSON padding, to test streaming
    # and integrity rather than accidental Python graph materialization.
    payload = (b'{"graph":{"n":2,"edges":[[0,1]]},"method":"morph","padding":"'
               + b"x" * (1024 * 1024) + b'"}')
    sha = hashlib.sha256(payload).hexdigest()
    monkeypatch.setenv("PREDATOR_NATIVE_MAX_REQUEST_BYTES", str(len(payload) + 100))
    monkeypatch.setenv("MORPH_DUMP_BIN", str(solver))
    monkeypatch.setattr("predator.api.app._graph_from", lambda *_: (_ for _ in ()).throw(AssertionError("Python graph parsed")))
    request = _handler(payload, _request(payload, sha))
    PredatorHandler._stream_native_json_file(request)
    code, _, result = request._write.call_args.args
    assert code == 200
    assert result["trace"]["input_bytes"] > 1024 * 1024
    assert result["trace"]["input_sha256"] == sha
    assert result["verified"] is True
    assert result["trace"]["streamed_bytes"] == len(payload)
    assert not list(tmp_path.glob("predator-native-*.json"))




def test_fastapi_cors_preflight_allows_native_sha256_header(monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from predator.api.app import create_app

    monkeypatch.setenv("PREDATOR_CORS_ORIGINS", "https://trusted.example")
    with TestClient(create_app()) as client:
        response = client.options("/v1/plan/native-file", headers={
            "Origin": "https://trusted.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type, x-content-sha256",
        })
    assert response.status_code == 204
    assert "x-content-sha256" in response.headers["access-control-allow-headers"].lower()


def test_fastapi_native_endpoint_uses_native_upload_cap_not_ordinary_cap(monkeypatch, tmp_path):
    fastapi = pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from predator.api.app import create_app

    payload = json.dumps({"graph": {"n": 3, "edges": [[0, 1]]}, "method": "morph"}).encode()
    sha = hashlib.sha256(payload).hexdigest()
    solver = _fake_solver(tmp_path)
    monkeypatch.setenv("PREDATOR_NATIVE_JSON_ENABLED", "1")
    monkeypatch.setenv("MORPH_DUMP_BIN", str(solver))
    monkeypatch.setenv("PREDATOR_MAX_REQUEST_BYTES", "128")
    monkeypatch.setenv("PREDATOR_NATIVE_MAX_REQUEST_BYTES", "100000")
    with TestClient(create_app()) as client:
        response = client.post("/v1/plan/native-file", content=payload, headers={
            "Content-Type": "application/json", "X-Content-SHA256": sha,
        })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["verified"] is True
    assert body["trace"]["streamed_bytes"] == len(payload)


def test_native_output_is_bounded_and_shape_checked(monkeypatch, tmp_path):
    bad_solver = tmp_path / "bad-solver"
    bad_solver.write_text("#!/bin/sh\nprintf '%s' '{\"nodes\":[0,0],\"size\":2,\"verified\":true,\"n\":1,\"m\":0}'\n", encoding="utf-8")
    bad_solver.chmod(0o755)
    monkeypatch.setenv("PREDATOR_NATIVE_JSON_ENABLED", "1")
    monkeypatch.setenv("MORPH_DUMP_BIN", str(bad_solver))
    monkeypatch.setenv("PREDATOR_NATIVE_TIMEOUT_S", "5")
    path = tmp_path / "input.json"
    path.write_text('{"graph":{"n":1,"edges":[]},"method":"morph"}', encoding="utf-8")
    result = api_app.native_json_plan_file(str(path), input_sha256="a" * 64, byte_length=42)
    assert result[0] == 502
    assert result[2]["error"] == "native_solver_verification_failed"


def test_stdlib_native_endpoint_accepts_actual_socket_stream(monkeypatch, tmp_path):
    from http.server import ThreadingHTTPServer
    import threading
    import urllib.request
    payload = json.dumps({"graph": {"n": 4, "edges": [[0, 1], [1, 2]]},
                          "method": "morph", "budget_ms": 7, "seed": 9}).encode()
    sha = hashlib.sha256(payload).hexdigest()
    solver = _fake_solver(tmp_path)
    monkeypatch.setenv("PREDATOR_NATIVE_JSON_ENABLED", "1")
    monkeypatch.setenv("MORPH_DUMP_BIN", str(solver))
    monkeypatch.setenv("PREDATOR_NATIVE_MAX_REQUEST_BYTES", "100000")
    monkeypatch.delenv("PREDATOR_API_TOKEN", raising=False)
    server = ThreadingHTTPServer(("127.0.0.1", 0), PredatorHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{server.server_port}/v1/plan/native-file",
            data=payload, method="POST", headers={"Content-Type":"application/json", "X-Content-SHA256":sha})
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                result = json.loads(response.read())
                assert response.status == 200
        except urllib.error.URLError as exc:
            if isinstance(getattr(exc, "reason", None), ConnectionRefusedError):
                pytest.skip("sandbox blocks loopback socket connections")
            raise
        assert result["trace"]["streamed_bytes"] == len(payload)
        assert result["trace"]["input_sha256"] == sha
        assert result["verified"] is True
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize("payload,env,expect_ok", [
    (b'{"graph":{"edges":[[0,1]],"n":2},"method":"morph","budget_ms":5}', {}, True),
    (b'{"graph":{"n":2,"edges":[[0,2]]},"method":"morph"}', {}, False),
    (b'{"graph":{"n":2,"edges":[[0,1],[0,1]]},"method":"morph"}', {"PREDATOR_NATIVE_MAX_EDGES": "1"}, False),
    (b'{"graph":{"n":2,"edges":[[0,1],[0,1]]},"method":"morph"}', {}, False),
    (b'{"graph":{"n":2,"edges":[]},"method":"morph","ignored":"' + b"x" * (1024 * 1024) + b'"}', {}, True),
])
def test_real_morph_json_mode_stream_parser(monkeypatch, payload, env, expect_ok):
    """Exercise C++ parser with the built MORPH executable; fake solver isn't enough."""
    binary = os.getenv("MORPH_DUMP_BIN")
    if not binary or not Path(binary).is_file():
        pytest.skip("MORPH_DUMP_BIN is unavailable; native parser requires compiled CI target")
    child_env = os.environ.copy()
    child_env.update(env)
    child_env.setdefault("PREDATOR_NATIVE_MAX_VERTICES", "100")
    child_env.setdefault("PREDATOR_NATIVE_MAX_EDGES", "100")
    import tempfile
    with tempfile.NamedTemporaryFile() as source:
        source.write(payload)
        source.flush()
        completed = subprocess.run([binary, "--json", source.name], capture_output=True,
                                   env=child_env, timeout=20, check=False)
    assert (completed.returncode == 0) is expect_ok, completed.stderr.decode(errors="replace")
    if expect_ok:
        result = json.loads(completed.stdout)
        assert result["verified"] is True


def test_real_morph_json_api_passes_python_graph_limits_to_native(monkeypatch, tmp_path):
    binary = os.getenv("MORPH_DUMP_BIN")
    if not binary or not Path(binary).is_file():
        pytest.skip("MORPH_DUMP_BIN is unavailable; native integration requires compiled CI target")
    payload = b'{"graph":{"n":3,"edges":[[0,1],[1,2]]},"method":"morph","budget_ms":5,"seed":9}'
    path = tmp_path / "request.json"
    path.write_bytes(payload)
    monkeypatch.setenv("MORPH_DUMP_BIN", binary)
    monkeypatch.setenv("PREDATOR_NATIVE_MAX_VERTICES", "2")
    result = api_app.native_json_plan_file(str(path), input_sha256=hashlib.sha256(payload).hexdigest(),
                                           byte_length=len(payload))
    assert result[0] == 400
    assert result[2]["error"] == "native_solver_rejected_input"


def test_native_stream_route_with_real_morph_executable(monkeypatch, tmp_path):
    """End-to-end request staging -> JSON-mode MORPH -> API response (no fake solver)."""
    binary = os.getenv("MORPH_DUMP_BIN")
    if not binary or not Path(binary).is_file():
        pytest.skip("MORPH_DUMP_BIN is unavailable; real native route requires compiled CI target")
    payload = json.dumps({"graph": {"n": 5, "edges": [[0, 1], [1, 2], [3, 4]]},
                          "method": "morph", "budget_ms": 10, "seed": 13}).encode()
    monkeypatch.setenv("MORPH_DUMP_BIN", binary)
    monkeypatch.setenv("PREDATOR_NATIVE_MAX_REQUEST_BYTES", str(1024 * 1024))
    monkeypatch.setenv("PREDATOR_NATIVE_MAX_VERTICES", "100")
    monkeypatch.setenv("PREDATOR_NATIVE_MAX_EDGES", "100")
    request = _handler(payload, _request(payload, hashlib.sha256(payload).hexdigest()))
    PredatorHandler._stream_native_json_file(request)
    status, _, response = request._write.call_args.args
    assert status == 200, response
    assert response["verified"] is True
    assert response["trace"]["native_json"] is True
    assert response["trace"]["streamed_bytes"] == len(payload)
    assert response["trace"]["n"] == 5
    assert response["trace"]["m"] == 3
