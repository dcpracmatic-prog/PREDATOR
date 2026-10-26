"""Measure planner quality/latency on this host and emit a hardware profile.

Synthetic sparse graphs are a reproducible calibration workload, not customer-data
or real-world evidence. Recommendations are empirical and host/workload-specific.
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import time
from pathlib import Path

from clan_subnet_detector import Graph, is_independent, morph_status, plan_independent
from predator.hardware import system_profile


def _sparse_graph(n: int, seed: int) -> Graph:
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


def _csv_ints(raw: str, label: str) -> list[int]:
    try:
        values = [int(part.strip()) for part in raw.split(",") if part.strip()]
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{label} must be comma-separated integers") from exc
    if not values or any(value <= 0 for value in values):
        raise argparse.ArgumentTypeError(f"{label} values must be positive")
    return values


def run_profile(sizes: list[int], budgets: list[int], seed: int = 20261026, repeats: int = 3) -> dict:
    if type(seed) is not int or seed < 0:
        raise ValueError("seed must be a non-negative integer")
    if type(repeats) is not int or not 2 <= repeats <= 20:
        raise ValueError("repeats must be an integer in [2, 20]")
    if not sizes or any(type(n) is not int or n <= 0 for n in sizes):
        raise ValueError("sizes must be positive integers")
    if not budgets or any(type(b) is not int or b <= 0 for b in budgets):
        raise ValueError("budgets must be positive integers")
    sizes, budgets = list(dict.fromkeys(sizes)), list(dict.fromkeys(budgets))
    host = system_profile()
    memory = host.get("available_memory_bytes")
    # Preflight heuristic only: actual peak RSS depends on graph structure and runtime.
    estimated_bytes_per_vertex = 32 * 1024
    # Unknown memory must not disable the guard; use a small conservative fallback.
    max_n = int(memory // (8 * estimated_bytes_per_vertex)) if isinstance(memory, int) else 2_048
    max_n = min(max_n, 2_000_000)
    selected_sizes = [n for n in sizes if n <= max_n]
    skipped_sizes = [n for n in sizes if n not in selected_sizes]
    status = morph_status()
    methods = ["gwmin"] + (["morph"] if status.get("available") and status.get("emits_vertices") else [])
    samples = []
    for n in selected_sizes:
        # Same graph per repeat group: repeated runtime/solution measurements differ
        # due to solver behavior, not a different generated instance each time.
        graph_seed = seed + n * 1009
        graph = _sparse_graph(n, graph_seed)
        for repeat in range(repeats):
            for method in methods:
                method_budgets = budgets if method == "morph" else [None]
                for budget in method_budgets:
                    trace = []
                    started = time.perf_counter()
                    result = plan_independent(graph, method=method, budget_ms=budget or 100,
                                              seed=graph_seed + repeat, trace_out=trace)
                    elapsed_ms = (time.perf_counter() - started) * 1000.0
                    meta = trace[0] if trace else {}
                    valid = is_independent(graph, result)
                    sample = {
                        "n": n, "m": graph.edge_count(), "repeat": repeat,
                        "method_requested": method, "method_resolved": meta.get("resolved"),
                        "budget_ms": budget, "solution_size": len(result), "valid": valid,
                        "wall_ms": round(elapsed_ms, 3),
                        "morph_wall_ms": (meta.get("morph") or {}).get("wall_ms"),
                        "fallback": bool(meta.get("fallback", False)),
                    }
                    if not valid:
                        raise RuntimeError(f"planner returned invalid independent set: {sample}")
                    samples.append(sample)
    recommendations = []
    for n in selected_sizes:
        for method in methods:
            rows = [s for s in samples if s["n"] == n and s["method_requested"] == method]
            by_budget = {}
            for row in rows:
                by_budget.setdefault(row["budget_ms"], []).append(row)
            candidates = []
            for budget, group in by_budget.items():
                candidates.append({
                    "n": n, "method": method, "budget_ms": budget,
                    "median_solution_size": statistics.median(r["solution_size"] for r in group),
                    "median_wall_ms": round(statistics.median(r["wall_ms"] for r in group), 3),
                    "repeat_count": len(group),
                })
            # Report Pareto tradeoffs; don't collapse solution quality vs time to a
            # single "best" setting or imply a local heuristic proves optimality.
            for candidate in candidates:
                dominated = any(
                    other["median_solution_size"] >= candidate["median_solution_size"]
                    and other["median_wall_ms"] <= candidate["median_wall_ms"]
                    and (other["median_solution_size"] > candidate["median_solution_size"]
                         or other["median_wall_ms"] < candidate["median_wall_ms"])
                    for other in candidates if other is not candidate
                )
                if not dominated:
                    candidate["basis"] = "non-dominated median solution-size/latency tradeoff across repeated runs; not an optimality guarantee"
                    recommendations.append(candidate)
    return {
        "schema": "predator.hardware_profile.v1",
        "host": host, "morph": status,
        "calibration": {
            "seed": seed, "repeats": repeats,
            "synthetic_workload": "deterministic sparse graphs; not real-data evidence",
            "requested_sizes": sizes, "tested_sizes": selected_sizes,
            "skipped_sizes_for_memory_estimate": skipped_sizes, "budgets_ms": budgets,
            "memory_estimate_bytes_per_vertex": estimated_bytes_per_vertex,
            "max_profile_memory_fraction": 0.125,
            "memory_guard_note": "preflight heuristic only; actual peak RSS is not measured or guaranteed",
        },
        "samples": samples, "candidate_recommendations": recommendations,
        "notes": [
            "Candidates are specific to this host and synthetic calibration workload.",
            "Recommendations use repeated medians and show non-dominated quality/latency tradeoffs.",
            "Benchmark representative real inputs separately before setting production limits.",
            "This profile does not silently override request budgets.",
            "MORPH budget_ms is solver search time, not a hard end-to-end wall-time limit.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", default="256,768,1600", help="comma-separated calibration graph sizes")
    parser.add_argument("--budgets-ms", default="25,100,250", help="comma-separated MORPH budgets")
    parser.add_argument("--repeats", type=int, default=3, help="repeated runs per point (2-20)")
    parser.add_argument("--seed", type=int, default=20261026)
    parser.add_argument("--output", type=Path, help="write JSON report to this path")
    args = parser.parse_args(argv)
    sizes = _csv_ints(args.sizes, "sizes")
    budgets = _csv_ints(args.budgets_ms, "budgets-ms")
    report = run_profile(sizes, budgets, args.seed, args.repeats)
    rendered = json.dumps(report, indent=2, sort_keys=True)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
