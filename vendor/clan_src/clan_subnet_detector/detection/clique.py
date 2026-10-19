"""Clique detection primitives.

A clique is a complete subgraph – every pair of nodes is connected.
In traffic / social analysis this often signals a tightly coordinated group.
"""

from __future__ import annotations

from typing import Iterable, List, Set

from ..graph.graph import Graph


def is_clique(g: Graph, nodes: Iterable[int]) -> bool:
    """Return True if the induced subgraph on `nodes` is complete."""
    node_list = list(nodes)
    for i, u in enumerate(node_list):
        for v in node_list[i + 1 :]:
            if not g.has_edge(u, v):
                # for undirected graphs has_edge is symmetric;
                # for directed we currently require both directions
                # or at least one – policy can be refined later.
                if g.directed:
                    if not (g.has_edge(u, v) or g.has_edge(v, u)):
                        return False
                else:
                    return False
    return True


def greedy_clique(g: Graph, seed: int | None = None) -> List[int]:
    """Simple greedy clique construction starting from highest-degree node
    (or a given seed).  Not maximal in the strong sense; useful as a fast
    baseline and for scoring pipelines.
    """
    if g.n == 0:
        return []
    if seed is None:
        seed = max(range(g.n), key=lambda u: g.degree(u))
    clique: List[int] = [seed]
    candidates: Set[int] = set(g.adj[seed].keys())
    while candidates:
        # pick the candidate with the highest degree inside the remaining set
        best = max(candidates, key=lambda u: sum(1 for v in candidates if g.has_edge(u, v)))
        # verify it is connected to all current clique members
        if all(g.has_edge(best, c) or (g.directed and g.has_edge(c, best)) for c in clique):
            clique.append(best)
            candidates &= set(g.adj[best].keys())
        else:
            candidates.discard(best)
    return clique
