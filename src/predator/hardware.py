"""Portable host-resource inspection used for safe request sizing and profiling."""
from __future__ import annotations

import os
import platform
import sys
from pathlib import Path
from typing import Optional

MiB = 1024 * 1024
MAX_REQUEST_BYTES = 64 * MiB
MAX_GRAPH_VERTICES = 2_000_000
MAX_GRAPH_EDGES = 10_000_000
GRAPH_MEMORY_BYTES_PER_VERTEX = 4096
DEFAULT_REQUEST_BYTES = 1 * MiB
REQUEST_MEMORY_RESERVE_FACTOR = 128


def _read_int(path: str) -> Optional[int]:
    try:
        raw = Path(path).read_text(encoding="ascii").strip()
        if raw.lower() == "max":
            return None
        value = int(raw)
        return value if value >= 0 else None
    except (OSError, ValueError):
        return None


def _cgroup_dirs(controller: str) -> list[Path]:
    """Return the process cgroup directory and ancestors for v1/v2 mounts."""
    roots: list[Path] = []
    try:
        for line in Path("/proc/self/cgroup").read_text(encoding="ascii").splitlines():
            parts = line.split(":", 2)
            if len(parts) != 3:
                continue
            controllers, relative = parts[1], parts[2].lstrip("/")
            # A cgroup-v2 membership has an empty controller field; the unified
            # hierarchy carries both memory and CPU controller files.
            if not controllers or controller in controllers.split(","):
                mount = Path("/sys/fs/cgroup") if not controllers else Path("/sys/fs/cgroup") / controller
                roots.append(mount / relative)
    except OSError:
        pass
    roots.append(Path("/sys/fs/cgroup"))
    result: list[Path] = []
    seen = set()
    for root in roots:
        for directory in (root, *root.parents):
            if directory in seen or not str(directory).startswith("/sys/fs/cgroup"):
                continue
            seen.add(directory)
            result.append(directory)
    return result


def available_memory_bytes() -> Optional[int]:
    """Estimate memory available to this process, respecting cgroup ancestors."""
    candidates = []
    for directory in _cgroup_dirs("memory"):
        pairs = ((directory / "memory.max", directory / "memory.current"),
                 (directory / "memory.limit_in_bytes", directory / "memory.usage_in_bytes"))
        for limit_path, current_path in pairs:
            limit, current = _read_int(str(limit_path)), _read_int(str(current_path))
            if limit is not None and 0 < limit < (1 << 60) and current is not None:
                remaining = limit - current
                if remaining > 0:
                    candidates.append(remaining)
    try:
        for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
            if line.startswith("MemAvailable:"):
                candidates.append(int(line.split()[1]) * 1024)
                break
    except (OSError, ValueError, IndexError):
        pass
    if not candidates:
        try:
            page_size = os.sysconf("SC_PAGE_SIZE")
            pages = os.sysconf("SC_AVPHYS_PAGES")
            candidates.append(int(page_size * pages))
        except (OSError, ValueError, AttributeError):
            return None
    return min(candidates)


def recommended_max_request_bytes(memory_bytes: Optional[int] = None) -> int:
    """Recommend a bounded JSON body cap reserving ~16x body size for parsing/graph data.

    This is a conservative starting point, not a guarantee of peak RSS. Operators can
    lower it or set an explicit limit with PREDATOR_MAX_REQUEST_BYTES.
    """
    memory = available_memory_bytes() if memory_bytes is None else memory_bytes
    if memory is None:
        return DEFAULT_REQUEST_BYTES
    return min(MAX_REQUEST_BYTES, max(64 * 1024, int(memory) // REQUEST_MEMORY_RESERVE_FACTOR))


def effective_cpu_count() -> Optional[float]:
    """Estimate CPUs available to this process, respecting cgroup ancestors and affinity."""
    limits: list[float] = []
    for directory in _cgroup_dirs("cpu"):
        try:
            quota, period = (directory / "cpu.max").read_text(encoding="ascii").split()[:2]
            if quota != "max":
                value = int(quota) / int(period)
                if value > 0:
                    limits.append(value)
        except (OSError, ValueError, IndexError, ZeroDivisionError):
            pass
        quota = _read_int(str(directory / "cpu.cfs_quota_us"))
        period = _read_int(str(directory / "cpu.cfs_period_us"))
        if quota is not None and period and quota > 0:
            limits.append(quota / period)
    try:
        affinity = os.sched_getaffinity(0)
        if affinity:
            limits.append(float(len(affinity)))
    except (AttributeError, OSError):
        pass
    if not limits:
        count = os.cpu_count()
        return float(count) if count else None
    return min(limits)


def system_profile() -> dict[str, object]:
    memory = available_memory_bytes()
    return {
        "platform": platform.platform(),
        "system": platform.system(),
        "machine": platform.machine(),
        "python": sys.version.split()[0],
        "logical_cpu_count": os.cpu_count(),
        "effective_cpu_count_estimate": effective_cpu_count(),
        "cpu_count_note": "affinity/cgroup-aware estimate; not a performance benchmark",
        "available_memory_bytes": memory,
        "recommended_max_request_bytes": recommended_max_request_bytes(memory),
        "request_memory_reserve_factor": REQUEST_MEMORY_RESERVE_FACTOR,
        "request_limit_hard_cap_bytes": MAX_REQUEST_BYTES,
        "max_graph_vertices": max_graph_vertices(memory),
        "max_graph_edges": max_graph_edges(memory),
    }


def max_graph_edges(memory_bytes: Optional[int] = None) -> int:
    """Estimate an input edge ceiling while reserving memory for Python graph state."""
    memory = available_memory_bytes() if memory_bytes is None else memory_bytes
    if memory is None:
        return 10_000
    # Python adjacency maps dominate storage; assume up to 512 bytes per undirected
    # edge and reserve 7/8 of available memory for parsing, solver and runtime.
    return min(MAX_GRAPH_EDGES, max(0, int(memory) // (8 * 512)))


def max_graph_vertices(memory_bytes: Optional[int] = None) -> int:
    """Bound graph allocation to a conservative fraction of available memory."""
    memory = available_memory_bytes() if memory_bytes is None else memory_bytes
    if memory is None:
        return 2_048
    # Allocate no more than roughly 1/8 of currently available RAM to per-vertex
    # structures, using a deliberately conservative 4 KiB/node estimate.
    return min(MAX_GRAPH_VERTICES, max(0, int(memory) // (8 * GRAPH_MEMORY_BYTES_PER_VERTEX)))


def recommended_morph_budget_ms(graph_n: int, profile_path: Optional[str] = None) -> Optional[int]:
    """Return nearest-size MORPH budget from an explicitly configured host profile."""
    import json

    path = profile_path or os.getenv("PREDATOR_HARDWARE_PROFILE")
    if not path or type(graph_n) is not int or graph_n < 0:
        return None
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("schema") != "predator.hardware_profile.v1":
        return None
    recommendations = data.get("candidate_recommendations", [])
    rows = [
        row for row in recommendations
        if isinstance(row, dict)
        and row.get("method") == "morph"
        and type(row.get("n")) is int
        and type(row.get("budget_ms")) is int
        and 1 <= row["budget_ms"] <= 600_000
    ] if isinstance(recommendations, list) else []
    if not rows:
        return None
    nearest_n = min(abs(row["n"] - graph_n) for row in rows)
    cohort = [row for row in rows if abs(row["n"] - graph_n) == nearest_n]
    best_size = max(float(row.get("median_solution_size", 0)) for row in cohort)
    quality_floor = best_size * 0.99
    eligible = [row for row in cohort if float(row.get("median_solution_size", 0)) >= quality_floor]
    selected = min(eligible, key=lambda row: (float(row.get("median_wall_ms", float("inf"))), row["budget_ms"]))
    return selected["budget_ms"]
