"""Dense-subgraph detectors: k-core decomposition and Charikar densest-subgraph peeling.

Complement the greedy clique baseline with structures that capture dense regions
even when they are not complete cliques.
"""

from __future__ import annotations

from typing import Dict, List, Set, Tuple

from ..graph.graph import Graph
from ..graph.metrics import density


def k_core(g: Graph, k: int) -> List[int]:
    """Return nodes belonging to the k-core (undirected view).

    Iteratively delete nodes with degree < k until stability.
    """
    if k <= 0:
        return list(range(g.n))
    # residual degree
    deg = [g.degree(u) for u in range(g.n)]
    alive = [True] * g.n
    changed = True
    while changed:
        changed = False
        for u in range(g.n):
            if alive[u] and deg[u] < k:
                alive[u] = False
                changed = True
                for v in g.adj[u]:
                    if alive[v]:
                        deg[v] -= 1
    return [u for u in range(g.n) if alive[u]]


def core_number(g: Graph) -> List[int]:
    """Core number of each vertex (highest k such that v is in the k-core)."""
    n = g.n
    deg = [g.degree(u) for u in range(n)]
    # bin sort
    bins: Dict[int, List[int]] = {}
    for u, d in enumerate(deg):
        bins.setdefault(d, []).append(u)
    core = [0] * n
    alive = [True] * n
    for d in range(n):
        while bins.get(d):
            u = bins[d].pop()
            if not alive[u]:
                continue
            core[u] = d
            alive[u] = False
            for v in g.adj[u]:
                if alive[v] and deg[v] > d:
                    # move v to lower bin
                    old = deg[v]
                    deg[v] -= 1
                    bins.setdefault(deg[v], []).append(v)
    return core


def densest_subgraph_peeling(g: Graph) -> Tuple[List[int], float]:
    """Charikar-style greedy peeling for densest subgraph approximation.

    Repeatedly remove the minimum-degree vertex; track the densest induced
    subgraph seen. Returns (nodes, density).
    """
    n = g.n
    if n == 0:
        return [], 0.0
    deg = [g.degree(u) for u in range(n)]
    alive = [True] * n
    remaining = n
    edges_left = g.edge_count()
    best_nodes: List[int] = list(range(n))
    best_dens = density(g)
    # order of removal
    order: List[int] = []
    while remaining > 0:
        # pick min-degree alive node
        best_u = -1
        best_d = n + 1
        for u in range(n):
            if alive[u] and deg[u] < best_d:
                best_d = deg[u]
                best_u = u
        if best_u < 0:
            break
        alive[best_u] = False
        order.append(best_u)
        remaining -= 1
        for v in g.adj[best_u]:
            if alive[v]:
                deg[v] -= 1
                edges_left -= 1
        if remaining >= 2 and edges_left > 0:
            dens = (2.0 * edges_left) / (remaining * (remaining - 1)) if not g.directed else edges_left / (remaining * (remaining - 1))
            # dens for undirected as m / (n choose 2)
            dens_und = edges_left / (remaining * (remaining - 1) / 2.0)
            if dens_und > best_dens:
                best_dens = dens_und
                best_nodes = [u for u in range(n) if alive[u]]
    return best_nodes, best_dens
