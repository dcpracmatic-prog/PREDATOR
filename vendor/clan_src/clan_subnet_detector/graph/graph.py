"""Core graph representation for traffic and social-interaction analysis.

Nodes are identified by non-negative integers (0 .. n-1).
Edges may be directed or undirected and may carry a numeric weight.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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
        if not self.adj:
            self.adj = [{} for _ in range(self.n)]
        if len(self.adj) != self.n:
            raise ValueError("adj length must equal n")

    @classmethod
    def from_edges(
        cls,
        n: int,
        edges: Iterable[Tuple[int, int] | Tuple[int, int, float] | Edge],
        directed: bool = False,
    ) -> "Graph":
        g = cls(n=n, directed=directed)
        for e in edges:
            if isinstance(e, Edge):
                g.add_edge(e.u, e.v, e.weight)
            elif len(e) == 2:
                g.add_edge(e[0], e[1])
            else:
                g.add_edge(e[0], e[1], e[2])
        return g

    def add_edge(self, u: int, v: int, weight: float = 1.0) -> None:
        if not (0 <= u < self.n and 0 <= v < self.n):
            raise IndexError("node index out of range")
        self.adj[u][v] = self.adj[u].get(v, 0.0) + weight
        if not self.directed and u != v:
            self.adj[v][u] = self.adj[v].get(u, 0.0) + weight

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
        node_list = sorted(set(nodes))
        mapping = {old: new for new, old in enumerate(node_list)}
        sub = Graph(n=len(node_list), directed=self.directed)
        for old_u in node_list:
            if old_u < 0 or old_u >= self.n:
                raise IndexError("node index out of range")
            for old_v, w in self.adj[old_u].items():
                if old_v in mapping and (self.directed or old_u <= old_v):
                    # Undirected adjacency stores each edge twice; insert it once
                    # or add_edge() would double its weight in the induced graph.
                    sub.add_edge(mapping[old_u], mapping[old_v], w)
        return sub

    def has_edge(self, u: int, v: int) -> bool:
        return v in self.adj[u]
