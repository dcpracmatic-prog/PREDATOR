"""Transparent adapter to the compiled MORPH binary (dump_morph).

Contract
--------
* Input:  Graph (0-indexed nodes), optional banned set, budget_ms, seed.
* Output: list of 0-indexed vertices forming an independent set, or raises.
* Side effects: writes a temporary DIMACS-like .gph, invokes the binary,
  never mutates the caller's Graph.

Discovery order for the binary
------------------------------
1. Explicit ``binary=`` argument
2. ``MORPH_DUMP_BIN`` environment variable
3. ``MORPH_BIN`` environment variable
4. ``dump_morph`` / ``morph_qoblib_solver`` on PATH
5. Common relative paths (artifacts/, sibling MORPH/, cwd)

Only binaries that emit vertex lists are accepted. Size-only solvers
raise so the caller can fall back to GWMIN without silent quality loss.

Transparency
------------
Every call can append a :class:`MorphRunInfo` via ``info_out`` so the audit
report records which binary, budget, seed and wall time were used.
Fallback is the responsibility of ``plan_independent``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from ..graph.graph import Graph


@dataclass
class MorphRunInfo:
    """Machine-readable record of one MORPH invocation (for audit trails)."""

    method: str = "morph"
    binary: str = ""
    binary_resolved: str = ""
    budget_ms: int = 0
    seed: int = 1
    n_input: int = 0
    m_input: int = 0
    n_after_ban: int = 0
    size: int = 0
    wall_ms: float = 0.0
    returncode: int = 0
    ok: bool = False
    error: str = ""
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def graph_to_gph(g: Graph, path: Path) -> None:
    """Write graph in DIMACS-like .gph format expected by MORPH (1-indexed edges)."""
    lines = [f"p edge {g.n} {g.edge_count()}"]
    seen = set()
    for u in range(g.n):
        for v in g.adj[u]:
            if u == v:
                continue
            a, b = (u, v) if u < v else (v, u)
            if (a, b) in seen:
                continue
            seen.add((a, b))
            lines.append(f"e {a + 1} {b + 1}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def find_morph_binary() -> Optional[Path]:
    """Locate a vertex-dump capable MORPH binary."""
    for env_key in ("MORPH_DUMP_BIN", "MORPH_BIN"):
        env = os.environ.get(env_key)
        if env:
            p = Path(env).expanduser()
            if p.is_file() and os.access(p, os.X_OK):
                return p.resolve()
    for name in ("dump_morph", "morph_qoblib_solver"):
        found = shutil.which(name)
        if found:
            return Path(found).resolve()
    candidates = [
        Path("/home/workdir/artifacts/MORPH/dump_morph"),
        Path("/home/workdir/artifacts/MORPH/morph_qoblib_solver"),
        Path("/home/workdir/artifacts/zero-trust-graph-engine/vendor/morph_src/dump_morph"),
        Path.cwd() / "dump_morph",
        Path.cwd() / "morph_qoblib_solver",
        Path.cwd().parent / "MORPH" / "dump_morph",
        Path.cwd().parent / "MORPH" / "morph_qoblib_solver",
    ]
    for p in candidates:
        if p.is_file() and os.access(p, os.X_OK):
            return p.resolve()
    return None


def morph_status() -> Dict[str, Any]:
    """Status dict for CLI health checks and ZTGE bootstrap."""
    p = find_morph_binary()
    if p is None:
        return {
            "available": False,
            "binary": None,
            "reason": (
                "No dump_morph binary found. Set MORPH_DUMP_BIN or place "
                "dump_morph on PATH. Planner will fall back to GWMIN."
            ),
        }
    emits_vertices = "dump" in p.name.lower()
    return {
        "available": True,
        "binary": str(p),
        "emits_vertices": emits_vertices,
        "warning": None
        if emits_vertices
        else (
            f"{p.name} may be size-only; independent-set vertices require "
            "dump_morph. plan_independent will fall back if invocation fails."
        ),
    }


def morph_independent(
    g: Graph,
    banned: Optional[Iterable[int]] = None,
    k: Optional[int] = None,
    budget_ms: int = 100,
    seed: int = 1,
    binary: Optional[Path] = None,
    info_out: Optional[List[MorphRunInfo]] = None,
) -> List[int]:
    """Call MORPH and return an independent set (0-indexed vertices)."""
    info = MorphRunInfo(
        budget_ms=budget_ms,
        seed=seed,
        n_input=g.n,
        m_input=g.edge_count(),
    )
    bin_path = binary or find_morph_binary()
    if bin_path is None:
        info.error = "MORPH binary not found"
        if info_out is not None:
            info_out.append(info)
        raise FileNotFoundError(
            "MORPH binary not found. Set MORPH_DUMP_BIN or place dump_morph on PATH."
        )
    info.binary = bin_path.name
    info.binary_resolved = str(bin_path)

    banned_set = set(banned or [])
    if banned_set:
        keep = [i for i in range(g.n) if i not in banned_set]
        inv = {new: old for new, old in enumerate(keep)}
        work = g.induced_subgraph(keep)
        info.notes.append(f"banned={len(banned_set)} induced n={work.n}")
    else:
        inv = None
        work = g
    info.n_after_ban = work.n

    if work.n == 0:
        info.ok = True
        info.size = 0
        if info_out is not None:
            info_out.append(info)
        return []

    t0 = time.perf_counter()
    try:
        with tempfile.TemporaryDirectory(prefix="morph_") as td:
            gph = Path(td) / "g.gph"
            graph_to_gph(work, gph)
            is_dump = "dump" in bin_path.name.lower()
            if not is_dump:
                raise RuntimeError(
                    f"{bin_path.name} does not emit vertices; use dump_morph instead"
                )
            cmd = [str(bin_path), str(gph), str(int(budget_ms)), str(int(seed))]
            try:
                out = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=max(5.0, budget_ms / 1000.0 + 30.0),
                    check=False,
                )
            except subprocess.TimeoutExpired as e:
                raise RuntimeError(f"MORPH timed out after budget={budget_ms}ms") from e
            info.returncode = out.returncode
            if out.returncode != 0:
                raise RuntimeError(
                    f"MORPH failed (rc={out.returncode}): {out.stderr[:400]}"
                )
            verts: List[int] = []
            for line in out.stdout.splitlines():
                s = line.strip()
                if not s or s.startswith("#") or s.startswith("c"):
                    continue
                try:
                    verts.append(int(s) - 1)
                except ValueError:
                    continue
    except Exception as e:
        info.error = str(e)
        info.wall_ms = (time.perf_counter() - t0) * 1000.0
        if info_out is not None:
            info_out.append(info)
        raise

    info.wall_ms = (time.perf_counter() - t0) * 1000.0
    if inv is not None:
        verts = [inv[v] for v in verts if v in inv]
    if k is not None and len(verts) > k:
        verts = verts[:k]
    info.size = len(verts)
    info.ok = True
    if info_out is not None:
        info_out.append(info)
    return verts
