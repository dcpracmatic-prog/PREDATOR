"""Minimal temporal support: timestamped edges and sliding windows.

An edge event is (u, v, timestamp [, weight]). Windows extract a static Graph
over [t0, t1] for the existing detectors.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Sequence, Tuple

from .graph import Graph


@dataclass(frozen=True)
class EdgeEvent:
    u: int
    v: int
    ts: float
    weight: float = 1.0


@dataclass
class TemporalGraph:
    """Collection of timestamped edge events over a fixed node set."""
    n: int
    events: List[EdgeEvent] = field(default_factory=list)
    directed: bool = False

    def add_event(self, u: int, v: int, ts: float, weight: float = 1.0) -> None:
        if not (0 <= u < self.n and 0 <= v < self.n):
            raise IndexError("node index out of range")
        self.events.append(EdgeEvent(u, v, ts, weight))

    def time_range(self) -> Tuple[float, float]:
        if not self.events:
            return 0.0, 0.0
        ts = [e.ts for e in self.events]
        return min(ts), max(ts)

    def window(self, t0: float, t1: float) -> Graph:
        """Induce a static Graph from events with ts in [t0, t1]."""
        edges = [
            (e.u, e.v, e.weight)
            for e in self.events
            if t0 <= e.ts <= t1
        ]
        return Graph.from_edges(self.n, edges, directed=self.directed)

    def sliding_windows(
        self,
        width: float,
        step: float,
    ) -> List[Tuple[float, float, Graph]]:
        """Generate consecutive windows of given width and step."""
        if width <= 0 or step <= 0:
            raise ValueError("width and step must be positive")
        t_min, t_max = self.time_range()
        if t_max < t_min:
            return []
        windows: List[Tuple[float, float, Graph]] = []
        t = t_min
        while t <= t_max:
            t1 = t + width
            windows.append((t, t1, self.window(t, t1)))
            t += step
        return windows
