"""Edge-list and minimal NetFlow-style loaders."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple, Union

from ..graph.graph import Graph
from ..graph.temporal import EdgeEvent, TemporalGraph


def load_edge_list(
    path: str | Path,
    directed: bool = False,
    weighted: bool = False,
) -> Graph:
    """Load a simple edge list (static).

    Format (whitespace-separated):
        u v          # unweighted
        u v w        # weighted (if weighted=True)
    """
    path = Path(path)
    raw_edges: List[Tuple[int, int, float]] = []
    nodes = set()
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            u, v = int(parts[0]), int(parts[1])
            w = float(parts[2]) if weighted and len(parts) > 2 else 1.0
            raw_edges.append((u, v, w))
            nodes.add(u)
            nodes.add(v)

    if not nodes:
        return Graph(n=0, directed=directed)

    sorted_nodes = sorted(nodes)
    mapping = {old: new for new, old in enumerate(sorted_nodes)}
    n = len(sorted_nodes)
    g = Graph(n=n, directed=directed)
    for u, v, w in raw_edges:
        g.add_edge(mapping[u], mapping[v], w)
    return g


def load_timestamped_edge_list(
    path: str | Path,
    directed: bool = False,
    ts_index: int = 2,
    weight_index: Optional[int] = None,
) -> TemporalGraph:
    """Load timestamped edges into a TemporalGraph.

    Default format:
        u v timestamp [weight]

    Indices are 0-based over whitespace-split fields.
    Node IDs are remapped to a contiguous 0..n-1 range.
    """
    path = Path(path)
    raw: List[Tuple[int, int, float, float]] = []
    nodes = set()
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            u, v = int(parts[0]), int(parts[1])
            ts = float(parts[ts_index])
            w = float(parts[weight_index]) if weight_index is not None and len(parts) > weight_index else 1.0
            raw.append((u, v, ts, w))
            nodes.add(u)
            nodes.add(v)

    if not nodes:
        return TemporalGraph(n=0, directed=directed)

    sorted_nodes = sorted(nodes)
    mapping = {old: new for new, old in enumerate(sorted_nodes)}
    tg = TemporalGraph(n=len(sorted_nodes), directed=directed)
    for u, v, ts, w in raw:
        tg.add_event(mapping[u], mapping[v], ts, w)
    return tg


def load_netflow_summary(
    path: str | Path,
    directed: bool = True,
) -> TemporalGraph:
    """Minimal NetFlow-style CSV/edge summary.

    Expected columns (header optional, detected by non-numeric first field):
        src dst bytes packets start_ts [end_ts]

    Uses start_ts as event timestamp and bytes as weight.
    """
    path = Path(path)
    raw: List[Tuple[int, int, float, float]] = []
    nodes = set()
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.replace(",", " ").split()
            # skip header
            try:
                u, v = int(parts[0]), int(parts[1])
            except ValueError:
                continue
            # try: src dst bytes packets start_ts
            try:
                weight = float(parts[2]) if len(parts) > 2 else 1.0
                ts = float(parts[4]) if len(parts) > 4 else float(parts[2])
            except (ValueError, IndexError):
                weight = 1.0
                ts = 0.0
            raw.append((u, v, ts, weight))
            nodes.add(u)
            nodes.add(v)

    if not nodes:
        return TemporalGraph(n=0, directed=directed)

    sorted_nodes = sorted(nodes)
    mapping = {old: new for new, old in enumerate(sorted_nodes)}
    tg = TemporalGraph(n=len(sorted_nodes), directed=directed)
    for u, v, ts, w in raw:
        tg.add_event(mapping[u], mapping[v], ts, w)
    return tg
