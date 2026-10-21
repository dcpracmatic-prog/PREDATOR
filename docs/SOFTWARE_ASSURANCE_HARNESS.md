# ZTGE Software Assurance Harness

## Product objective

ZTGE is the assurance orchestrator for keeping software functional and secure across developer updates, including changes proposed by coding agents. The product is a reproducible decision backed by evidence linking a source change to findings, candidate repairs, verification runs, and the final decision.

## Responsibilities

- ZTGE core: discover change boundaries, resolve policy, schedule checks, correlate findings, apply release gates, and emit evidence bundles.
- clan-subnet-detector / MORPH: optional graph-analysis and heuristic plugins. Verify returned structures independently; heuristics are not proofs of optimality or security boundaries.
- verificacion_formal: adapter for applicable contracts. Preserve scope, assumptions, tool versions, counterexamples, and the distinction between proven-in-domain, refuted, and unresolved.
- ATL Edge patterns: reuse one canonical execution path, schema validation before effects, allow-list policies, fail-closed decisions, bounded repair, and independent invariant checks. Do not import its data-plane or crypto code wholesale.
- NEXUS patterns: preserve human authority over promotion, separate proposal from authorization, require evidence before claiming success, and treat application-level isolation honestly. A timeout is not a sandbox.
- HBAG patterns: use deterministic fixtures, independent numerical oracles, bit-exact checks where appropriate, stable machine-readable output, and separate correctness from performance claims.

## Required change lifecycle

1. Identify base and candidate commits and the changed-file set.
2. Resolve applicable contracts, dependency graph, tests, security checks, and formal obligations.
3. Execute checks in a controlled worker. Record exact commands, toolchain versions, environment identity, timeouts, exit codes, and artifact digests.
4. Normalize results to PASS, FAIL, UNKNOWN, SKIPPED, or NOT_APPLICABLE. A timeout, unavailable solver, missing check, or malformed output must never silently become PASS.
5. Preserve failure reproducers. An agent may propose a minimal patch in a disposable worktree, but cannot modify the trusted policy, verifier, signing keys, or acceptance rules used to judge that patch.
6. Re-run the reproducer, then required regression/security checks and applicable formal obligations.
7. Bind the decision to source-tree digests, policy/test-plan versions, tool versions, and evidence artifacts. Independently verify signatures.
8. Keep default operation advisory. Merge, release, deployment, privileged operations, and policy changes require explicit policy and human authorization.

## Trust boundaries

- Repository code, dependencies, test output, and agent proposals are untrusted inputs.
- Do not execute arbitrary agent code in the controller process.
- A subprocess timeout is availability control, not a sandbox. Untrusted code needs a disposable container/VM or equivalent boundary, resource limits, and restricted network/credentials.
- Never let a candidate patch change the policy or verifier that decides whether that same patch passes.
- Graph scores, heuristic confidence, telemetry, and signatures are not substitutes for acceptance criteria.
- Missing or failed optional analyzers may be tolerated only by explicit policy; record the fallback.

## Integration order

### P0 — correctness
- Correct false-positive checks such as unconditional-success conditions (`... or True`).
- Normalize verification statuses; unknown/unrun checks cannot satisfy mandatory gates.
- Add an end-to-end seeded regression demonstrating detection and rejection of a bad repair.

### P1 — evidence
- Validate evidence bundles against a versioned JSON Schema.
- Record commits, changed paths, commands, exit codes, timeouts, tool versions, inputs/outputs, and SHA-256 digests.
- Store repair lineage in an append-only or externally anchored ledger; a hash chain needs external protection of its trusted head.

### P2 — guarded repair
- Add an opt-in repair worker isolated from controller credentials and trusted policy.
- Require reproducer, regression, security, and applicable formal checks after every patch.
- Require human approval for promotion and changes to the trust base.

### P3 — optimization
- Add graph-based impact selection and adaptive test scheduling only after comparing against a full-suite baseline. Optimization must never weaken mandatory correctness gates.

## Licensing and provenance

Do not copy source code across these repositories without compatibility review. ZTGE declares AGPL-3.0, ATL Edge Elastic License 2.0, HBAG Apache-2.0, and verificacion_formal Elastic License 2.0. NEXUS is private and its applicable license was not established in this review. Reuse architectural patterns and define adapters first; review provenance and version pinning before vendoring or linking code.

## Current status

This document defines the target contract. It does not claim that an autonomous repair worker, hardened sandbox, CI trigger, or complete evidence ledger already exists. Those capabilities require implementation and end-to-end validation.