# Pareto on dense ER (avg degree ≈ 12)

Single-run recipe (reproducible):

```bash
export MORPH_DUMP_BIN=/path/to/dump_morph
python benchmarks/run_benchmark.py --mode pareto \
  --families ER --avg-deg-list 12 \
  --n-list 200,500,1000,2000 \
  --budgets 10,50,100,500 --reps 5 --seed 42
```

## Result snapshot (commit near `116f780`, 5 reps, seed 42)

| n | budget | morph ms | \|S\|_m | \|S\|_g | gain% |
|---|--------|----------|--------|--------|-------|
| 200 | 10 | 15 | 56 | 52 | **+7.7** |
| 200 | 50 | 56 | 57 | 52 | **+9.6** |
| 200 | 100 | 107 | 57 | 52 | +9.6 |
| 200 | 500 | 506 | 58 | 52 | **+11.5** |
| 500 | 10 | 17 | 136 | 131 | +3.8 |
| 500 | 50–500 | 58–508 | 137–138 | 131 | **+4.6–5.3** |
| 1000 | 10 | 19 | 272 | 265 | +2.6 |
| 1000 | 500 | 511 | 275 | 265 | +3.8 |
| 2000 | 10 | 26 | 538 | 527 | +2.1 |
| 2000 | 100–500 | 117–519 | 543 | 527 | **+3.0** |

## Reading

1. **Most of the gain appears by 10–50 ms.** Going from 100→500 ms adds little except on the smallest graph (+9.6→+11.5 at n=200).
2. **Relative gain shrinks with n** on this density (~12): from ~10% at n=200 to ~3% at n=2000.
3. At **n≥2000**, MORPH at 10 ms is already **faster than GWMIN** (26 ms vs 42 ms) *and* slightly better (+2%).
4. Default `auto` threshold n=1500 still makes sense: below that, paying ≥50 ms for a few nodes is rarely worth it unless the graph is known dense and quality matters more than latency.

## Implication for the planner

Optional future refinement (not required for packaging): density-aware `auto` (e.g. prefer MORPH earlier when avg degree ≳ 10). The size-only threshold remains a safe default.
