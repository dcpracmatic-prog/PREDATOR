"""Audit reports and cryptographic envelopes for external auditors."""

from .report import AuditReport, Finding, run_audit, write_report
from .schema import SCHEMA_VERSION, validate_report
from .signing import (
    attach_content_hash,
    generate_hmac_secret,
    sign_report_hmac,
    verify_envelope_hmac,
)

__all__ = [
    "AuditReport",
    "Finding",
    "run_audit",
    "write_report",
    "SCHEMA_VERSION",
    "validate_report",
    "attach_content_hash",
    "generate_hmac_secret",
    "sign_report_hmac",
    "verify_envelope_hmac",
]
