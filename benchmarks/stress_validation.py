#!/usr/bin/env python3
"""Reproducible correctness/performance smoke benchmark for ZTGE planners.

This is a regression guard, not a publishable benchmark. It records complete
wall time, solution size, chosen planner/fallback, fixed seeds, and environment.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import platform
import random
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor" / "clan_src"))

from clan_subnet_detector.detection.independent_set import is_independent, plan_independent  # noqa: E402
from clan_subnet_detector.detection.morph_adapter import morph_status  # noqa: E402
from clan_subnet_detector.graph.graph import Graph  # noqa: E402


def sparse_graph(n: int, seed: int) -> Graph:
    """Build a deterministic sparse, non-directed graph without third-party deps."""
    rng = random.Random(seed)
    edges = set()
    for u in range(n):
        for offset in (1, 5, 19):
            v = u + offset
            if v < n and rng.random() < 0.55:
                edges.add((u, v))
        for _ in range(2):
            v = rng.randrange(n)
            if u != v:
                edges.add((min(u, v), max(u, v)))
    return Graph.from_edges(n, sorted(edges), directed=False)


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(p * len(ordered)) - 1)]


def parse_sizes(raw: str) -> list[int]:
    try:
        sizes = [int(part.strip()) for part in raw.split(",") if part.strip()]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("sizes must be comma-separated integers") from exc
    if not sizes or any(size <= 0 for size in sizes):
        raise argparse.ArgumentTypeError("all sizes must be positive integers")
    return sizes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", type=parse_sizes, default=parse_sizes("256,768,1600"))
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--seed", type=int, default=20261019)
    parser.add_argument("--budget-ms", type=int, default=50)
    parser.add_argument("--max-ms", type=float, default=10000.0, help="maximum accepted wall time per sample")
    parser.add_argument("--output", type=Path, help="optional JSON report path")
    args = parser.parse_args()
    if args.repeats < 1 or args.budget_ms < 1 or args.max_ms <= 0:
        parser.error("repeats, budget-ms, and max-ms must be positive")

    status = morph_status()
    methods = ["gwmin", "auto"]
    if status.get("available") and status.get("emits_vertices"):
        methods.append("morph")

    samples = []
    grouped = defaultdict(list)
    for size in args.sizes:
        for repeat in range(args.repeats):
            seed = args.seed + size * 1009 + repeat
            graph = sparse_graph(size, seed)
            for method in methods:
                trace = []
                started = time.perf_counter()
                result = plan_independent(
                    graph, method=method, budget_ms=args.budget_ms, seed=seed,
                    k=None, trace_out=trace,
                )
                elapsed_ms = (time.perf_counter() - started) * 1000.0
                valid = is_independent(graph, result)
                metadata = trace[0] if trace else {}
                sample = {
                    "n": size, "m": graph.edge_count(), "repeat": repeat, "seed": seed,
                    "requested": method, "resolved": metadata.get("resolved"),
                    "fallback": metadata.get("fallback", False), "size": len(result),
                    "valid": valid, "wall_ms": round(elapsed_ms, 3),
                    "morph_wall_ms": (metadata.get("morph") or {}).get("wall_ms"),
                }
                samples.append(sample)
                grouped[(size, method)].append(sample)
                if not valid:
                    raise RuntimeError(f"invalid independent-set result: {sample}")
                if elapsed_ms > args.max_ms:
                    raise TimeoutError(
                        f"{method} on n={size} took {elapsed_ms:.1f}ms > max {args.max_ms:.1f}ms"
                    )

    summary = []
    for (size, method), rows in sorted(grouped.items()):
        times = [row["wall_ms"] for row in rows]
        summary.append({
            "n": size, "method": method, "samples": len(rows),
            "median_wall_ms": round(statistics.median(times), 3),
            "p95_wall_ms": round(percentile(times, 0.95), 3),
            "max_wall_ms": round(max(times), 3),
            "median_solution_size": statistics.median(row["size"] for row in rows),
            "all_valid": all(row["valid"] for row in rows),
            "resolved_methods": sorted({str(row["resolved"]) for row in rows}),
            "fallback_count": sum(bool(row["fallback"]) for row in rows),
        })
    report = {
        "kind": "ztge.performance_smoke.v1",
        "seed": args.seed, "repeats": args.repeats, "budget_ms": args.budget_ms,
        "max_wall_ms_per_sample": args.max_ms,
        "python": sys.version.split()[0], "platform": platform.platform(),
        "cpu_count": os.cpu_count(), "morph": status,
        "summary": summary, "samples": samples,
    }
    rendered = json.dumps(report, indent=2, sort_keys=True)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
