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
    """Write simple undirected edges in the 1-indexed format expected by MORPH."""
    edges = []
    seen = set()
    for u in range(g.n):
        for v in g.adj[u]:
            if u == v:
                continue
            a, b = (u, v) if u < v else (v, u)
            if (a, b) in seen:
                continue
            seen.add((a, b))
            edges.append((a, b))
    lines = [f"p edge {g.n} {len(edges)}"]
    lines.extend(f"e {u + 1} {v + 1}" for u, v in edges)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def find_morph_binary() -> Optional[Path]:
    """Locate an *executable* dump_morph binary.

    Prefer ``MORPH_DUMP_BIN``. Skip paths that are not executable (e.g. noexec
    mounts under some notebook artifact filesystems).
    """
    candidates: List[Path] = []
    for env_key in ("MORPH_DUMP_BIN", "MORPH_BIN"):
        raw = os.environ.get(env_key)
        if raw:
            candidates.append(Path(raw))
    candidates.extend(
        [
            Path("/tmp/dump_morph"),
            Path.cwd() / "dump_morph",
            Path.cwd() / "vendor" / "morph_src" / "dump_morph",
            Path.cwd().parent / "vendor" / "morph_src" / "dump_morph",
        ]
    )
    # PATH lookup
    for name in ("dump_morph", "morph_qoblib_solver"):
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))

    seen = set()
    for p in candidates:
        try:
            p = p.resolve()
        except Exception:
            continue
        if p in seen:
            continue
        seen.add(p)
        if not p.is_file():
            continue
        if not os.access(p, os.X_OK):
            # Common on noexec fuse mounts: copy to /tmp and retry
            dest = Path("/tmp/dump_morph")
            try:
                shutil.copy2(p, dest)
                dest.chmod(0o755)
                if dest.is_file() and os.access(dest, os.X_OK):
                    return dest
            except Exception:
                continue
            continue
        # Probe exec: noexec mounts sometimes still report X_OK
        try:
            import subprocess as _sp
            r = _sp.run([str(p)], capture_output=True, timeout=2)
            # usage exit codes 1/2 are fine — means the loader ran
            return p
        except PermissionError:
            dest = Path("/tmp/dump_morph")
            try:
                shutil.copy2(p, dest)
                dest.chmod(0o755)
                if os.access(dest, os.X_OK):
                    return dest
            except Exception:
                continue
        except Exception:
            # binary ran or failed for other reasons — still usable if X_OK
            return p
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
    if isinstance(budget_ms, bool) or not isinstance(budget_ms, int) or budget_ms <= 0:
        raise ValueError("budget_ms must be a positive integer")
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("seed must be a non-negative integer")
    if k is not None and (
        isinstance(k, bool) or not isinstance(k, int) or k < 0
    ):
        raise ValueError("k must be None or a non-negative integer")

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

    try:
        banned_set = set(banned or [])
    except TypeError as exc:
        raise TypeError("banned must be an iterable of integer node IDs") from exc
    for node in banned_set:
        if isinstance(node, bool) or not isinstance(node, int):
            raise TypeError("banned node IDs must be integers")
        if node < 0 or node >= g.n:
            raise IndexError(f"banned node ID out of range: {node}")
    # Self-loop vertices cannot be in an independent set; exclude them before
    # serialization so the native solver never sees a graph with dropped loops.
    looped = {node for node in range(g.n) if node in g.adj[node]}
    if looped:
        banned_set.update(looped)
        info.notes.append(f"excluded_self_loops={len(looped)}")
    if k == 0:
        info.ok = True
        if info_out is not None:
            info_out.append(info)
        return []
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
                    timeout=max(5.0, budget_ms / 1000.0 + 2.0),
                    check=False,
                )
            except subprocess.TimeoutExpired as e:
                raise RuntimeError(f"MORPH timed out after budget={budget_ms}ms") from e
            info.returncode = out.returncode
            if out.returncode != 0:
                raise RuntimeError(
                    f"MORPH failed (rc={out.returncode}): {out.stderr[:400]}"
                )
            output_lines = [line.strip() for line in (out.stdout or "").splitlines() if line.strip()]
            if not output_lines or not output_lines[0].startswith("#"):
                raise RuntimeError("MORPH output is missing the '# <size>' header")
            try:
                declared_size = int(output_lines[0][1:].strip())
            except ValueError as exc:
                raise RuntimeError("MORPH output has a malformed size header") from exc
            if declared_size < 0 or declared_size > work.n:
                raise RuntimeError(f"MORPH declared impossible solution size: {declared_size}")

            verts: List[int] = []
            seen_vertices = set()
            for line_number, value in enumerate(output_lines[1:], start=2):
                if value.startswith("c"):
                    continue
                if value.startswith("#"):
                    raise RuntimeError(f"MORPH output has an unexpected header at line {line_number}")
                try:
                    vertex_id = int(value)
                except ValueError as exc:
                    raise RuntimeError(f"MORPH output has malformed vertex at line {line_number}") from exc
                if vertex_id < 1 or vertex_id > work.n:
                    raise RuntimeError(f"MORPH output vertex is out of range: {vertex_id}")
                if vertex_id in seen_vertices:
                    raise RuntimeError(f"MORPH output contains duplicate vertex: {vertex_id}")
                seen_vertices.add(vertex_id)
                verts.append(vertex_id - 1)
            if len(verts) != declared_size:
                raise RuntimeError(
                    f"MORPH output size mismatch: header={declared_size}, vertices={len(verts)}"
                )
            if not verts:
                raise RuntimeError("MORPH returned an empty independent set for a non-empty graph")
    except Exception as e:
        info.error = str(e)
        info.wall_ms = (time.perf_counter() - t0) * 1000.0
        if info_out is not None:
            info_out.append(info)
        raise

    info.wall_ms = (time.perf_counter() - t0) * 1000.0
    if inv is not None:
        # Every returned index has already been range-checked above.
        verts = [inv[v] for v in verts]
    if k is not None and len(verts) > k:
        verts = verts[:k]
    info.size = len(verts)
    info.ok = True
    if info_out is not None:
        info_out.append(info)
    return verts
