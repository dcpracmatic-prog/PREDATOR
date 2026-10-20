"""Independent-set planners.

Primary use-case: groups of nodes that do not communicate (isolated logical
subnetworks). Supports GWMIN (pure Python) and MORPH (compiled binary).

Transparency contract
---------------------
``plan_independent`` always returns vertices and, when ``trace_out`` is
supplied, appends a dict describing which method actually ran (requested
method, resolved method, binary path, budget, wall time, fallback reason).

``auto`` policy
---------------
Prefer GWMIN on small graphs (default n < 1500) where wall time dominates any
modest quality gain from MORPH. Prefer MORPH on larger graphs when the binary
is available. Threshold is overridable via ``auto_n_threshold``.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

from ..graph.graph import Graph

# Empirical crossover from BA/ER degree≈6 benches: GWMIN cheaper below ~1.5–1.7k.
DEFAULT_AUTO_N_THRESHOLD = 1500


def gwmin_independent(
    g: Graph,
    banned: Optional[Iterable[int]] = None,
    k: Optional[int] = None,
    weights: Optional[Sequence[float]] = None,
) -> List[int]:
    """GWMIN greedy independent set (weight / (degree + 1))."""
    n = g.n
    banned_set: Set[int] = set(banned or [])
    # A vertex with a self-loop cannot belong to an independent set.
    alive = [i not in banned_set and i not in g.adj[i] for i in range(n)]
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
    if any(not isinstance(u, int) or u < 0 or u >= g.n for u in node_set):
        return False
    for u in node_set:
        for v in g.adj[u]:
            if v in node_set:
                return False
    return True


def is_maximal_independent(g: Graph, nodes: Iterable[int]) -> bool:
    """True iff ``nodes`` is independent and every outsider is adjacent to it."""
    node_set = set(nodes)
    if not is_independent(g, node_set):
        return False
    for u in range(g.n):
        if u in node_set:
            continue
        # u must have a neighbor in the set (or the set is empty and n>0 → not maximal)
        if not any(v in node_set for v in g.adj[u]):
            return False
    if g.n > 0 and not node_set:
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
    auto_n_threshold: int = DEFAULT_AUTO_N_THRESHOLD,
) -> List[int]:
    """Public planner with transparent method resolution.

    Methods
    -------
    gwmin : pure-Python GWMIN (always available).
    morph : compiled MORPH binary; falls back to GWMIN on failure.
    auto  : size-aware selection — GWMIN when n < auto_n_threshold (default 1500),
            else MORPH if available, else GWMIN. Never forces MORPH on tiny graphs.
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
        "auto_n_threshold": auto_n_threshold,
        "graph_n": g.n,
    }

    def _finish(verts: List[int]) -> List[int]:
        trace["size"] = len(verts)
        if trace_out is not None:
            trace_out.append(dict(trace))
        return verts

    def _gwmin(reason: str, *, fallback: bool = False) -> List[int]:
        verts = gwmin_independent(g, banned=banned, k=k, weights=weights)
        trace["resolved"] = "gwmin"
        trace["fallback"] = fallback
        trace["reason"] = reason
        return _finish(verts)

    if requested == "gwmin":
        return _gwmin("explicit gwmin")

    from .morph_adapter import morph_independent, morph_status

    status = morph_status()

    # --- auto: prefer cheap GWMIN below crossover ---
    if requested == "auto":
        if g.n < auto_n_threshold:
            return _gwmin(
                f"auto: n={g.n} < threshold={auto_n_threshold} → gwmin",
                fallback=False,
            )
        if not status.get("available"):
            return _gwmin(
                status.get("reason") or "auto: MORPH unavailable → gwmin",
                fallback=True,
            )
        # fall through to MORPH for large n
        pass
    elif requested == "morph" and not status.get("available"):
        return _gwmin(status.get("reason") or "MORPH unavailable", fallback=True)

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
        if len(set(verts)) != len(verts) or not is_independent(g, verts):
            raise ValueError("MORPH returned an invalid independent-set candidate")
        if banned is not None and set(verts).intersection(set(banned)):
            raise ValueError("MORPH returned a banned vertex")
        # Safety: if MORPH is smaller than a free GWMIN would be, prefer GWMIN
        # only when sizes differ and we are in auto (quality floor).
        if requested == "auto":
            gw = gwmin_independent(g, banned=banned, k=k, weights=weights)
            if len(gw) > len(verts):
                trace["resolved"] = "gwmin"
                trace["fallback"] = True
                trace["reason"] = (
                    f"auto: MORPH size {len(verts)} < GWMIN {len(gw)}; prefer GWMIN"
                )
                trace["morph"] = morph_info[0].to_dict() if morph_info else status
                return _finish(gw)
        trace["resolved"] = "morph"
        trace["reason"] = (
            "MORPH binary used"
            if requested == "morph"
            else f"auto: n={g.n} >= threshold={auto_n_threshold} → morph"
        )
        trace["fallback"] = False
        trace["morph"] = morph_info[0].to_dict() if morph_info else status
        return _finish(verts)
    except Exception as e:
        return _gwmin(f"MORPH failed: {e}", fallback=True)
