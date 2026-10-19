"""Signing and integrity helpers for ZTGE audit reports.

Canonicalization is deterministic (sorted keys, compact separators, UTF-8).
Primary integrity mechanism for B2B delivery:

* SHA-256 content hash of the canonical payload
* HMAC-SHA256 over the content hash (shared secret with auditor), or
* Ed25519 over the content hash (when ``cryptography`` is installed)

The envelope schema is ``schemas/ztge_signed_envelope.schema.json``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional, Tuple

SCHEMA_VERSION = "ztge.audit.v1"
ENVELOPE_VERSION = "ztge.envelope.v1"


def canonical_json(obj: Any) -> bytes:
    """RFC-8785-inspired canonical JSON: sorted keys, no insignificant whitespace."""
    return json.dumps(
        obj,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def content_hash_for_report(report: Mapping[str, Any]) -> str:
    """Hash of the report with ``content_hash`` forced to empty before hashing."""
    body = dict(report)
    body["content_hash"] = ""
    return sha256_hex(canonical_json(body))


def attach_content_hash(report: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy of *report* with a correct ``content_hash`` field."""
    out = dict(report)
    out["content_hash"] = content_hash_for_report(out)
    return out


def hmac_sign(content_hash: str, secret: bytes, *, key_id: str) -> Dict[str, Any]:
    sig = hmac.new(secret, content_hash.encode("ascii"), hashlib.sha256).hexdigest()
    return {
        "alg": "HMAC-SHA256",
        "content_hash": content_hash,
        "signature": sig,
        "key_id": key_id,
        "signed_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def hmac_verify(content_hash: str, signature: str, secret: bytes) -> bool:
    expected = hmac.new(secret, content_hash.encode("ascii"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def ed25519_sign(content_hash: str, private_key_pem: bytes, *, key_id: str) -> Dict[str, Any]:
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "Ed25519 signing requires the 'cryptography' package"
        ) from e
    key = serialization.load_pem_private_key(private_key_pem, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise TypeError("PEM is not an Ed25519 private key")
    sig = key.sign(content_hash.encode("ascii")).hex()
    return {
        "alg": "Ed25519",
        "content_hash": content_hash,
        "signature": sig,
        "key_id": key_id,
        "signed_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def ed25519_verify(content_hash: str, signature: str, public_key_pem: bytes) -> bool:
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "Ed25519 verify requires the 'cryptography' package"
        ) from e
    key = serialization.load_pem_public_key(public_key_pem)
    if not isinstance(key, Ed25519PublicKey):
        raise TypeError("PEM is not an Ed25519 public key")
    try:
        key.verify(bytes.fromhex(signature), content_hash.encode("ascii"))
        return True
    except Exception:
        return False


def wrap_envelope(
    payload: Mapping[str, Any],
    integrity: Mapping[str, Any],
    *,
    producer: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    env: Dict[str, Any] = {
        "envelope_version": ENVELOPE_VERSION,
        "payload": dict(payload),
        "integrity": dict(integrity),
    }
    if producer:
        env["producer"] = dict(producer)
    return env


def sign_report_hmac(
    report: Mapping[str, Any],
    secret: bytes,
    *,
    key_id: str = "hmac:default",
    producer: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    """Attach content_hash and return a signed envelope (HMAC-SHA256)."""
    payload = attach_content_hash(dict(report))
    integrity = hmac_sign(payload["content_hash"], secret, key_id=key_id)
    return wrap_envelope(payload, integrity, producer=producer)


def verify_envelope_hmac(envelope: Mapping[str, Any], secret: bytes) -> Tuple[bool, str]:
    """Verify HMAC envelope. Returns (ok, reason)."""
    if envelope.get("envelope_version") != ENVELOPE_VERSION:
        return False, "unsupported envelope_version"
    payload = envelope.get("payload")
    integrity = envelope.get("integrity") or {}
    if not isinstance(payload, dict):
        return False, "missing payload"
    alg = integrity.get("alg")
    if alg != "HMAC-SHA256":
        return False, f"unexpected alg {alg}"
    expected_hash = content_hash_for_report(payload)
    if integrity.get("content_hash") != expected_hash:
        return False, "content_hash mismatch"
    if payload.get("content_hash") != expected_hash:
        return False, "payload content_hash field mismatch"
    if not hmac_verify(expected_hash, str(integrity.get("signature", "")), secret):
        return False, "signature invalid"
    return True, "ok"


def secret_from_env(var: str = "ZTGE_HMAC_SECRET") -> Optional[bytes]:
    """Load HMAC secret from env (raw string or hex: prefix)."""
    raw = os.environ.get(var)
    if not raw:
        return None
    if raw.startswith("hex:"):
        return bytes.fromhex(raw[4:])
    return raw.encode("utf-8")


def generate_hmac_secret() -> str:
    """Return a hex-encoded 32-byte secret suitable for ZTGE_HMAC_SECRET=hex:..."""
    return "hex:" + secrets.token_hex(32)
