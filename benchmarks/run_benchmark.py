#!/usr/bin/env python3
"""Single-source GWMIN vs MORPH vs auto benchmark.

Generates CSV, JSON, Markdown and (if matplotlib available) PNG from **one** run
so artifacts cannot diverge. Records git commit, CPU, seeds, and binary path.
"""

from __future__ import annotations

import argparse
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
from typing import Dict, List, Tuple

# Repo root = parent of benchmarks/
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
                ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, stderr=subprocess.DEVNULL
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


def median(xs: List[float]) -> float:
    s = sorted(xs)
    return float(s[len(s) // 2])


def iqr(xs: List[float]) -> Tuple[float, float]:
    s = sorted(xs)
    n = len(s)
    return float(s[n // 4]), float(s[(3 * n) // 4])


def run(args: argparse.Namespace) -> Path:
    status = morph_status()
    if args.require_morph and not status.get("available"):
        raise SystemExit(f"MORPH not available: {status}")

    n_list = [int(x) for x in args.n_list.split(",")]
    out = ROOT / "results" / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{git_commit()}"
    out.mkdir(parents=True, exist_ok=True)

    rows = []
    for family, builder in [
        ("ER", lambda n, seed: erdos_renyi(n, args.avg_deg, seed)),
        ("BA", lambda n, seed: barabasi_albert(n, max(2, int(args.avg_deg // 2)), seed)),
    ]:
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
            gain = 100.0 * (m_med / max(g_med, 1) - 1.0) if status.get("available") else float("nan")
            # auto must never be worse than GWMIN in median size
            auto_not_worse = median(sizes["auto"]) >= g_med - 1e-9
            # below threshold auto should resolve to gwmin
            expect_gwmin = n < args.auto_n_threshold
            auto_policy_ok = all(
                (r == "gwmin") if expect_gwmin else (r in ("morph", "gwmin"))
                for r in resolved_auto
            )
            if expect_gwmin:
                auto_policy_ok = all(r == "gwmin" for r in resolved_auto)

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
                "gwmin_all_maximal": all(maximal["gwmin"]),
                "auto_not_worse_than_gwmin": auto_not_worse,
                "auto_policy_ok": auto_policy_ok,
                "auto_resolved_modes": ",".join(sorted(set(resolved_auto))),
            }
            rows.append(row)
            print(
                f"[{family}] n={n:<5d} gwmin={row['gwmin_ms_med']:7.1f}ms/{int(g_med)} "
                f"morph={row['morph_ms_med']:7.1f}ms/{int(m_med)} gain={gain:+.1f}% "
                f"auto→{row['auto_resolved_modes']} policy_ok={auto_policy_ok}"
            )

    # Write CSV
    import csv

    csv_path = out / "scaling.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    checks = {
        "morph_available": bool(status.get("available")),
        "all_independent": all(r["gwmin_all_independent"] and r["auto_all_independent"] for r in rows),
        "auto_never_worse_than_gwmin": all(r["auto_not_worse_than_gwmin"] for r in rows),
        "auto_policy_ok": all(r["auto_policy_ok"] for r in rows),
    }
    mean_gain = sum(r["size_gain_morph_vs_gwmin_pct"] for r in rows if r["size_gain_morph_vs_gwmin_pct"] == r["size_gain_morph_vs_gwmin_pct"]) / max(
        1, sum(1 for r in rows if r["size_gain_morph_vs_gwmin_pct"] == r["size_gain_morph_vs_gwmin_pct"])
    )
    meta = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git_commit": git_commit(),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "morph": status,
        "budget_ms": args.budget_ms,
        "reps": args.reps,
        "avg_deg": args.avg_deg,
        "auto_n_threshold": args.auto_n_threshold,
        "seed": args.seed,
        "checks": checks,
        "mean_size_gain_morph_vs_gwmin_pct": mean_gain,
        "rows": rows,
    }
    (out / "report.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

    # Markdown from same rows
    lines = [
        "# Independent-set planner benchmark",
        "",
        f"- Generated (UTC): `{meta['generated_utc']}`",
        f"- Git commit: `{meta['git_commit']}`",
        f"- Budget MORPH: {args.budget_ms} ms | reps: {args.reps} | avg_deg: {args.avg_deg}",
        f"- auto threshold: n < {args.auto_n_threshold} → GWMIN",
        f"- MORPH binary: `{status.get('binary')}`",
        "",
        "## Checks",
    ]
    for k, v in checks.items():
        lines.append(f"- `{k}`: **{'PASS' if v else 'FAIL'}**")
    lines += [
        "",
        f"- Mean size gain MORPH vs GWMIN: **{mean_gain:.2f}%**",
        "",
        "## Scaling (same run as CSV/JSON)",
        "",
        "| family | n | gwmin_ms | morph_ms | auto_ms | gwmin|S| | morph|S| | gain% | auto modes | policy |",
        "|--------|---|----------|----------|---------|----------|----------|-------|------------|--------|",
    ]
    for r in rows:
        lines.append(
            f"| {r['family']} | {r['n']} | {r['gwmin_ms_med']:.1f} | {r['morph_ms_med']:.1f} | "
            f"{r['auto_ms_med']:.1f} | {int(r['gwmin_size_med'])} | {int(r['morph_size_med'])} | "
            f"{r['size_gain_morph_vs_gwmin_pct']:+.2f} | `{r['auto_resolved_modes']}` | "
            f"{'ok' if r['auto_policy_ok'] else 'FAIL'} |"
        )
    lines += [
        "",
        "## Key takeaways",
        "",
        f"- Cross-over: GWMIN is cheaper below n≈{args.auto_n_threshold}; MORPH budget is ~{args.budget_ms} ms wall.",
        f"- Quality: MORPH median gain ≈ {mean_gain:.1f}% overall (often ~0% on BA, small positive on ER).",
        "- `auto` uses GWMIN on small graphs and only spends the MORPH budget when n is large.",
        "",
        "## Limitations",
        "",
        "- Synthetic ER/BA only; single average degree; modest reps.",
        "- `is_independent` checks validity; maximality is reported separately.",
        "- MORPH is a heuristic with a fixed time budget — not an exact solver.",
        "",
    ]
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Optional plots
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

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
            ax.set_title(f"{family}: quality gain (not overlaid sizes)")
            ax.grid(True, which="both", alpha=0.3)
            ax.legend(fontsize=8)
            fig.tight_layout()
            fig.savefig(out / f"gain_{family}.png", dpi=120)
            plt.close(fig)

            fig, ax = plt.subplots(figsize=(6, 4))
            ax.plot(ns, [r["gwmin_ms_med"] for r in sub], "o-", label="GWMIN wall ms")
            ax.plot(ns, [r["morph_ms_med"] for r in sub], "s-", label=f"MORPH wall ms (budget {args.budget_ms})")
            ax.plot(ns, [r["auto_ms_med"] for r in sub], "d--", label="auto wall ms")
            ax.set_xscale("log")
            ax.set_yscale("log")
            ax.set_xlabel("n")
            ax.set_ylabel("median ms")
            ax.set_title(f"{family}: latency (auto should track GWMIN for small n)")
            ax.grid(True, which="both", alpha=0.3)
            ax.legend(fontsize=8)
            fig.tight_layout()
            fig.savefig(out / f"latency_{family}.png", dpi=120)
            plt.close(fig)
    except Exception as e:
        (out / "plots_skipped.txt").write_text(str(e), encoding="utf-8")

    # pointer latest
    latest = ROOT / "results" / "LATEST"
    latest.write_text(str(out.relative_to(ROOT)) + "\n", encoding="utf-8")
    print("WROTE", out)
    print("CHECKS", checks)
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--budget-ms", type=int, default=100)
    p.add_argument("--reps", type=int, default=5)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--avg-deg", type=float, default=6.0)
    p.add_argument("--n-list", default="200,500,1000,2000,5000")
    p.add_argument("--auto-n-threshold", type=int, default=DEFAULT_AUTO_N_THRESHOLD)
    p.add_argument("--require-morph", action="store_true")
    p.add_argument("--quick", action="store_true", help="n=200,500,1000 reps=3")
    args = p.parse_args()
    if args.quick:
        args.n_list = "200,500,1000"
        args.reps = 3
    run(args)


if __name__ == "__main__":
    main()
