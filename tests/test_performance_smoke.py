from __future__ import annotations

import time

from clan_subnet_detector.detection.independent_set import gwmin_independent, is_independent
from clan_subnet_detector.graph.graph import Graph


def test_gwmin_performance_smoke_on_large_edgeless_graph():
    # An edgeless graph is a useful worst-case selection path: each pass scans
    # the remaining vertices. This deliberately broad ceiling catches hangs or
    # accidental super-quadratic regressions without timing micro-optimizations.
    graph = Graph(n=1500)
    started = time.perf_counter()
    result = gwmin_independent(graph)
    elapsed = time.perf_counter() - started
    assert len(result) == graph.n
    assert is_independent(graph, result)
    assert elapsed < 8.0, f"GWMIN took {elapsed:.3f}s for {graph.n} edgeless vertices"
