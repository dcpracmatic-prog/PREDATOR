"""auto must not force MORPH on small graphs."""

from clan_subnet_detector.detection.independent_set import (
    DEFAULT_AUTO_N_THRESHOLD,
    is_independent,
    plan_independent,
)
from clan_subnet_detector.graph.graph import Graph


def _path(n: int) -> Graph:
    return Graph.from_edges(n, [(i, i + 1) for i in range(n - 1)], directed=False)


def test_auto_small_resolves_gwmin():
    g = _path(50)
    tr = []
    S = plan_independent(g, method="auto", budget_ms=50, seed=1, trace_out=tr)
    assert is_independent(g, S)
    assert tr[0]["resolved"] == "gwmin"
    assert g.n < DEFAULT_AUTO_N_THRESHOLD


def test_auto_never_worse_than_gwmin_small():
    g = _path(100)
    tr = []
    S = plan_independent(g, method="auto", trace_out=tr)
    from clan_subnet_detector.detection.independent_set import gwmin_independent

    G = gwmin_independent(g)
    assert len(S) >= len(G)
