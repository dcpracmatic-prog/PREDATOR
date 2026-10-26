#!/usr/bin/env python3
"""Compare PREDATOR heuristics with an exact CP-SAT MIS on a supplied real graph.

This tool never synthesizes or silently substitutes graph data. Pass an actual
edge-list file; metadata includes its SHA-256, size, and source citation string.
Exact solving is opt-in and guarded by a node-count limit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from clan_subnet_detector.detection.independent_set import gwmin_independent, is_independent
from clan_subnet_detector.detection.morph_adapter import morph_independent, morph_status
from clan_subnet_detector.graph.graph import Graph
from clan_subnet_detector.ingest.edge_list import load_edge_list


def exact_mis_cpsat(graph: Graph, time_limit_s: float):
    try:
        from ortools.sat.python import cp_model
    except ImportError as exc:
        raise RuntimeError("Exact comparison requires `pip install 'predator[exact]'` (OR-Tools).") from exc
    model = cp_model.CpModel()
    selected = [model.NewBoolVar(f"x_{i}") for i in range(graph.n)]
    seen = set()
    for u in range(graph.n):
        for v in graph.adj[u]:
            if u == v:
                model.Add(selected[u] == 0)
            else:
                edge = (min(u, v), max(u, v))
                if edge not in seen:
                    model.Add(selected[u] + selected[v] <= 1)
                    seen.add(edge)
    model.Maximize(sum(selected))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    solver.parameters.num_search_workers = 1
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None, solver.StatusName(status)
    nodes = [i for i, var in enumerate(selected) if solver.Value(var)]
    return nodes, solver.StatusName(status)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("edge_list", type=Path, help="real edge-list file; rows: source target")
    parser.add_argument("--source", required=True, help="dataset citation, URL, or provenance description")
    parser.add_argument("--out", type=Path, default=Path("results/real-graph-mis.json"))
    parser.add_argument("--format", choices=["edge-list", "networkrepository-mtx"], default="edge-list",
                        help="input format; NetworkRepository MTX variant has a dimensions row then edge pairs")
    parser.add_argument("--exact", action="store_true", help="also run exact OR-Tools CP-SAT")
    parser.add_argument("--exact-max-n", type=int, default=120, help="refuse exact solve above this node count")
    parser.add_argument("--exact-time-limit", type=float, default=60.0)
    parser.add_argument("--method", choices=["auto", "gwmin", "morph"], default="auto")
    parser.add_argument("--budget-ms", type=int, default=100)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args(argv)
    if not args.edge_list.is_file():
        parser.error(f"edge-list does not exist: {args.edge_list}")
    if args.exact_max_n < 1 or args.exact_time_limit <= 0 or args.budget_ms <= 0:
        parser.error("exact-max-n, exact-time-limit and budget-ms must be positive")

    raw = args.edge_list.read_bytes()
    if args.format == "edge-list":
        graph = load_edge_list(args.edge_list)
    else:
        lines = args.edge_list.read_text(encoding="utf-8").splitlines()
        if not lines:
            parser.error("NetworkRepository matrix file is empty")
        dims = lines[0].split()
        if len(dims) < 2 or not all(part.isdigit() for part in dims[:2]):
            parser.error("expected NetworkRepository matrix first row: node_count node_count")
        n_declared = int(dims[0])
        normalized = args.edge_list.with_suffix(args.edge_list.suffix + ".edges.tmp")
        normalized.write_text("\n".join(lines[1:]) + "\n", encoding="utf-8")
        try:
            graph = load_edge_list(normalized)
        finally:
            normalized.unlink(missing_ok=True)
        if graph.n != n_declared:
            parser.error(f"matrix declares n={n_declared}, but edge list maps to n={graph.n}")
    if graph.n == 0:
        parser.error("edge-list contains no graph edges")
    if args.exact and graph.n > args.exact_max_n:
        parser.error(f"refusing exact solve for n={graph.n} > --exact-max-n={args.exact_max_n}")

    measurements = []
    for name, fn in (("gwmin", lambda: gwmin_independent(graph)),
                     ("morph", lambda: morph_independent(graph, budget_ms=args.budget_ms, seed=args.seed))):
        if name == "morph" and not morph_status().get("available"):
            measurements.append({"method": name, "status": "unavailable", "warning": morph_status().get("reason")})
            continue
        started = time.perf_counter()
        try:
            nodes = fn()
            elapsed_ms = (time.perf_counter() - started) * 1000
            measurements.append({"method": name, "status": "ok", "wall_ms": elapsed_ms,
                                "size": len(nodes), "verified": is_independent(graph, nodes),
                                "nodes": list(nodes)})
        except Exception as exc:
            measurements.append({"method": name, "status": "error", "error": str(exc)})

    exact = None
    if args.exact:
        started = time.perf_counter()
        nodes, status = exact_mis_cpsat(graph, args.exact_time_limit)
        exact = {"status": status, "wall_ms": (time.perf_counter() - started) * 1000,
                 "size": len(nodes) if nodes is not None else None,
                 "nodes": nodes, "verified": is_independent(graph, nodes) if nodes is not None else None}
        if nodes is not None:
            for row in measurements:
                if row.get("status") == "ok":
                    row["gap_pct_to_exact"] = 100 * (1 - row["size"] / max(len(nodes), 1))

    result = {
        "schema": "predator.real_graph_mis.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": args.source,
        "input": {"format": args.format, "file_name": args.edge_list.name, "sha256": hashlib.sha256(raw).hexdigest(),
                  "n": graph.n, "m": graph.edge_count(), "directed": graph.directed},
        "environment": {"python": sys.version.split()[0], "platform": platform.platform(),
                        "method": args.method, "seed": args.seed, "budget_ms": args.budget_ms},
        "measurements": measurements,
        "exact": exact,
        "caveat": "Results apply only to this input graph and environment; heuristic comparison is not a general performance claim.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.out), "n": graph.n, "m": graph.edge_count(),
                      "exact": exact["status"] if exact else "not requested"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
