# Zero-Trust Graph Engine (ZTGE)

Unified architecture that combines three independently verifiable layers:

| Layer | Role | Component |
|-------|------|-----------|
| **MORPH** | Low-latency combinatorial muscle (Maximum Independent Set) | `vendor/morph_src` |
| **Clan-Subnet Detector** | Domain brain — cliques, isolated subnetworks, dense cores, audit | `vendor/clan_src` |
| **COMMONWEAVE Zero** | Trust shield — YAML contracts, generated adapters, differential verification, cryptographic seals | `vendor/cw_zero` + `contracts/` |

**Value proposition:** extreme speed + mathematical independent verification + cryptographic traceability, without silent glue or unverifiable black boxes.

## Architecture

```
[ YAML contracts ] ──(COMMONWEAVE Zero generator)──> [ verified native adapters ]
        │
        ▼
[ Graph / NetFlow / edge-list ] ──(Clan-Subnet Detector)──> [ findings + audit report ]
        │                                                         │
        │                              (optional) MORPH binary ───┘
        ▼
[ CSG / HMAC seal ] ──> immutable acceptance certificate
```

## Transparent MORPH integration

The independent-set planner exposes three methods:

| Method | Behaviour |
|--------|-----------|
| `gwmin` | Pure-Python GWMIN (always available) |
| `morph` | Compiled `dump_morph`; falls back to GWMIN on failure |
| `auto`  | Prefer MORPH when discoverable (default) |

Every run records in the audit report:

- `method_requested` / `method_resolved`
- `fallback` flag and `reason`
- MORPH binary path, budget, seed, wall time (when used)

```bash
# Health check
PYTHONPATH=vendor/clan_src python -m clan_subnet_detector.cli --status

# Audit with transparent planner
PYTHONPATH=vendor/clan_src python -m clan_subnet_detector.cli --demo --method auto --out results/
```

## Expanded contracts

Located in `contracts/` (mirrored under `vendor/cw_zero/contracts/`):

| Contract | Purpose |
|----------|---------|
| `matmul.yaml` | Dense float64 matrix multiply |
| `stats.yaml` | `array_stats` + `histogram` |
| `scale_clamp.yaml` | Scale + clamp with `hi >= lo` precondition |
| `morph_mis.yaml` | Logical CLI contract for MORPH MIS + audit fields |
| `graph_metrics.yaml` | Pure-Python density / components / is_independent / is_clique |

Generate an adapter:

```bash
python vendor/cw_zero/generator/generate_adapter.py \
  --contract contracts/matmul.yaml \
  --lib vendor/cw_zero/c_src/libmatmul.so \
  --out generated/matmul_adapter.py
```

## Quick start

```bash
# 1. Clan detector smoke
PYTHONPATH=vendor/clan_src python -m clan_subnet_detector.cli --demo --method auto --out /tmp/ztge_demo

# 2. Status of MORPH discovery
PYTHONPATH=vendor/clan_src python -m clan_subnet_detector.cli --status

# 3. Engine orchestration helper
python scripts/ztge_status.py
```

## Repository layout

```
zero-trust-graph-engine/
├── README.md                 # this file
├── docs/ARCHITECTURE.md
├── contracts/                # expanded YAML contracts (source of truth)
├── scripts/ztge_status.py
├── src/ztge/                 # thin orchestration package
└── vendor/
    ├── clan_src/             # Clan-Subnet Detector (patched for transparency)
    ├── cw_zero/              # COMMONWEAVE Zero contracts, generator, c_src, seal
    └── morph_src/            # MORPH C++ sources + build notes
```

## Design principles

1. **Independent verification first** — every finding is re-checked by a pure function before it enters the report.
2. **No silent fallbacks without trace** — planner resolution is always recorded.
3. **Contracts as source of truth** — adapters are generated; glue is not hand-maintained.
4. **Honest scope** — MORPH is a low-latency heuristic; formal proofs are bounded as declared in `verificacion_formal`.

## Version

ZTGE consolidation snapshot — 2026-10-19.

## Packaging

See [docs/PACKAGING.md](docs/PACKAGING.md) for SDK / B2B API readiness and next steps.
