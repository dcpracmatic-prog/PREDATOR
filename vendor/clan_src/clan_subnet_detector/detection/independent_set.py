"""Independent-set planners.

Primary use-case: groups of nodes that do not communicate (isolated logical
subnetworks). Supports GWMIN (pure Python) and MORPH (compiled binary).

Transparency contract
---------------------
``plan_independent`` always returns vertices and, when ``trace_out`` is
supplied, appends a dict describing which method actually ran (requested
method, resolved method, binary path, budget, wall time, fallback reason).
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

from ..graph.graph import Graph


def gwmin_independent(
    g: Graph,
    banned: Optional[Iterable[int]] = None,
    k: Optional[int] = None,
    weights: Optional[Sequence[float]] = None,
) -> List[int]:
    """GWMIN greedy independent set (weight / (degree + 1))."""
    n = g.n
    banned_set: Set[int] = set(banned or [])
    alive = [i not in banned_set for i in range(n)]
    w = list(weights) if weights is not None else [1.0] * n
    if len(w) != n:
        raise ValueError("weights length must equal number of nodes")

    deg = [0] * n
    for u in range(n):
        if not alive[u]:
            continue
        for v in g.adj[u]:
            if alive[v]:
                deg[u] += 1

    picked: List[int] = []
    while True:
        if k is not None and len(picked) >= k:
            break
        best = -1
        best_score = -1.0
        for v in range(n):
            if not alive[v]:
                continue
            score = w[v] / (deg[v] + 1)
            if score > best_score:
                best_score = score
                best = v
        if best < 0:
            break
        picked.append(best)
        alive[best] = False
        for u in list(g.adj[best].keys()):
            if alive[u]:
                alive[u] = False
                for x in g.adj[u]:
                    if alive[x]:
                        deg[x] -= 1
        if g.directed:
            for u in range(n):
                if alive[u] and best in g.adj[u]:
                    alive[u] = False
                    for x in g.adj[u]:
                        if alive[x]:
                            deg[x] -= 1
    return picked


def is_independent(g: Graph, nodes: Iterable[int]) -> bool:
    """Pure verifier: True iff no edge connects any pair in ``nodes``."""
    node_set = set(nodes)
    for u in node_set:
        for v in g.adj[u]:
            if v in node_set and u != v:
                return False
    return True


def plan_independent(
    g: Graph,
    banned: Optional[Iterable[int]] = None,
    k: Optional[int] = None,
    weights: Optional[Sequence[float]] = None,
    method: str = "auto",
    budget_ms: int = 100,
    seed: int = 1,
    trace_out: Optional[List[Dict[str, Any]]] = None,
) -> List[int]:
    """Public planner with transparent method resolution.

    Methods
    -------
    gwmin : pure-Python GWMIN (always available).
    morph : compiled MORPH binary; falls back to GWMIN on failure.
    auto  : prefer MORPH when discoverable, else GWMIN (recommended default).
    """
    requested = (method or "auto").lower().strip()
    if requested not in ("gwmin", "morph", "auto"):
        raise ValueError(f"Unknown independent-set method: {method!r}")

    trace: Dict[str, Any] = {
        "requested": requested,
        "resolved": None,
        "fallback": False,
        "reason": "",
        "morph": None,
        "size": 0,
    }

    def _gwmin(reason: str = "") -> List[int]:
        verts = gwmin_independent(g, banned=banned, k=k, weights=weights)
        trace["resolved"] = "gwmin"
        if reason:
            trace["fallback"] = requested in ("morph", "auto")
            trace["reason"] = reason
        else:
            trace["reason"] = "explicit gwmin"
        trace["size"] = len(verts)
        if trace_out is not None:
            trace_out.append(trace)
        return verts

    if requested == "gwmin":
        return _gwmin()

    from .morph_adapter import morph_independent, morph_status

    status = morph_status()
    if not status.get("available"):
        return _gwmin(reason=status.get("reason") or "MORPH unavailable")

    morph_info: List = []
    try:
        verts = morph_independent(
            g,
            banned=banned,
            k=k,
            budget_ms=budget_ms,
            seed=seed,
            info_out=morph_info,
        )
        trace["resolved"] = "morph"
        trace["reason"] = "MORPH binary used"
        trace["morph"] = morph_info[0].to_dict() if morph_info else status
        trace["size"] = len(verts)
        if trace_out is not None:
            trace_out.append(trace)
        return verts
    except Exception as e:
        return _gwmin(reason=f"MORPH failed: {e}")
