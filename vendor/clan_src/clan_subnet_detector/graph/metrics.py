"""Basic graph metrics used by detection and scoring layers."""

from __future__ import annotations

from collections import deque
from typing import List, Set, Tuple

from .graph import Graph


def density(g: Graph) -> float:
    """Edge density of the graph (or induced subgraph)."""
    m = g.edge_count()
    n = g.n
    if n < 2:
        return 0.0
    max_edges = n * (n - 1) if g.directed else n * (n - 1) // 2
    return m / max_edges if max_edges else 0.0


def degree_sequence(g: Graph) -> List[int]:
    return [g.degree(u) for u in range(g.n)]


def connected_components(g: Graph) -> List[Set[int]]:
    """Return list of connected components (treats directed graph as undirected)."""
    visited = [False] * g.n
    components: List[Set[int]] = []

    for start in range(g.n):
        if visited[start]:
            continue
        comp: Set[int] = set()
        queue = deque([start])
        visited[start] = True
        while queue:
            u = queue.popleft()
            comp.add(u)
            # undirected view
            for v in g.adj[u]:
                if not visited[v]:
                    visited[v] = True
                    queue.append(v)
            if not g.directed:
                continue
            # also consider reverse edges for weak connectivity
            for v in range(g.n):
                if u in g.adj[v] and not visited[v]:
                    visited[v] = True
                    queue.append(v)
        components.append(comp)
    return components
