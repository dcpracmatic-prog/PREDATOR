# Clan-Subnet Detector (MVP 0.2)

**MVP auditable** for detection of **cliques (clanes)**, **dense subgraphs** and **isolated subnetworks** in communication / interaction graphs (internet traffic, social networks).

Every reported structure is **independently re-verified** against the original graph before it is accepted into the audit report. Reports can be **HMAC-signed** (or ECDSA when `cryptography` is available) so they become verifiable artefacts in the spirit of ChannelGuardian / TDCP policy bindings.

## What the MVP does

1. Loads a graph (static edge-list, timestamped edge-list, NetFlow-style summary, or built-in demo).
2. Optional **temporal window** extraction over timestamped events.
3. Runs detectors:
   - Greedy clique construction.
   - Independent-set planner: **GWMIN** (pure Python) or **MORPH** (compiled binary via `dump_morph`).
   - **k-core** and **Charikar densest-subgraph** peeling (complement to clique).
4. Independently verifies each result.
5. Emits an audit report (JSON + Markdown) and optionally a **signed envelope**.

## Quick start

```bash
export PYTHONPATH=src
# Optional: point to the MORPH vertex-dump binary
export MORPH_DUMP_BIN=/path/to/dump_morph

python -m clan_subnet_detector.cli --demo --out results/
python -m clan_subnet_detector.cli --demo --method morph --budget-ms 100 --out results/
python -m clan_subnet_detector.cli --demo --sign-hmac 'your-secret' --out results/

# Timestamped edges + window
python -m clan_subnet_detector.cli --timestamped data/samples/small_temporal.edgelist \
  --window 100 150 --out results/
```

Smoke:

```bash
./scripts/smoke_test.sh
```

## MORPH integration

Build MORPH and the vertex dump helper:

```bash
git clone https://github.com/dcpracmatic-prog/MORPH.git
cd MORPH && make
# compile dump helper (see project docs) or set MORPH_DUMP_BIN
```

`plan_independent(..., method="morph")` writes a temporary `.gph`, calls `dump_morph`, and returns 0-indexed vertices. If the binary is missing or fails, the planner **falls back to GWMIN** so the audit path remains available.

## Audit contract

| Check | Meaning |
|-------|---------|
| `clique_verified` | Returned nodes form a true clique |
| `independent_set_verified` | Returned nodes form a true independent set |
| `dense_verified` | k-core / densest peeling checks passed |
| `all_findings_verified` | All of the above |

Signed reports (`audit_report.signed.json`) include `digest_sha256`, algorithm, `kid` and the full report payload. Verify with `verify_report_hmac`.

## Layout

```
src/clan_subnet_detector/
├── graph/          # Graph, metrics, TemporalGraph + windows
├── detection/      # clique, independent set (GWMIN/MORPH), k-core, densest
├── scoring/        # risk / isolation scores
├── ingest/         # edge-list, timestamped, NetFlow-style
├── audit/          # run_audit, AuditReport, HMAC/ECDSA signing
└── cli.py
```

## Version

`0.2.0-mvp` — MORPH adapter, dense detectors, temporal windows, signable reports.

## License

See `LICENSE` (proprietary placeholder until formal terms are defined).
