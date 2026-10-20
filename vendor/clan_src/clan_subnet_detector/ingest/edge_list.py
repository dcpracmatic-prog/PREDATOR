"""Strict parsers for static, timestamped, and NetFlow-style edge lists."""

from __future__ import annotations

import math
from pathlib import Path
from typing import List, Optional, Tuple

from ..graph.graph import Graph
from ..graph.temporal import TemporalGraph


def _parse_node_pair(parts: list[str], line_number: int) -> tuple[int, int]:
    if len(parts) < 2:
        raise ValueError(f"line {line_number}: expected at least two node IDs")
    try:
        return int(parts[0]), int(parts[1])
    except ValueError as exc:
        raise ValueError(f"line {line_number}: node IDs must be integers") from exc


def load_edge_list(
    path: str | Path,
    directed: bool = False,
    weighted: bool = False,
) -> Graph:
    """Load strict whitespace-delimited edges: u v or u v weight.

    Blank lines, full-line comments, and inline comments starting with # are
    ignored. Node IDs are remapped to a contiguous zero-based range.
    """
    path = Path(path)
    raw_edges: List[Tuple[int, int, float]] = []
    nodes = set()
    for line_number, raw_line in enumerate(path.open(encoding="utf-8"), start=1):
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        expected = 3 if weighted else 2
        if len(parts) != expected:
            raise ValueError(
                f"line {line_number}: expected exactly {expected} fields "
                f"for {'weighted' if weighted else 'unweighted'} input, got {len(parts)}"
            )
        u, v = _parse_node_pair(parts, line_number)
        try:
            weight = float(parts[2]) if weighted else 1.0
        except ValueError as exc:
            raise ValueError(f"line {line_number}: edge weight must be numeric") from exc
        if not math.isfinite(weight):
            raise ValueError(f"line {line_number}: edge weight must be finite")
        raw_edges.append((u, v, weight))
        nodes.update((u, v))

    if not nodes:
        return Graph(n=0, directed=directed)

    sorted_nodes = sorted(nodes)
    mapping = {old: new for new, old in enumerate(sorted_nodes)}
    graph = Graph(n=len(sorted_nodes), directed=directed)
    for u, v, weight in raw_edges:
        graph.add_edge(mapping[u], mapping[v], weight)
    return graph


def load_timestamped_edge_list(
    path: str | Path,
    directed: bool = False,
    ts_index: int = 2,
    weight_index: Optional[int] = None,
) -> TemporalGraph:
    """Load u v timestamp [weight] rows, remapping node IDs to 0..n-1."""
    if isinstance(ts_index, bool) or not isinstance(ts_index, int) or ts_index < 2:
        raise ValueError("ts_index must be an integer >= 2")
    if weight_index is not None:
        if isinstance(weight_index, bool) or not isinstance(weight_index, int) or weight_index < 2:
            raise ValueError("weight_index must be None or an integer >= 2")
        if weight_index == ts_index:
            raise ValueError("weight_index and ts_index must differ")

    path = Path(path)
    raw: List[Tuple[int, int, float, float]] = []
    nodes = set()
    last_index = max(ts_index, weight_index if weight_index is not None else 0)
    for line_number, raw_line in enumerate(path.open(encoding="utf-8"), start=1):
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) <= last_index:
            raise ValueError(f"line {line_number}: missing timestamp or configured weight field")
        u, v = _parse_node_pair(parts, line_number)
        try:
            timestamp = float(parts[ts_index])
            weight = float(parts[weight_index]) if weight_index is not None else 1.0
        except ValueError as exc:
            raise ValueError(f"line {line_number}: timestamp and weight must be numeric") from exc
        if not math.isfinite(timestamp):
            raise ValueError(f"line {line_number}: timestamp must be finite")
        if not math.isfinite(weight):
            raise ValueError(f"line {line_number}: weight must be finite")
        raw.append((u, v, timestamp, weight))
        nodes.update((u, v))

    if not nodes:
        return TemporalGraph(n=0, directed=directed)

    sorted_nodes = sorted(nodes)
    mapping = {old: new for new, old in enumerate(sorted_nodes)}
    graph = TemporalGraph(n=len(sorted_nodes), directed=directed)
    for u, v, timestamp, weight in raw:
        graph.add_event(mapping[u], mapping[v], timestamp, weight)
    return graph


def load_netflow_summary(
    path: str | Path,
    directed: bool = True,
) -> TemporalGraph:
    """Load src dst bytes packets start_ts [end_ts] CSV/edge summaries.

    A header is allowed on the first nonempty row; malformed rows are rejected
    instead of silently skipped or replaced with default values.
    """
    path = Path(path)
    raw: List[Tuple[int, int, float, float]] = []
    nodes = set()
    saw_data = False
    for line_number, raw_line in enumerate(path.open(encoding="utf-8"), start=1):
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.replace(",", " ").split()
        if len(parts) >= 2 and parts[0].lower() in {"src", "source", "source_ip", "source_id"}:
            if saw_data:
                raise ValueError(f"line {line_number}: header found after data rows")
            continue
        if len(parts) < 5:
            raise ValueError(f"line {line_number}: expected at least 5 NetFlow fields")
        u, v = _parse_node_pair(parts, line_number)
        try:
            weight = float(parts[2])
            timestamp = float(parts[4])
        except ValueError as exc:
            raise ValueError(f"line {line_number}: bytes and start_ts must be numeric") from exc
        if not math.isfinite(weight) or not math.isfinite(timestamp):
            raise ValueError(f"line {line_number}: bytes and start_ts must be finite")
        raw.append((u, v, timestamp, weight))
        nodes.update((u, v))
        saw_data = True

    if not nodes:
        return TemporalGraph(n=0, directed=directed)

    sorted_nodes = sorted(nodes)
    mapping = {old: new for new, old in enumerate(sorted_nodes)}
    graph = TemporalGraph(n=len(sorted_nodes), directed=directed)
    for u, v, timestamp, weight in raw:
        graph.add_event(mapping[u], mapping[v], timestamp, weight)
    return graph
