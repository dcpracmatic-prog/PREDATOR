#!/usr/bin/env python3
"""Single-source GWMIN vs MORPH vs auto benchmark.

Modes
-----
scaling  — size ladder ER/BA (default)
pareto   — quality vs MORPH budget on fixed graphs
exact    — gap to CP-SAT optimum on small n (requires ortools)

All modes write under results/<UTC>_<commit>/ from **one** process so CSV/JSON/MD
cannot diverge. Records git commit, CPU, seeds, binary path.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import random
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor" / "clan_src"))

from clan_subnet_detector.detection.independent_set import (  # noqa: E402
    DEFAULT_AUTO_N_THRESHOLD,
    gwmin_independent,
    is_independent,
    is_maximal_independent,
    plan_independent,
)
from clan_subnet_detector.detection.morph_adapter import (  # noqa: E402
    morph_independent,
    morph_status,
)
from clan_subnet_detector.graph.graph import Graph  # noqa: E402


def git_commit() -> str:
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=ROOT,
                stderr=subprocess.DEVNULL,
            )
            .decode()
            .strip()
        )
    except Exception:
        return "unknown"


def erdos_renyi(n: int, avg_deg: float, seed: int) -> Graph:
    rng = random.Random(seed)
    p = avg_deg / max(n - 1, 1)
    edges = [(i, j) for i in range(n) for j in range(i + 1, n) if rng.random() < p]
    return Graph.from_edges(n, edges, directed=False)


def barabasi_albert(n: int, m: int, seed: int) -> Graph:
    rng = random.Random(seed)
    if n <= m:
        edges = [(i, j) for i in range(n) for j in range(i + 1, n)]
        return Graph.from_edges(n, edges, directed=False)
    edges = [(i, j) for i in range(m + 1) for j in range(i + 1, m + 1)]
    deg = [m] * (m + 1) + [0] * (n - m - 1)
    for new in range(m + 1, n):
        targets = set()
        total = sum(deg[:new])
        while len(targets) < m and total > 0:
            r = rng.random() * total
            acc = 0.0
            for v in range(new):
                acc += deg[v]
                if acc >= r:
                    targets.add(v)
                    break
        for t in targets:
            edges.append((new, t))
            deg[new] += 1
            deg[t] += 1
    return Graph.from_edges(n, edges, directed=False)


def median(xs: Sequence[float]) -> float:
    s = sorted(float(x) for x in xs)
    return float(s[len(s) // 2])


def iqr(xs: Sequence[float]) -> Tuple[float, float]:
    s = sorted(float(x) for x in xs)
    n = len(s)
    return float(s[n // 4]), float(s[(3 * n) // 4])


def exact_mis_cpsat(
    g: Graph, time_limit_s: float = 10.0
) -> Tuple[Optional[List[int]], Optional[int], str]:
    """Return (vertices, size, status). status is OPTIMAL|FEASIBLE|FAILED|NO_ORTOOLS."""
    try:
        from ortools.sat.python import cp_model
    except ImportError:
        return None, None, "NO_ORTOOLS"

    model = cp_model.CpModel()
    x = [model.NewBoolVar(f"v{i}") for i in range(g.n)]
    # undirected: one constraint per unordered edge
    seen = set()
    for u in range(g.n):
        for v in g.adj[u]:
            if u < v and (u, v) not in seen:
                seen.add((u, v))
                model.Add(x[u] + x[v] <= 1)
    model.Maximize(sum(x))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    solver.parameters.num_search_workers = 1
    st = solver.Solve(model)
    if st in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        verts = [i for i in range(g.n) if solver.Value(x[i]) == 1]
        label = "OPTIMAL" if st == cp_model.OPTIMAL else "FEASIBLE"
        return verts, len(verts), label
    return None, None, "FAILED"


def new_out_dir() -> Path:
    out = ROOT / "results" / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{git_commit()}"
    out.mkdir(parents=True, exist_ok=True)
    return out


def write_meta(out: Path, mode: str, args: argparse.Namespace, status: dict, extra: dict) -> None:
    meta = {
        "mode": mode,
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git_commit": git_commit(),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "morph": status,
        "args": {
            "budget_ms": getattr(args, "budget_ms", None),
            "budgets": getattr(args, "budgets", None),
            "reps": args.reps,
            "avg_deg": args.avg_deg,
            "auto_n_threshold": getattr(args, "auto_n_threshold", DEFAULT_AUTO_N_THRESHOLD),
            "seed": args.seed,
            "n_list": getattr(args, "n_list", None),
        },
        **extra,
    }
    (out / "report.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    (ROOT / "results" / "LATEST").write_text(str(out.relative_to(ROOT)) + "\n", encoding="utf-8")


def run_scaling(args: argparse.Namespace) -> Path:
    status = morph_status()
    if args.require_morph and not status.get("available"):
        raise SystemExit(f"MORPH not available: {status}")

    n_list = [int(x) for x in args.n_list.split(",")]
    out = new_out_dir()
    rows: List[Dict[str, Any]] = []

    families = [
        ("ER", lambda n, seed: erdos_renyi(n, args.avg_deg, seed)),
        ("BA", lambda n, seed: barabasi_albert(n, max(2, int(args.avg_deg // 2)), seed)),
    ]

    for family, builder in families:
        for n in n_list:
            times: Dict[str, List[float]] = defaultdict(list)
            sizes: Dict[str, List[int]] = defaultdict(list)
            ok: Dict[str, List[bool]] = defaultdict(list)
            maximal: Dict[str, List[bool]] = defaultdict(list)
            resolved_auto: List[str] = []
            m_edges = 0
            for r in range(args.reps):
                seed = args.seed + r * 1009 + n
                g = builder(n, seed)
                m_edges = g.edge_count()

                t0 = time.perf_counter()
                vg = gwmin_independent(g)
                times["gwmin"].append((time.perf_counter() - t0) * 1000)
                sizes["gwmin"].append(len(vg))
                ok["gwmin"].append(is_independent(g, vg))
                maximal["gwmin"].append(is_maximal_independent(g, vg))

                if status.get("available"):
                    t0 = time.perf_counter()
                    vm = morph_independent(g, budget_ms=args.budget_ms, seed=seed)
                    times["morph"].append((time.perf_counter() - t0) * 1000)
                    sizes["morph"].append(len(vm))
                    ok["morph"].append(is_independent(g, vm))
                    maximal["morph"].append(is_maximal_independent(g, vm))
                else:
                    times["morph"].append(float("nan"))
                    sizes["morph"].append(0)
                    ok["morph"].append(False)
                    maximal["morph"].append(False)

                tr: List[dict] = []
                t0 = time.perf_counter()
                va = plan_independent(
                    g,
                    method="auto",
                    budget_ms=args.budget_ms,
                    seed=seed,
                    trace_out=tr,
                    auto_n_threshold=args.auto_n_threshold,
                )
                times["auto"].append((time.perf_counter() - t0) * 1000)
                sizes["auto"].append(len(va))
                ok["auto"].append(is_independent(g, va))
                maximal["auto"].append(is_maximal_independent(g, va))
                resolved_auto.append((tr[0] or {}).get("resolved", "?"))

            g_med, m_med = median(sizes["gwmin"]), median(sizes["morph"])
            gain = (
                100.0 * (m_med / max(g_med, 1) - 1.0)
                if status.get("available")
                else float("nan")
            )
            expect_gwmin = n < args.auto_n_threshold
            auto_policy_ok = (
                all(r == "gwmin" for r in resolved_auto)
                if expect_gwmin
                else all(r in ("morph", "gwmin") for r in resolved_auto)
            )
            q1g, q3g = iqr(times["gwmin"])
            q1m, q3m = iqr(times["morph"])
            row = {
                "family": family,
                "n": n,
                "m": m_edges,
                "budget_ms": args.budget_ms,
                "reps": args.reps,
                "auto_n_threshold": args.auto_n_threshold,
                "gwmin_ms_med": median(times["gwmin"]),
                "gwmin_ms_q1": q1g,
                "gwmin_ms_q3": q3g,
                "morph_ms_med": median(times["morph"]),
                "morph_ms_q1": q1m,
                "morph_ms_q3": q3m,
                "auto_ms_med": median(times["auto"]),
                "gwmin_size_med": g_med,
                "morph_size_med": m_med,
                "auto_size_med": median(sizes["auto"]),
                "size_gain_morph_vs_gwmin_pct": gain,
                "gwmin_all_independent": all(ok["gwmin"]),
                "morph_all_independent": all(ok["morph"]) if status.get("available") else False,
                "auto_all_independent": all(ok["auto"]),
                "auto_not_worse_than_gwmin": median(sizes["auto"]) >= g_med - 1e-9,
                "auto_policy_ok": auto_policy_ok,
                "auto_resolved_modes": ",".join(sorted(set(resolved_auto))),
            }
            rows.append(row)
            print(
                f"[{family}] n={n:<5d} gwmin={row['gwmin_ms_med']:7.1f}ms/{int(g_med)} "
                f"morph={row['morph_ms_med']:7.1f}ms/{int(m_med)} gain={gain:+.1f}% "
                f"auto→{row['auto_resolved_modes']} policy_ok={auto_policy_ok}"
            )

    csv_path = out / "scaling.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    checks = {
        "morph_available": bool(status.get("available")),
        "all_independent": all(
            r["gwmin_all_independent"] and r["auto_all_independent"] for r in rows
        ),
        "auto_never_worse_than_gwmin": all(r["auto_not_worse_than_gwmin"] for r in rows),
        "auto_policy_ok": all(r["auto_policy_ok"] for r in rows),
    }
    gains = [r["size_gain_morph_vs_gwmin_pct"] for r in rows if r["size_gain_morph_vs_gwmin_pct"] == r["size_gain_morph_vs_gwmin_pct"]]
    mean_gain = sum(gains) / max(1, len(gains))

    md = [
        "# Independent-set planner — scaling",
        "",
        f"- Commit `{git_commit()}` | budget {args.budget_ms} ms | reps {args.reps} | avg_deg {args.avg_deg}",
        f"- auto: n < {args.auto_n_threshold} → GWMIN",
        "",
        "## Checks",
    ]
    for k, v in checks.items():
        md.append(f"- `{k}`: **{'PASS' if v else 'FAIL'}**")
    md += ["", f"- Mean MORPH size gain vs GWMIN: **{mean_gain:.2f}%**", "", "| family | n | gwmin_ms | morph_ms | auto_ms | |S|_g | |S|_m | gain% | auto |",
           "|--------|---|----------|----------|---------|------|------|-------|------|"]
    for r in rows:
        md.append(
            f"| {r['family']} | {r['n']} | {r['gwmin_ms_med']:.1f} | {r['morph_ms_med']:.1f} | "
            f"{r['auto_ms_med']:.1f} | {int(r['gwmin_size_med'])} | {int(r['morph_size_med'])} | "
            f"{r['size_gain_morph_vs_gwmin_pct']:+.2f} | `{r['auto_resolved_modes']}` |"
        )
    md += [
        "",
        "## Limitations",
        "- Synthetic ER/BA; single avg degree unless you pass --avg-deg.",
        "- MORPH wall time tracks the budget, not asymptotic complexity.",
        "",
    ]
    (out / "report.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    write_meta(out, "scaling", args, status, {"checks": checks, "mean_size_gain_pct": mean_gain, "rows": rows})
    _plots_scaling(out, rows, args.budget_ms)
    print("WROTE", out)
    print("CHECKS", checks)
    return out


def run_pareto(args: argparse.Namespace) -> Path:
    """Quality vs wall time while sweeping MORPH budget."""
    status = morph_status()
    if not status.get("available"):
        raise SystemExit(f"MORPH required for pareto mode: {status}")

    budgets = [int(x) for x in args.budgets.split(",")]
    n_list = [int(x) for x in args.n_list.split(",")]
    out = new_out_dir()
    rows: List[Dict[str, Any]] = []

    for family, builder in [
        ("ER", lambda n, seed: erdos_renyi(n, args.avg_deg, seed)),
        ("BA", lambda n, seed: barabasi_albert(n, max(2, int(args.avg_deg // 2)), seed)),
    ]:
        for n in n_list:
            # Fixed graph per (family,n) so budgets are comparable
            g = builder(n, args.seed + n)
            m_edges = g.edge_count()

            t0 = time.perf_counter()
            vg = gwmin_independent(g)
            gw_ms = (time.perf_counter() - t0) * 1000
            gw_sz = len(vg)
            assert is_independent(g, vg)

            for b in budgets:
                sizes, times = [], []
                for r in range(args.reps):
                    seed = args.seed + r * 17 + b
                    t0 = time.perf_counter()
                    vm = morph_independent(g, budget_ms=b, seed=seed)
                    times.append((time.perf_counter() - t0) * 1000)
                    sizes.append(len(vm))
                    assert is_independent(g, vm)
                m_sz = median(sizes)
                m_ms = median(times)
                rows.append(
                    {
                        "family": family,
                        "n": n,
                        "m": m_edges,
                        "budget_ms": b,
                        "reps": args.reps,
                        "gwmin_ms": gw_ms,
                        "gwmin_size": gw_sz,
                        "morph_ms_med": m_ms,
                        "morph_size_med": m_sz,
                        "size_gain_pct": 100.0 * (m_sz / max(gw_sz, 1) - 1.0),
                        "size_delta": m_sz - gw_sz,
                    }
                )
                print(
                    f"[pareto {family} n={n}] budget={b:>4d}ms "
                    f"morph={m_ms:7.1f}ms size={int(m_sz)} "
                    f"(gwmin {gw_ms:.1f}ms/{gw_sz}) gain={rows[-1]['size_gain_pct']:+.1f}%"
                )

    with (out / "pareto.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    md = [
        "# Pareto — MORPH quality vs time budget",
        "",
        f"- Commit `{git_commit()}` | budgets {args.budgets} | reps {args.reps}",
        "- Same graph per (family, n); only seed of MORPH varies across reps.",
        "",
        "| family | n | budget_ms | morph_ms | |S|_m | |S|_g | gain% | Δsize |",
        "|--------|---|-----------|----------|------|------|-------|-------|",
    ]
    for r in rows:
        md.append(
            f"| {r['family']} | {r['n']} | {r['budget_ms']} | {r['morph_ms_med']:.1f} | "
            f"{int(r['morph_size_med'])} | {r['gwmin_size']} | {r['size_gain_pct']:+.2f} | {int(r['size_delta'])} |"
        )
    md += [
        "",
        "## Reading the frontier",
        "- Horizontal axis conceptually = wall time ≈ budget.",
        "- Vertical = size gain % vs GWMIN on the same graph.",
        "- If gain saturates at low budget, higher budgets only buy latency cost.",
        "",
    ]
    (out / "report.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    write_meta(out, "pareto", args, status, {"rows": rows})
    _plots_pareto(out, rows)
    print("WROTE", out)
    return out


def run_exact(args: argparse.Namespace) -> Path:
    """Gap of heuristics to CP-SAT optimum on small graphs."""
    status = morph_status()
    n_list = [int(x) for x in args.n_list.split(",")]
    # Cap for exact mode
    n_list = [n for n in n_list if n <= args.exact_max_n]
    if not n_list:
        n_list = [20, 30, 40, 50, 60, 80]
        n_list = [n for n in n_list if n <= args.exact_max_n]

    out = new_out_dir()
    rows: List[Dict[str, Any]] = []

    for family, builder in [
        ("ER", lambda n, seed: erdos_renyi(n, args.avg_deg, seed)),
        ("BA", lambda n, seed: barabasi_albert(n, max(2, int(args.avg_deg // 2)), seed)),
    ]:
        for n in n_list:
            for r in range(args.reps):
                seed = args.seed + r * 1009 + n
                g = builder(n, seed)
                t0 = time.perf_counter()
                opt_v, opt_sz, st = exact_mis_cpsat(g, time_limit_s=args.exact_time_limit)
                opt_ms = (time.perf_counter() - t0) * 1000
                if opt_sz is None:
                    print(f"[exact {family} n={n} r={r}] CP-SAT {st} — skip")
                    continue
                assert is_independent(g, opt_v or [])

                t0 = time.perf_counter()
                vg = gwmin_independent(g)
                gw_ms = (time.perf_counter() - t0) * 1000
                gw_sz = len(vg)

                if status.get("available"):
                    t0 = time.perf_counter()
                    vm = morph_independent(g, budget_ms=args.budget_ms, seed=seed)
                    m_ms = (time.perf_counter() - t0) * 1000
                    m_sz = len(vm)
                else:
                    m_ms, m_sz = float("nan"), 0

                row = {
                    "family": family,
                    "n": n,
                    "m": g.edge_count(),
                    "rep": r,
                    "seed": seed,
                    "opt_status": st,
                    "opt_size": opt_sz,
                    "opt_ms": opt_ms,
                    "gwmin_size": gw_sz,
                    "gwmin_ms": gw_ms,
                    "gwmin_gap_pct": 100.0 * (1.0 - gw_sz / max(opt_sz, 1)),
                    "morph_size": m_sz,
                    "morph_ms": m_ms,
                    "morph_gap_pct": 100.0 * (1.0 - m_sz / max(opt_sz, 1))
                    if status.get("available")
                    else float("nan"),
                    "budget_ms": args.budget_ms,
                }
                rows.append(row)
                print(
                    f"[exact {family} n={n}] opt={opt_sz} ({st}, {opt_ms:.0f}ms) "
                    f"gwmin={gw_sz} gap={row['gwmin_gap_pct']:.1f}% "
                    f"morph={m_sz} gap={row['morph_gap_pct']:.1f}%"
                )

    if not rows:
        raise SystemExit("No exact rows produced (install ortools / relax limits)")

    with (out / "exact.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    # Aggregate by family,n
    from statistics import mean

    agg_keys = sorted({(r["family"], r["n"]) for r in rows})
    agg = []
    for fam, n in agg_keys:
        sub = [r for r in rows if r["family"] == fam and r["n"] == n]
        agg.append(
            {
                "family": fam,
                "n": n,
                "reps": len(sub),
                "opt_size_mean": mean(r["opt_size"] for r in sub),
                "gwmin_gap_pct_mean": mean(r["gwmin_gap_pct"] for r in sub),
                "morph_gap_pct_mean": mean(r["morph_gap_pct"] for r in sub),
                "all_optimal_status": all(r["opt_status"] == "OPTIMAL" for r in sub),
            }
        )

    md = [
        "# Gap to exact MIS (CP-SAT)",
        "",
        f"- Commit `{git_commit()}` | n≤{args.exact_max_n} | CP-SAT limit {args.exact_time_limit}s",
        f"- MORPH budget {args.budget_ms} ms | avg_deg {args.avg_deg}",
        "",
        "## Mean gap to optimum (% below |S*|)",
        "",
        "| family | n | reps | |S*| mean | GWMIN gap% | MORPH gap% | all OPTIMAL |",
        "|--------|---|------|-----------|------------|------------|-------------|",
    ]
    for a in agg:
        md.append(
            f"| {a['family']} | {a['n']} | {a['reps']} | {a['opt_size_mean']:.1f} | "
            f"{a['gwmin_gap_pct_mean']:.2f} | {a['morph_gap_pct_mean']:.2f} | {a['all_optimal_status']} |"
        )
    md += [
        "",
        "Gap% = 100 * (1 - |S_heuristic| / |S*|). Lower is better.",
        "",
    ]
    (out / "report.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    write_meta(
        out,
        "exact",
        args,
        status,
        {"rows": rows, "aggregate": agg, "checks": {"all_cpsat_optimal": all(a["all_optimal_status"] for a in agg)}},
    )
    _plots_exact(out, agg)
    print("WROTE", out)
    return out


def _plots_scaling(out: Path, rows: List[dict], budget_ms: int) -> None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as e:
        (out / "plots_skipped.txt").write_text(str(e), encoding="utf-8")
        return
    for family in ("ER", "BA"):
        sub = [r for r in rows if r["family"] == family]
        if not sub:
            continue
        ns = [r["n"] for r in sub]
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.plot(ns, [r["size_gain_morph_vs_gwmin_pct"] for r in sub], "s-", label="MORPH size gain % vs GWMIN")
        ax.axhline(0, color="gray", lw=0.8)
        ax.set_xscale("log")
        ax.set_xlabel("n")
        ax.set_ylabel("size gain %")
        ax.set_title(f"{family}: quality gain")
        ax.grid(True, which="both", alpha=0.3)
        ax.legend(fontsize=8)
        fig.tight_layout()
        fig.savefig(out / f"gain_{family}.png", dpi=120)
        plt.close(fig)

        fig, ax = plt.subplots(figsize=(6, 4))
        ax.plot(ns, [r["gwmin_ms_med"] for r in sub], "o-", label="GWMIN")
        ax.plot(ns, [r["morph_ms_med"] for r in sub], "s-", label=f"MORPH (budget {budget_ms}ms)")
        ax.plot(ns, [r["auto_ms_med"] for r in sub], "d--", label="auto")
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_xlabel("n")
        ax.set_ylabel("median ms")
        ax.set_title(f"{family}: latency")
        ax.grid(True, which="both", alpha=0.3)
        ax.legend(fontsize=8)
        fig.tight_layout()
        fig.savefig(out / f"latency_{family}.png", dpi=120)
        plt.close(fig)


def _plots_pareto(out: Path, rows: List[dict]) -> None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as e:
        (out / "plots_skipped.txt").write_text(str(e), encoding="utf-8")
        return
    for family in ("ER", "BA"):
        sub = [r for r in rows if r["family"] == family]
        if not sub:
            continue
        fig, ax = plt.subplots(figsize=(6, 4))
        for n in sorted({r["n"] for r in sub}):
            pts = sorted([r for r in sub if r["n"] == n], key=lambda r: r["budget_ms"])
            ax.plot(
                [r["morph_ms_med"] for r in pts],
                [r["size_gain_pct"] for r in pts],
                "o-",
                label=f"n={n}",
            )
        ax.axhline(0, color="gray", lw=0.8)
        ax.set_xlabel("MORPH wall time (ms, median)")
        ax.set_ylabel("size gain % vs GWMIN")
        ax.set_title(f"{family}: Pareto (quality vs time)")
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=8)
        fig.tight_layout()
        fig.savefig(out / f"pareto_{family}.png", dpi=120)
        plt.close(fig)


def _plots_exact(out: Path, agg: List[dict]) -> None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as e:
        (out / "plots_skipped.txt").write_text(str(e), encoding="utf-8")
        return
    for family in ("ER", "BA"):
        sub = [a for a in agg if a["family"] == family]
        if not sub:
            continue
        ns = [a["n"] for a in sub]
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.plot(ns, [a["gwmin_gap_pct_mean"] for a in sub], "o-", label="GWMIN gap% to opt")
        ax.plot(ns, [a["morph_gap_pct_mean"] for a in sub], "s-", label="MORPH gap% to opt")
        ax.set_xlabel("n")
        ax.set_ylabel("mean gap % below optimum")
        ax.set_title(f"{family}: heuristic gap to CP-SAT")
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=8)
        fig.tight_layout()
        fig.savefig(out / f"gap_{family}.png", dpi=120)
        plt.close(fig)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--mode", choices=["scaling", "pareto", "exact", "all"], default="scaling")
    p.add_argument("--budget-ms", type=int, default=100)
    p.add_argument("--budgets", default="10,50,100,500", help="Comma budgets for pareto mode")
    p.add_argument("--reps", type=int, default=5)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--avg-deg", type=float, default=6.0)
    p.add_argument("--n-list", default="200,500,1000,2000,5000")
    p.add_argument("--auto-n-threshold", type=int, default=DEFAULT_AUTO_N_THRESHOLD)
    p.add_argument("--require-morph", action="store_true")
    p.add_argument("--exact-max-n", type=int, default=80)
    p.add_argument("--exact-time-limit", type=float, default=10.0)
    p.add_argument("--quick", action="store_true")
    args = p.parse_args()

    if args.quick:
        if args.mode in ("scaling", "all"):
            args.n_list = "200,500,1000"
            args.reps = 3
        if args.mode in ("pareto", "all"):
            args.budgets = "10,50,100"
            if args.mode == "pareto":
                args.n_list = "500,2000"
                args.reps = 3
        if args.mode in ("exact", "all"):
            args.n_list = "20,40,60"
            args.reps = 3
            args.exact_time_limit = 5.0

    modes = ["scaling", "pareto", "exact"] if args.mode == "all" else [args.mode]
    # Adjust n-list defaults per mode when user left scaling defaults on non-scaling mode
    for m in modes:
        a = argparse.Namespace(**vars(args))
        if m == "pareto" and args.mode == "all" and not args.quick:
            a.n_list = "500,2000,5000"
            a.reps = min(args.reps, 5)
        if m == "exact" and args.mode == "all" and not args.quick:
            a.n_list = "20,30,40,50,60,80"
            a.reps = min(args.reps, 5)
        if m == "scaling":
            run_scaling(a)
        elif m == "pareto":
            run_pareto(a)
        else:
            run_exact(a)


if __name__ == "__main__":
    main()
