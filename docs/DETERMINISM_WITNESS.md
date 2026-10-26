# ZTGE determinism witness

The optional witness lives in `src/ztge/determinism.py`. It is diagnostic
telemetry, not a security boundary and not a replacement for graph validation,
independent-set checks, contract checks or signature verification. The witness
must never change the verifier's verdict.

## Example

```python
from predator.determinism import best_of_k, code_identity, count_work, evidence_manifest

identity = code_identity([verify_graph])  # use the actual Python verifier
timing = best_of_k(verify_graph, graph, k=7, warmups=1)
work = count_work(verify_graph, graph)
manifest = evidence_manifest(identity=identity, work=work)
```

## Evidence and limits

- Meter records monotonic wall time, thread CPU time where available, process
  CPU time where available, and Linux scheduler run-delay when readable.
  Unsupported metrics are `None`; process CPU time must not be interpreted as
  per-thread CPU time.
- best_of_k retains raw samples and reports minimum, median, p95 and maximum.
  Minimum is a best-case observation, not typical latency. Use uninstrumented
  runs for primary performance claims.
- code_identity hashes Python code plus inspectable defaults, closure cells,
  annotations and referenced globals. Unsupported object state is marked
  opaque and makes `complete` false. The hash is not a signature and does not
  attest native extensions, interpreter memory or the runtime itself.
- count_work counts Python line/call events only for explicitly selected
  functions. It refuses to replace an active trace hook and restores tracing
  if the target raises. C/native work, unselected helpers, other threads and
  I/O are not represented.
- expected_work evaluates a supplied affine model, `intercept + slope * hops`.
  It does not fit or prove that model. Calibrate coefficients on training cases
  and report residuals on held-out cases before drawing conclusions.

## Integration rules

1. The existing verifier remains authoritative. A witness failure can mark
   evidence incomplete, but cannot convert a rejection into acceptance.
2. Compare identity hashes only within the same Python implementation/version
   and compatible environment unless cross-version behavior is tested.
3. Tracing has overhead; enable it only for diagnostic runs, separately from
   production performance measurements.
4. Do not rely on in-process evidence to resist malicious code running with the
   same privileges.
5. The JSON manifest states `authoritative: false` and lists its limitations.
