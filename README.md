# Independent-set planner (GWMIN + MORPH)

Fast GWMIN heuristic and budgeted MORPH solver for the maximum independent set
problem on undirected graphs, with **size-aware `auto` selection**.

## Key results (synthetic ER/BA, avg degree ≈ 6, 5 reps)

- **Correctness:** all returned sets are independent (verified).
- **Quality:** MORPH improves median size over GWMIN by roughly **0–3.6%** on ER; **~0%** on BA.
- **Latency:** GWMIN grows with *n* (≈2 ms at n=200, hundreds of ms at n=5k). MORPH sits near its **time budget** (e.g. 100 ms). Cross-over around **n ≈ 1.5–1.7k**.
- **`auto`:** uses **GWMIN when n < 1500**, MORPH when larger (if the binary is available). It does **not** pay the MORPH budget on tiny graphs.

Reproduce:

```bash
cd vendor/morph_src && make dump_morph
export MORPH_DUMP_BIN="$(pwd)/dump_morph"
python benchmarks/run_benchmark.py          # or --quick
# artifacts: results/<timestamp>_<commit>/{scaling.csv,report.json,report.md,*.png}
```

## When to use which method

| Situation | Method |
|-----------|--------|
| n ≪ 1500, need low latency | `gwmin` or `auto` |
| n ≫ 1500, can spend ~100 ms | `morph` or `auto` |
| Force pure Python | `gwmin` |
| Force compiled path | `morph` (falls back if binary missing) |

## Quickstart (library)

```bash
pip install -e ".[yaml]"
export MORPH_DUMP_BIN=/path/to/dump_morph
python -c "
from clan_subnet_detector import Graph, plan_independent, is_independent
g = Graph.from_edges(5, [(0,1),(1,2),(2,3)])
S = plan_independent(g, method='auto', budget_ms=50)
assert is_independent(g, S)
print(S)
"
```


## Benchmark modes

```bash
python benchmarks/run_benchmark.py --mode scaling          # size ladder
python benchmarks/run_benchmark.py --mode pareto           # quality vs MORPH budget (10/50/100/500)
python benchmarks/run_benchmark.py --mode exact            # gap to CP-SAT optimum (n≤80, needs ortools)
python benchmarks/run_benchmark.py --mode all --quick      # smoke all modes
make bench-quick
```

Artifacts land in `results/<UTC>_<commit>/` (CSV + report.json + report.md + PNG).

## Limitations (honest)

- Benchmarks use **synthetic** ER/BA only; one average degree; few repetitions.
- Validity is checked; maximality is reported separately and not always required.
- MORPH is a **heuristic with a fixed budget**, not an exact MIS solver.
- No claim of optimality or production network control.

## Layout

```
benchmarks/run_benchmark.py   # single source of CSV/JSON/MD/PNG
results/                      # dated run folders (generated)
vendor/clan_src/              # Python package
vendor/morph_src/             # MORPH C++ sources (build dump_morph)
contracts/ schemas/ docs/     # optional zero-trust / audit packaging
```

Spanish notes: see `docs/` (architecture, signed reports, packaging).
