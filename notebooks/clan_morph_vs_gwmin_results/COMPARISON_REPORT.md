# GWMIN vs MORPH (method=auto) — Performance Report

- Budget: 100 ms

- `morph_available`: **PASS**
- `all_gwmin_verified`: **PASS**
- `all_morph_verified`: **PASS**
- `all_auto_verified`: **PASS**
- `auto_always_resolved_morph`: **PASS**

- Mean size gain MORPH vs GWMIN: **1.16%**

## Scaling (CSV)

See `gwmin_vs_morph_scaling.csv`.

family    n     m  budget_ms  reps  gwmin_ms_med  morph_ms_med  auto_ms_med  gwmin_size_med  morph_size_med  auto_size_med  gwmin_all_ok  morph_all_ok  auto_all_ok  auto_resolved_morph  size_gain_morph_vs_gwmin_pct
    ER  200   620        100     5          0.66        103.29       104.21              77              79             79          True          True         True                 True                          2.60
    ER  500  1504        100     5          3.76        104.12       104.28             195             202            202          True          True         True                 True                          3.59
    ER 1000  3045        100     5         14.97        107.57       105.74             389             400            400          True          True         True                 True                          2.83
    ER 2000  5939        100     5         64.66        108.83       108.66             785             799            800          True          True         True                 True                          1.78
    ER 5000 14961        100     5        394.69        119.12       119.38            1958            1972           1972          True          True         True                 True                          0.72
    BA  200   594        100     5          0.75        105.79       103.50              98              98             98          True          True         True                 True                          0.00
    BA  500  1494        100     5          4.95        104.58       104.69             256             256            256          True          True         True                 True                          0.00
    BA 1000  2994        100     5         19.49        105.89       105.86             511             511            511          True          True         True                 True                          0.00
    BA 2000  5994        100     5         80.68        109.00       108.40            1009            1009           1009          True          True         True                 True                          0.00
    BA 5000 14994        100     5        512.98        118.05       117.95            2539            2540           2540          True          True         True                 True                          0.04

## Audit (BA n=2000)
- GWMIN audit: 287.9 ms, IS size=1017
- auto/MORPH audit: 320.7 ms, IS size=1018
- auto extra: `{'method_requested': 'auto', 'method_resolved': 'morph', 'fallback': False, 'reason': 'MORPH binary used', 'morph': {'method': 'morph', 'binary': 'dump_morph', 'binary_resolved': '/tmp/dump_morph', 'budget_ms': 100, 'seed': 42, 'n_input': 2000, 'm_input': 5994, 'n_after_ban': 2000, 'size': 1018, 'wall_ms': 108.2427729999722, 'returncode': 0, 'ok': True, 'error': '', 'notes': []}, 'k': None, 'budget_ms': 100, 'seed': 42}`
