"""Regression coverage for the CLI's explicit HMAC signing option."""
import json

from clan_subnet_detector.audit.signing import verify_envelope_hmac
from clan_subnet_detector.cli import main


def test_cli_sign_hmac_writes_verifiable_envelope(tmp_path):
    assert main(["--demo", "--method", "gwmin", "--sign-hmac", "cli-secret",
                 "--out", str(tmp_path)]) == 0
    envelope = json.loads((tmp_path / "audit_report.signed.json").read_text())
    assert envelope["payload"]["schema_version"] == "ztge.audit.v1"
    assert envelope["payload"]["engine"]["name"] == "predator"
    assert envelope["producer"]["service"] == "predator"
    assert verify_envelope_hmac(envelope, b"cli-secret") == (True, "ok")
