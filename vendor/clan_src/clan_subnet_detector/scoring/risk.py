"""Simple risk scoring for detected structures.

Scores are deliberately transparent and configurable so that later
policy layers (signed bindings, containment) can reason about them.
"""

from __future__ import annotations

from typing import Iterable

from ..graph.graph import Graph
from ..graph.metrics import density


def score_clique(g: Graph, nodes: Iterable[int], base_weight: float = 1.0) -> float:
    """Heuristic risk score for a clique.

    Factors (primitive version):
    - size of the clique
    - density of the induced subgraph (should be 1.0 for a true clique)
    - average degree of the members in the original graph
    """
    node_list = list(nodes)
    k = len(node_list)
    if k < 2:
        return 0.0
    sub = g.induced_subgraph(node_list)
    dens = density(sub)
    avg_deg = sum(g.degree(u) for u in node_list) / k
    return base_weight * (k ** 1.5) * dens * (1.0 + 0.1 * avg_deg)


def score_independent_set(
    g: Graph,
    nodes: Iterable[int],
    base_weight: float = 1.0,
) -> float:
    """Heuristic score for an independent set (isolated logical group).

    Larger independent sets that also have low external connectivity
    receive higher isolation scores.
    """
    node_list = list(nodes)
    k = len(node_list)
    if k == 0:
        return 0.0
    # external cut size (edges leaving the set)
    node_set = set(node_list)
    cut = 0
    for u in node_list:
        for v in g.adj[u]:
            if v not in node_set:
                cut += 1
    # lower cut relative to size → higher isolation
    isolation = 1.0 / (1.0 + cut / max(k, 1))
    return base_weight * k * isolation
