# Signed audit reports for external auditors

## Documents

| File | Role |
|------|------|
| `schemas/ztge_audit_report.schema.json` | Body schema (`schema_version = ztge.audit.v1`) |
| `schemas/ztge_signed_envelope.schema.json` | Envelope (`envelope_version = ztge.envelope.v1`) |
| `audit_report.json` | Unsigned body with `content_hash` |
| `audit_report.signed.json` | Envelope: payload + integrity |

## Integrity model

1. Build the report body with `content_hash` set to `""`.
2. Canonicalize JSON (UTF-8, sorted keys, separators `,` / `:`).
3. `content_hash = SHA-256(canonical_bytes)` as lowercase hex.
4. Sign the **hex string** of `content_hash`:
   - **HMAC-SHA256** (default B2B shared secret), or
   - **Ed25519** (optional; requires `cryptography`).
5. Ship the envelope. Auditors recompute the hash from `payload` and verify the signature.

### Environment

```bash
export ZTGE_HMAC_SECRET='hex:<64-hex-chars>'   # or raw utf-8 string
# generate one:
python -c 'from clan_subnet_detector.audit import generate_hmac_secret; print(generate_hmac_secret())'
```

### Python API

```python
from clan_subnet_detector.audit import run_audit, write_report, verify_envelope_hmac
from clan_subnet_detector.graph.graph import Graph

g = Graph.from_edges(4, [(0,1),(1,2),(2,3)])
report = run_audit(g, method="auto", budget_ms=50, seed=1)
paths = write_report(report, "out/", sign=True, key_id="hmac:prod-2026-10")

import json
env = json.loads(paths["signed"].read_text())
ok, reason = verify_envelope_hmac(env, secret)
assert ok, reason

# Public-key verification: keep the private key with the signer and distribute
# the corresponding public key to independent auditors.
from clan_subnet_detector.audit import sign_report_ed25519, verify_envelope_ed25519
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

# Demonstration only: in production, load a persistent protected private key.
private_key = Ed25519PrivateKey.generate()
private_pem = private_key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
)
public_pem = private_key.public_key().public_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PublicFormat.SubjectPublicKeyInfo,
)
ed_env = sign_report_ed25519(report.to_v1_dict(), private_pem, key_id="ed25519:prod")
ok, reason = verify_envelope_ed25519(ed_env, public_pem)
assert ok, reason
```

## Stable fields for auditors

- `schema_version`, `report_id`, `timestamp_utc`
- `engine.{name,version,clan_version}`
- `graph.{n,m,density,n_components,digest_sha256?}`
- `findings[]` with `kind`, `nodes`, `size`, `verified`, `score`, `extra`
  - For `independent_set`, `extra.method_requested` / `method_resolved` / `fallback` are required when the planner ran
- `checks` (map of boolean)
- `content_hash`

Re-verification does **not** require trusting the detector: for each finding with
`kind in {clique, independent_set}`, recompute the pure predicate on the
declared `nodes` against the input graph.

## Contracts

YAML contracts under `contracts/` bind detectors, metrics, ingest, and MORPH.
They are the declarative companion to this report schema for SDK/B2B packaging.
