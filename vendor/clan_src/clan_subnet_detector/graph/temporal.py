"""Minimal temporal support: timestamped edges and sliding windows."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from numbers import Real
from typing import List, Tuple

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

    def __post_init__(self) -> None:
        if isinstance(self.n, bool) or not isinstance(self.n, int):
            raise TypeError("n must be an integer")
        if self.n < 0:
            raise ValueError("n must be non-negative")
        if not isinstance(self.directed, bool):
            raise TypeError("directed must be a bool")

    def add_event(self, u: int, v: int, ts: float, weight: float = 1.0) -> None:
        for label, node in (("u", u), ("v", v)):
            if isinstance(node, bool) or not isinstance(node, int):
                raise TypeError(f"event endpoint {label} must be an integer")
            if node < 0 or node >= self.n:
                raise IndexError("node index out of range")
        if isinstance(ts, bool) or not isinstance(ts, Real) or not math.isfinite(float(ts)):
            raise ValueError("timestamp must be a finite real number")
        if isinstance(weight, bool) or not isinstance(weight, Real) or not math.isfinite(float(weight)):
            raise ValueError("event weight must be a finite real number")
        self.events.append(EdgeEvent(u, v, float(ts), float(weight)))

    def time_range(self) -> Tuple[float, float]:
        if not self.events:
            return 0.0, 0.0
        timestamps = [event.ts for event in self.events]
        return min(timestamps), max(timestamps)

    def window(self, t0: float, t1: float) -> Graph:
        """Induce a static Graph from events with timestamps in [t0, t1]."""
        for label, value in (("t0", t0), ("t1", t1)):
            if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(float(value)):
                raise ValueError(f"{label} must be a finite number")
        if t0 > t1:
            raise ValueError("t0 must be <= t1")
        edges = [
            (event.u, event.v, event.weight)
            for event in self.events
            if t0 <= event.ts <= t1
        ]
        return Graph.from_edges(self.n, edges, directed=self.directed)

    def sliding_windows(
        self,
        width: float,
        step: float,
    ) -> List[Tuple[float, float, Graph]]:
        """Generate consecutive windows of a positive finite width and step."""
        for label, value in (("width", width), ("step", step)):
            if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(float(value)) or value <= 0:
                raise ValueError(f"{label} must be a positive finite number")
        t_min, t_max = self.time_range()
        windows: List[Tuple[float, float, Graph]] = []
        t = t_min
        while t <= t_max:
            t1 = t + width
            windows.append((t, t1, self.window(t, t1)))
            next_t = t + step
            if next_t <= t:
                raise ValueError("step is too small to advance the window timestamp")
            t = next_t
        return windows
