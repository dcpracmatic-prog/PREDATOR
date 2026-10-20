from __future__ import annotations

import os
from pathlib import Path
from subprocess import CompletedProcess, TimeoutExpired
import time

import pytest

from clan_subnet_detector.detection import morph_adapter
from clan_subnet_detector.detection.independent_set import is_independent, plan_independent
from clan_subnet_detector.graph.graph import Graph


def _stub_binary(tmp_path: Path) -> Path:
    # The adapter receives this explicit path; subprocess.run is mocked below.
    return tmp_path / "dump_morph"


def _completed(cmd, stdout="", returncode=0, stderr=""):
    return CompletedProcess(cmd, returncode, stdout=stdout, stderr=stderr)


def test_morph_parses_valid_vertex_list_and_records_success(tmp_path, monkeypatch):
    graph = Graph.from_edges(3, [(0, 1)])
    monkeypatch.setattr(
        morph_adapter.subprocess,
        "run",
        lambda cmd, **kwargs: _completed(cmd, "# 2\n1\n3\n"),
    )
    info = []
    result = morph_adapter.morph_independent(graph, binary=_stub_binary(tmp_path), info_out=info)
    assert result == [0, 2]
    assert is_independent(graph, result)
    assert info[0].ok is True
    assert info[0].error == ""


@pytest.mark.parametrize(
    "stdout,expected_message",
    [
        ("", "missing the"),
        ("not-a-header\n1\n", "missing the"),
        ("# bad\n1\n", "malformed size header"),
        ("# 2\n1\n", "size mismatch"),
        ("# 1\n0\n", "out of range"),
        ("# 1\n4\n", "out of range"),
        ("# 2\n1\n1\n", "duplicate vertex"),
        ("# 1\nxyz\n", "malformed vertex"),
        ("# 0\n", "empty independent set"),
        ("# 2\n1\n2\n", "non-independent"),
    ],
)
def test_morph_rejects_corrupted_or_adversarial_native_output(
    tmp_path, monkeypatch, stdout, expected_message
):
    graph = Graph.from_edges(3, [(0, 1)])
    monkeypatch.setattr(
        morph_adapter.subprocess,
        "run",
        lambda cmd, **kwargs: _completed(cmd, stdout),
    )
    info = []
    with pytest.raises(RuntimeError, match=expected_message):
        morph_adapter.morph_independent(graph, binary=_stub_binary(tmp_path), info_out=info)
    assert info and info[0].ok is False
    assert expected_message in info[0].error


def test_morph_timeout_is_bounded_and_recorded(tmp_path, monkeypatch):
    observed = {}

    def timeout(cmd, **kwargs):
        observed.update(kwargs)
        raise TimeoutExpired(cmd=cmd, timeout=kwargs["timeout"])

    monkeypatch.setattr(morph_adapter.subprocess, "run", timeout)
    info = []
    with pytest.raises(RuntimeError, match="timed out"):
        morph_adapter.morph_independent(
            Graph.from_edges(2, [(0, 1)]),
            binary=_stub_binary(tmp_path),
            budget_ms=1000,
            info_out=info,
        )
    assert observed["timeout"] == 5.0
    assert info and info[0].ok is False
    assert "timed out" in info[0].error


def test_morph_rejects_nonzero_native_exit_with_bounded_stderr(tmp_path, monkeypatch):
    monkeypatch.setattr(
        morph_adapter.subprocess,
        "run",
        lambda cmd, **kwargs: _completed(cmd, returncode=7, stderr="native solver failed"),
    )
    info = []
    with pytest.raises(RuntimeError, match="rc=7"):
        morph_adapter.morph_independent(
            Graph.from_edges(2, [(0, 1)]),
            binary=_stub_binary(tmp_path),
            info_out=info,
        )
    assert info and "native solver failed" in info[0].error


def test_morph_excludes_self_loop_vertices_before_serialization(tmp_path, monkeypatch):
    graph = Graph.from_edges(3, [(0, 0), (1, 2)])
    captured = {}

    def run(cmd, **kwargs):
        captured["gph"] = Path(cmd[1]).read_text(encoding="utf-8")
        return _completed(cmd, "# 1\n1\n")

    monkeypatch.setattr(morph_adapter.subprocess, "run", run)
    info = []
    result = morph_adapter.morph_independent(graph, binary=_stub_binary(tmp_path), info_out=info)
    assert result == [1]
    assert "excluded_self_loops=1" in info[0].notes
    assert captured["gph"].splitlines()[0] == "p edge 2 1"


@pytest.mark.parametrize("timeout_s", [0, -1, float("nan"), float("inf"), True, "0.1"])
def test_morph_api_rejects_invalid_process_timeouts(tmp_path, timeout_s):
    with pytest.raises(ValueError, match="process_timeout_s"):
        morph_adapter.morph_independent(
            Graph.from_edges(2, [(0, 1)]),
            binary=_stub_binary(tmp_path),
            process_timeout_s=timeout_s,
        )


@pytest.mark.skipif(os.name != "posix", reason="real executable-timeout test requires POSIX shebang support")
def test_morph_real_stalling_process_is_terminated_by_outer_timeout(tmp_path):
    binary = _stub_binary(tmp_path)
    binary.write_text("#!/usr/bin/env python3\nimport time\ntime.sleep(3)\n", encoding="utf-8")
    binary.chmod(0o755)
    info = []
    started = time.perf_counter()
    with pytest.raises(RuntimeError, match="timed out"):
        morph_adapter.morph_independent(
            Graph.from_edges(2, [(0, 1)]),
            binary=binary,
            process_timeout_s=0.05,
            info_out=info,
        )
    elapsed = time.perf_counter() - started
    assert elapsed < 2.0, f"outer timeout failed to terminate child promptly: {elapsed:.2f}s"
    assert info and info[0].ok is False
    assert info[0].process_timeout_s == 0.05
    assert "timed out" in info[0].error


def test_morph_api_rejects_invalid_budgets_seeds_and_banned_nodes(tmp_path):
    graph = Graph.from_edges(2, [(0, 1)])
    binary = _stub_binary(tmp_path)
    with pytest.raises(ValueError, match="budget_ms"):
        morph_adapter.morph_independent(graph, binary=binary, budget_ms=0)
    with pytest.raises(ValueError, match="seed"):
        morph_adapter.morph_independent(graph, binary=binary, seed=-1)
    with pytest.raises(ValueError, match="k"):
        morph_adapter.morph_independent(graph, binary=binary, k=-1)
    with pytest.raises(IndexError, match="out of range"):
        morph_adapter.morph_independent(graph, binary=binary, banned=[9])


def test_plan_independent_falls_back_safely_when_native_output_is_corrupt(tmp_path, monkeypatch):
    graph = Graph.from_edges(4, [(0, 1), (1, 2), (2, 3)])
    binary = _stub_binary(tmp_path)
    monkeypatch.setattr(morph_adapter, "find_morph_binary", lambda: binary)
    monkeypatch.setattr(
        morph_adapter,
        "morph_status",
        lambda: {"available": True, "binary": str(binary), "emits_vertices": True},
    )
    monkeypatch.setattr(
        morph_adapter.subprocess,
        "run",
        lambda cmd, **kwargs: _completed(cmd, "# 2\n1\n2\n"),
    )
    trace = []
    result = plan_independent(graph, method="morph", trace_out=trace)
    assert is_independent(graph, result)
    assert trace[0]["resolved"] == "gwmin"
    assert trace[0]["fallback"] is True
    assert "non-independent" in trace[0]["reason"]
