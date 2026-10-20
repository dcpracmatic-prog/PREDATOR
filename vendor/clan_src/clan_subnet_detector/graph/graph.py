"""Core graph representation for traffic and social-interaction analysis.

Nodes are identified by non-negative integers (0 .. n-1).
Edges may be directed or undirected and may carry a numeric weight.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from numbers import Real
from typing import Dict, Iterable, List, Optional, Set, Tuple


@dataclass(frozen=True)
class Edge:
    """Directed or undirected edge with optional weight."""
    u: int
    v: int
    weight: float = 1.0


@dataclass
class Graph:
    """Simple adjacency-list graph.

    Parameters
    ----------
    n : int
        Number of nodes (labelled 0 .. n-1).
    directed : bool
        Whether the graph is directed.
    """
    n: int
    directed: bool = False
    adj: List[Dict[int, float]] = field(default_factory=list)
    node_attrs: Dict[int, dict] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.n, bool) or not isinstance(self.n, int):
            raise TypeError("n must be an integer")
        if self.n < 0:
            raise ValueError("n must be non-negative")
        if not isinstance(self.directed, bool):
            raise TypeError("directed must be a bool")
        if not self.adj:
            self.adj = [{} for _ in range(self.n)]
        if len(self.adj) != self.n:
            raise ValueError("adj length must equal n")
        for u, neighbors in enumerate(self.adj):
            if not isinstance(neighbors, dict):
                raise TypeError(f"adj[{u}] must be a dictionary")
            for v, weight in neighbors.items():
                if isinstance(v, bool) or not isinstance(v, int):
                    raise TypeError(f"neighbor index at node {u} must be an integer")
                if v < 0 or v >= self.n:
                    raise IndexError(f"neighbor index out of range at node {u}: {v}")
                self._validate_weight(weight)
        if not self.directed:
            for u, neighbors in enumerate(self.adj):
                for v, weight in neighbors.items():
                    if self.adj[v].get(u) != weight:
                        raise ValueError("undirected adjacency must be symmetric")
    
    @staticmethod
    def _validate_weight(weight: Real) -> float:
        if isinstance(weight, bool) or not isinstance(weight, Real):
            raise TypeError("edge weight must be a finite real number")
        value = float(weight)
        if not math.isfinite(value):
            raise ValueError("edge weight must be finite")
        return value

    @classmethod
    def from_edges(
        cls,
        n: int,
        edges: Iterable[Tuple[int, int] | Tuple[int, int, float] | Edge],
        directed: bool = False,
    ) -> "Graph":
        g = cls(n=n, directed=directed)
        for index, e in enumerate(edges, start=1):
            if isinstance(e, Edge):
                g.add_edge(e.u, e.v, e.weight)
                continue
            if not isinstance(e, (tuple, list)) or len(e) not in (2, 3):
                raise ValueError(f"edge {index} must contain exactly 2 or 3 fields")
            if len(e) == 2:
                g.add_edge(e[0], e[1])
            else:
                g.add_edge(e[0], e[1], e[2])
        return g

    def add_edge(self, u: int, v: int, weight: float = 1.0) -> None:
        for label, node in (("u", u), ("v", v)):
            if isinstance(node, bool) or not isinstance(node, int):
                raise TypeError(f"edge endpoint {label} must be an integer")
            if node < 0 or node >= self.n:
                raise IndexError("node index out of range")
        weight = self._validate_weight(weight)
        self.adj[u][v] = self.adj[u].get(v, 0.0) + weight
        if not math.isfinite(self.adj[u][v]):
            raise ValueError("accumulated edge weight must be finite")
        if not self.directed and u != v:
            self.adj[v][u] = self.adj[v].get(u, 0.0) + weight
            if not math.isfinite(self.adj[v][u]):
                raise ValueError("accumulated edge weight must be finite")

    def neighbors(self, u: int) -> Dict[int, float]:
        return self.adj[u]

    def degree(self, u: int) -> int:
        return len(self.adj[u])

    def edge_count(self) -> int:
        if self.directed:
            return sum(len(neigh) for neigh in self.adj)
        # Count each undirected edge once, including self-loops (stored once).
        return sum(
            1
            for u, neighbors in enumerate(self.adj)
            for v in neighbors
            if u <= v
        )
    def induced_subgraph(self, nodes: Iterable[int]) -> "Graph":
        requested = list(nodes)
        for node in requested:
            if isinstance(node, bool) or not isinstance(node, int):
                raise TypeError("subgraph node labels must be integers")
            if node < 0 or node >= self.n:
                raise IndexError("node index out of range")
        node_list = sorted(set(requested))
        mapping = {old: new for new, old in enumerate(node_list)}
        sub = Graph(n=len(node_list), directed=self.directed)
        for old_u in node_list:
            for old_v, weight in self.adj[old_u].items():
                if old_v in mapping and (self.directed or old_u <= old_v):
                    # Undirected adjacency stores each edge twice; insert once.
                    sub.add_edge(mapping[old_u], mapping[old_v], weight)
        return sub
    def has_edge(self, u: int, v: int) -> bool:
        return v in self.adj[u]
