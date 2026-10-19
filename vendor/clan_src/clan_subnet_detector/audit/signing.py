"""Detachable signatures for AuditReport.

Produces a canonical JSON payload and a signature envelope that can be
verified offline. Prefer ECDSA (cryptography library) when available;
otherwise fall back to HMAC-SHA256 with an explicit shared secret.

This is intentionally aligned with the spirit of ChannelGuardian /
TDCP policy bindings: the report becomes a verifiable artefact, not
just a log file.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from .report import AuditReport


def canonical_payload(report: AuditReport) -> bytes:
    """Deterministic UTF-8 JSON of the report (sorted keys, no whitespace)."""
    data = report.to_dict()
    text = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return text.encode("utf-8")


def payload_digest(report: AuditReport) -> str:
    return hashlib.sha256(canonical_payload(report)).hexdigest()


@dataclass
class SignedAudit:
    """Envelope: payload digest + signature + metadata."""
    alg: str
    digest_sha256: str
    signature_hex: str
    signed_at_utc: str
    kid: str
    report: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "alg": self.alg,
            "digest_sha256": self.digest_sha256,
            "signature_hex": self.signature_hex,
            "signed_at_utc": self.signed_at_utc,
            "kid": self.kid,
            "report": self.report,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


def sign_report_hmac(
    report: AuditReport,
    secret: bytes,
    kid: str = "hmac-default",
) -> SignedAudit:
    """HMAC-SHA256 signature over the canonical payload."""
    payload = canonical_payload(report)
    digest = hashlib.sha256(payload).hexdigest()
    sig = hmac.new(secret, payload, hashlib.sha256).hexdigest()
    return SignedAudit(
        alg="HMAC-SHA256",
        digest_sha256=digest,
        signature_hex=sig,
        signed_at_utc=datetime.now(timezone.utc).isoformat(),
        kid=kid,
        report=report.to_dict(),
    )


def verify_report_hmac(signed: SignedAudit, secret: bytes) -> bool:
    """Verify HMAC and that the embedded report matches the digest."""
    # rebuild payload from embedded report
    text = json.dumps(signed.report, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    payload = text.encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    if not hmac.compare_digest(digest, signed.digest_sha256):
        return False
    expected = hmac.new(secret, payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signed.signature_hex)


def sign_report_ecdsa(
    report: AuditReport,
    private_key_pem: bytes,
    kid: str = "ecdsa-default",
) -> SignedAudit:
    """ECDSA-SHA256 (SECP256R1) when the cryptography package is installed."""
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
    except ImportError as e:
        raise ImportError(
            "cryptography package required for ECDSA signing; use sign_report_hmac instead"
        ) from e

    key = serialization.load_pem_private_key(private_key_pem, password=None)
    if not isinstance(key, ec.EllipticCurvePrivateKey):
        raise TypeError("private key must be an EC key")
    payload = canonical_payload(report)
    digest = hashlib.sha256(payload).hexdigest()
    sig = key.sign(payload, ec.ECDSA(hashes.SHA256()))
    return SignedAudit(
        alg="ECDSA-SHA256-SECP256R1",
        digest_sha256=digest,
        signature_hex=sig.hex(),
        signed_at_utc=datetime.now(timezone.utc).isoformat(),
        kid=kid,
        report=report.to_dict(),
    )


def verify_report_ecdsa(signed: SignedAudit, public_key_pem: bytes) -> bool:
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.exceptions import InvalidSignature
    except ImportError:
        return False
    key = serialization.load_pem_public_key(public_key_pem)
    if not isinstance(key, ec.EllipticCurvePublicKey):
        return False
    text = json.dumps(signed.report, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    payload = text.encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    if not hmac.compare_digest(digest, signed.digest_sha256):
        return False
    try:
        key.verify(bytes.fromhex(signed.signature_hex), payload, ec.ECDSA(hashes.SHA256()))
        return True
    except InvalidSignature:
        return False
