# Packaging readiness — Zero-Trust Graph Engine

## Status: base ready for SDK / B2B API packaging

This document records what is already in place for a final SDK or B2B API
service packaging, and what remains for the next increment.

### Ready (base)

| Area | Evidence |
|------|----------|
| Detection + independent verification | `vendor/clan_src` — clique, IS, k-core, densest; pure verifiers |
| Transparent MORPH integration | `method=auto|morph|gwmin`, `MorphRunInfo`, audit `extra` / notes |
| Audit reports | JSON + Markdown; HMAC signing (`audit/signing.py`) |
| Contracts YAML | `contracts/` — matmul, stats, scale_clamp, morph_mis, graph_metrics |
| Adapter generator | `vendor/cw_zero/generator/generate_adapter.py` |
| Engine orchestration | `src/ztge/engine/pipeline.py` |
| Operator status | `scripts/ztge_status.py`, CLI `--status` |
| Benchmarks | `notebooks/` + comparison reports |

### Packaging surfaces

1. **Python SDK** — installable via `pip install -e .` (this `pyproject.toml`).
   Public surface: `clan_subnet_detector` + `ztge.engine.pipeline`.
2. **CLI** — `clan-detect`, `ztge-status` entry points.
3. **B2B API (next)** — thin HTTP layer over `run_audit` / `audit_graph` returning
   the same JSON audit document + optional signed envelope. Not shipped in 0.1.0.

### Next logical steps (not blocking base packaging)

1. Expand YAML contracts for remaining native kernels and graph ingest formats.
2. Standardize signed report schema for external auditors (versioned JSON Schema,
   stable field names, optional Ed25519 via CSG seal path).
3. Publish OpenAPI for the B2B service once the HTTP surface is defined.
4. CI: `make dump_morph` + unit tests + contract differential smoke.

### Build notes

```bash
cd vendor/morph_src && make dump_morph
export MORPH_DUMP_BIN="$(pwd)/dump_morph"
pip install -e ".[yaml,dev]"
PYTHONPATH=vendor/clan_src python -m clan_subnet_detector.cli --status
```

### Honesty bounds

- MORPH is a low-latency heuristic; reports record method resolution and do not claim optimality.
- Formal verification scope is as declared in upstream verificacion_formal (bounded domains / contracts).
- Autonomous network reconfiguration / code mutation is out of scope for this packaging baseline.
