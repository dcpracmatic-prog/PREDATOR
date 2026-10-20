from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest


@pytest.fixture
def dump_morph() -> Path:
    raw = os.environ.get("MORPH_DUMP_BIN")
    if not raw:
        pytest.skip("MORPH_DUMP_BIN is not set; build MORPH before native CLI tests")
    binary = Path(raw)
    if not binary.is_file():
        pytest.skip("MORPH binary has not been built")
    return binary


def _run(binary: Path, graph_text: str, tmp_path: Path, budget: str = "1", seed: str = "1"):
    graph_path = tmp_path / "case.gph"
    graph_path.write_text(graph_text, encoding="utf-8")
    return subprocess.run(
        [str(binary), str(graph_path), budget, seed],
        capture_output=True,
        text=True,
        timeout=3,
        check=False,
    )


@pytest.mark.parametrize(
    "graph_text,expected_error",
    [
        ("e 1 2\n", "before problem header"),
        ("p edge -1 0\n", "vertex count outside supported range"),
        ("p edge 2000001 0\n", "vertex count outside supported range"),
        ("p edge 2 10000001\n", "edge count outside supported range"),
        ("p edge two 1\n", "malformed problem header"),
        ("p edge 2 1\ne 1\n", "malformed edge record"),
        ("p edge 2 1\ne 1 3\n", "outside declared vertex range"),
        ("p edge 2 1\ne 1 1\n", "self-loops are not supported"),
        ("p edge 2 2\ne 1 2\ne 2 1\n", "duplicate edge record"),
        ("p edge 2 2\ne 1 2\n", "does not match problem header"),
        ("p edge 2 0\nx 1 2\n", "unknown graph record tag"),
        ("p edge 2 0\np edge 2 0\n", "duplicate problem header"),
        ("p edge 2 -1\n", "edge count outside supported range"),
    ],
)
def test_native_solver_rejects_hostile_graph_files(dump_morph, tmp_path, graph_text, expected_error):
    result = _run(dump_morph, graph_text, tmp_path)
    assert result.returncode != 0
    assert expected_error in result.stderr


@pytest.mark.parametrize(
    "budget,seed,expected_error",
    [
        ("0", "1", "budget_ms must be a positive 32-bit integer"),
        ("-1", "1", "budget_ms must be a positive 32-bit integer"),
        ("2147483648", "1", "budget_ms must be a positive 32-bit integer"),
        ("10x", "1", "budget_ms must be a positive 32-bit integer"),
        ("1", "-1", "seed must be an unsigned 64-bit integer"),
        ("1", "1x", "seed must be an unsigned 64-bit integer"),
        ("1", "18446744073709551616", "stoull"),
    ],
)
def test_native_solver_rejects_invalid_cli_numbers(dump_morph, tmp_path, budget, seed, expected_error):
    result = _run(dump_morph, "p edge 2 1\ne 1 2\n", tmp_path, budget, seed)
    assert result.returncode != 0
    assert expected_error in result.stderr


def test_native_solver_emits_well_formed_solution_for_valid_graph(dump_morph, tmp_path):
    result = _run(dump_morph, "c valid graph\np edge 3 1\ne 1 2\n", tmp_path)
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines and lines[0].startswith("# ")
    declared_size = int(lines[0][1:].strip())
    vertices = [int(line) for line in lines[1:]]
    assert len(vertices) == declared_size
    assert len(set(vertices)) == len(vertices)
    assert all(1 <= v <= 3 for v in vertices)
    assert not ({1, 2} <= set(vertices))
