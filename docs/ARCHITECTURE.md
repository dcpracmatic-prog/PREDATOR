# ZTGE Architecture

## Layers

### 1. MORPH (muscle)

Heuristic Maximum Independent Set solver optimised for low wall-clock latency.
Produces feasible independent sets; does not claim optimality. Integrated via
`dump_morph` binary and the transparent adapter in
`clan_subnet_detector.detection.morph_adapter`.

### 2. Clan-Subnet Detector (brain)

Applies MORPH / GWMIN, greedy cliques, k-core and densest-subgraph peeling to
communication graphs. Emits an `AuditReport` where every structure is
independently re-verified (`is_clique`, `is_independent`, structural checks).

### 3. COMMONWEAVE Zero (shield)

- Declarative YAML contracts for native components and logical planners.
- Generator that emits ctypes adapters with precondition checks.
- Differential verification harnesses and CSG / HMAC seals for acceptance
  certificates.

## Data flow for a typical audit

1. Ingest edge-list / NetFlow / demo graph → `Graph`.
2. Optional temporal window.
3. `run_audit(method="auto")`:
   - greedy clique + verify
   - `plan_independent` (MORPH if available else GWMIN) + verify
   - k-core / densest + soft structural checks
4. Write JSON + Markdown report; optional HMAC / CSG seal.
5. Operator inspects `method_resolved` and `planner_fallback` in the report.

## Trust boundaries

| Boundary | Guarantee |
|----------|-----------|
| Detector → Report | Independent pure verifiers; detector may be swapped |
| MORPH binary → Adapter | Subprocess isolation; fallback recorded |
| Contract → Adapter | Generated code; differential tests against Python oracles |
| Report → Seal | Digest over artefacts; Ed25519 / HMAC |

## Non-goals (current snapshot)

- Autonomous network reconfiguration or code mutation in production.
- Proof of optimality for MORPH solutions.
- Full unbounded formal verification of the entire Python stack.
