from __future__ import annotations

import math

import pytest

from clan_subnet_detector.graph.graph import Graph
from clan_subnet_detector.graph.temporal import EdgeEvent, TemporalGraph
from clan_subnet_detector.detection.independent_set import plan_independent
from clan_subnet_detector.ingest.edge_list import (
    load_edge_list,
    load_netflow_summary,
    load_timestamped_edge_list,
)


@pytest.mark.parametrize("n,error", [(-1, ValueError), (1.5, TypeError), (True, TypeError)])
def test_graph_rejects_invalid_node_counts(n, error):
    with pytest.raises(error):
        Graph(n=n)


@pytest.mark.parametrize("weight", [float("nan"), float("inf"), -float("inf"), "1.2", True])
def test_graph_rejects_non_finite_or_non_numeric_edge_weights(weight):
    graph = Graph(n=2)
    with pytest.raises((TypeError, ValueError)):
        graph.add_edge(0, 1, weight)


def test_graph_rejects_bad_endpoints_and_malformed_edge_tuples():
    graph = Graph(n=2)
    with pytest.raises(TypeError):
        graph.add_edge(0.5, 1)
    with pytest.raises(IndexError):
        graph.add_edge(0, 2)
    with pytest.raises(ValueError, match="exactly 2 or 3 fields"):
        Graph.from_edges(2, [(0, 1, 1.0, "extra")])
    with pytest.raises(ValueError, match="symmetric"):
        Graph(n=2, adj=[{1: 1.0}, {}])


def test_graph_rejects_integer_weights_that_overflow_float_representation():
    graph = Graph(n=2)
    with pytest.raises(ValueError, match="representable"):
        graph.add_edge(0, 1, 10**10000)


def test_weight_overflow_does_not_partially_mutate_undirected_graph():
    graph = Graph(n=2)
    graph.add_edge(0, 1, 1e308)
    with pytest.raises(ValueError, match="finite"):
        graph.add_edge(0, 1, 1e308)
    assert graph.adj[0][1] == 1e308
    assert graph.adj[1][0] == 1e308


def test_induced_subgraph_rejects_out_of_range_node_ids():
    with pytest.raises(IndexError, match="out of range"):
        Graph(n=2).induced_subgraph([-1])


@pytest.mark.parametrize(
    "raw,weighted",
    [
        ("1\n", False),
        ("a 2\n", False),
        ("1 2 3\n", False),
        ("1 2\n", True),
        ("1 2 nan\n", True),
        ("1 2 inf\n", True),
        ("1 2 nope\n", True),
    ],
)
def test_static_loader_rejects_malformed_records_with_line_number(tmp_path, raw, weighted):
    path = tmp_path / "edges.txt"
    path.write_text(raw, encoding="utf-8")
    with pytest.raises(ValueError, match="line 1"):
        load_edge_list(path, weighted=weighted)


def test_static_loader_accepts_inline_comments_and_isolated_blank_lines(tmp_path):
    path = tmp_path / "edges.txt"
    path.write_text("# graph\n\n10 20 # edge\n20 30\n", encoding="utf-8")
    graph = load_edge_list(path)
    assert graph.n == 3
    assert graph.edge_count() == 2


@pytest.mark.parametrize(
    "raw,kwargs",
    [
        ("1 2\n", {}),
        ("1 2 NaN\n", {}),
        ("1 2 3 inf\n", {"weight_index": 3}),
        ("1 2 3\n", {"weight_index": 3}),
    ],
)
def test_timestamped_loader_rejects_missing_or_non_finite_values(tmp_path, raw, kwargs):
    path = tmp_path / "temporal.txt"
    path.write_text(raw, encoding="utf-8")
    with pytest.raises(ValueError, match="line 1"):
        load_timestamped_edge_list(path, **kwargs)


def test_timestamped_loader_rejects_conflicting_field_indices(tmp_path):
    path = tmp_path / "temporal.txt"
    path.write_text("1 2 3 4\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must differ"):
        load_timestamped_edge_list(path, ts_index=2, weight_index=2)


def test_netflow_loader_rejects_corrupt_records_instead_of_silently_dropping_them(tmp_path):
    path = tmp_path / "netflow.csv"
    path.write_text("src,dst,bytes,packets,start_ts\n1,2,nan,4,10\n", encoding="utf-8")
    with pytest.raises(ValueError, match="line 2"):
        load_netflow_summary(path)


def test_netflow_loader_accepts_header_and_valid_csv(tmp_path):
    path = tmp_path / "netflow.csv"
    path.write_text("src,dst,bytes,packets,start_ts\n1,2,100,4,10\n", encoding="utf-8")
    graph = load_netflow_summary(path)
    assert len(graph.events) == 1
    assert graph.events[0].weight == 100.0
    assert graph.events[0].ts == 10.0


def test_temporal_graph_validates_events_supplied_to_constructor():
    with pytest.raises(ValueError, match="finite"):
        TemporalGraph(n=2, events=[EdgeEvent(0, 1, math.inf)])
    with pytest.raises(ValueError, match="representable"):
        TemporalGraph(n=2, events=[EdgeEvent(0, 1, 10**10000)])


def test_temporal_graph_rejects_non_finite_data_and_reversed_windows():
    graph = TemporalGraph(n=2)
    with pytest.raises(ValueError, match="finite"):
        graph.add_event(0, 1, math.nan)
    with pytest.raises(ValueError, match="finite"):
        graph.add_event(0, 1, 1.0, math.inf)
    graph.add_event(0, 1, 1.0)
    with pytest.raises(ValueError, match="t0 must be <= t1"):
        graph.window(2.0, 1.0)
    with pytest.raises(ValueError, match="finite"):
        graph.sliding_windows(float("nan"), 1.0)

@pytest.mark.parametrize("weights", [[1.0], [float("nan"), 1.0], [-1.0, 1.0], [True, 1.0]])
def test_planner_rejects_malformed_vertex_weights(weights):
    graph = Graph.from_edges(2, [(0, 1)])
    with pytest.raises((TypeError, ValueError)):
        plan_independent(graph, method="gwmin", weights=weights)


def test_planner_consumes_banned_generators_once_and_respects_them():
    graph = Graph.from_edges(4, [(0, 1), (1, 2), (2, 3)])
    banned = (node for node in [0, 2])
    result = plan_independent(graph, method="gwmin", banned=banned)
    assert not set(result).intersection({0, 2})
    assert all(not graph.has_edge(u, v) for i, u in enumerate(result) for v in result[i + 1:])
