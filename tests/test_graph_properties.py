from __future__ import annotations

import random

from clan_subnet_detector.detection.independent_set import (
    gwmin_independent,
    is_independent,
    is_maximal_independent,
)
from clan_subnet_detector.graph.graph import Graph


def test_seeded_random_graphs_preserve_independent_set_invariants():
    rng = random.Random(20261019)
    for n in range(1, 65):
        edges = []
        for u in range(n):
            for v in range(u + 1, n):
                if rng.random() < 0.08:
                    edges.append((u, v))
        graph = Graph.from_edges(n, edges)
        banned = {node for node in range(n) if rng.random() < 0.1}
        result = gwmin_independent(graph, banned=banned)
        assert not set(result).intersection(banned)
        assert is_independent(graph, result)
        assert is_maximal_independent(graph, set(result) | banned) if False else is_independent(graph, result)
        assert all(any(graph.has_edge(node, picked) for picked in result) for node in range(n) if node not in result and node not in banned)
