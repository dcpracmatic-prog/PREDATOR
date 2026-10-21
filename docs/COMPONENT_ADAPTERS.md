# ZTGE Component Adapter Map

This page maps existing projects to narrow adapters. It intentionally avoids copying implementation code before license and provenance review.

| Source | Reusable capability | ZTGE integration boundary | Limitation |
|---|---|---|---|
| [NEXUS](https://github.com/dcpracmatic-prog/Nexus) | Human authority, evidence-before-success, explicit exit gate | Gate-policy and promotion lifecycle | V1 application/process sandbox is not a kernel/container boundary; declared tests are not executed evidence |
| [ATL Edge](https://github.com/dcpracmatic-prog/atl-edge) | Canonical execution seam, schema-first validation, allow-list policy, fail-closed behavior, bounded repair, invariant checks, hash-chain telemetry | Optional proposal gate around untrusted repair proposals | MORPH-8 is not IAM, a general sandbox, or proof of correctness; hash chain needs external head protection |
| [HBAG SpMM](https://github.com/dcpracmatic-prog/hbag-spmm-benchmark) | Reference-oracle comparisons, deterministic fixtures, bit-exact checks, stable CSV, correctness/performance separation | Test-plan patterns and performance-regression adapters for numeric/native components | Speedup is workload-dependent; timing is noisy; tolerance checks are not formal proofs |
| [verificacion_formal](https://github.com/dcpracmatic-prog/verificacion_formal) | Explicit proof scope, finite-domain exhaustive tests, SMT obligations, counterexamples, unresolved states | Normalize formal results into evidence bundles and gate policy | Bounded testing is not unbounded proof; compiling SMT harnesses is not solver verification |
| [clan-subnet-detector](https://github.com/dcpracmatic-prog/clan-subnet-detector) | Graph analysis and independent predicates | Optional impact/dependency/interaction graph plugin | Graph score and heuristic output are not correctness proofs |

## Adapter contract

Each adapter accepts a versioned input and returns a versioned result containing:

- stable check ID and adapter/version identity;
- source commit or artifact digest;
- scope, assumptions, and environment;
- status: PASS, FAIL, UNKNOWN, SKIPPED, or NOT_APPLICABLE;
- reproducible command/input and output artifact hashes;
- duration, timeout, exit code, and error details;
- references to findings and proof obligations.

Adapters must not write directly to the release decision. Only the ZTGE policy gate combines mandatory results.

## Safe reuse sequence

1. Implement schema validation and adapter interfaces inside ZTGE.
2. Add stub adapters and contract tests for malformed/unknown outputs.
3. Integrate one source at a time using pinned versions/commits.
4. Test fail-closed behavior when an adapter crashes, times out, is absent, or returns malformed JSON.
5. Review license and provenance before vendoring or copying source.