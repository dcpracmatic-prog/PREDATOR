from __future__ import annotations

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from clan_subnet_detector.audit.schema import validate_report
from clan_subnet_detector.audit.signing import (
    ed25519_verify,
    hmac_verify,
    sign_report_ed25519,
    sign_report_hmac,
    verify_envelope_ed25519,
    verify_envelope_hmac,
)
from clan_subnet_detector.detection.independent_set import gwmin_independent, is_independent
from clan_subnet_detector.graph.graph import Graph
from clan_subnet_detector.graph.metrics import density


def test_hmac_envelope_detects_payload_tampering():
    envelope = sign_report_hmac({"schema_version": "ztge.audit.v1", "value": 7}, b"test-secret")
    assert verify_envelope_hmac(envelope, b"test-secret") == (True, "ok")

    tampered = {**envelope, "payload": {**envelope["payload"], "value": 8}}
    ok, reason = verify_envelope_hmac(tampered, b"test-secret")
    assert not ok
    assert reason == "content_hash mismatch"


def test_ed25519_envelope_round_trip_and_tamper_detection():
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
    envelope = sign_report_ed25519({"schema_version": "ztge.audit.v1", "value": 11}, private_pem)
    assert verify_envelope_ed25519(envelope, public_pem) == (True, "ok")

    tampered = {**envelope, "payload": {**envelope["payload"], "value": 12}}
    ok, reason = verify_envelope_ed25519(tampered, public_pem)
    assert not ok
    assert reason == "content_hash mismatch"


def test_ed25519_verifier_rejects_malformed_signature_without_raising():
    private_key = Ed25519PrivateKey.generate()
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    assert ed25519_verify("abcd", "not-hex", public_pem) is False


def test_independent_set_rejects_self_loop_and_greedy_skips_looped_vertex():
    graph = Graph.from_edges(3, [(0, 0), (1, 2)])
    assert not is_independent(graph, [0])
    assert graph.edge_count() == 2
    assert density(graph) == 1 / 3
    result = gwmin_independent(graph)
    assert 0 not in result
    assert is_independent(graph, result)


def test_induced_subgraph_preserves_undirected_edge_weight():
    graph = Graph.from_edges(3, [(0, 1, 2.5), (1, 2, 4.0)])
    subgraph = graph.induced_subgraph([0, 1, 2])
    assert subgraph.adj[0][1] == 2.5
    assert subgraph.adj[1][0] == 2.5
    assert subgraph.adj[1][2] == 4.0
    assert subgraph.adj[2][1] == 4.0

def test_signed_envelope_verifiers_fail_closed_on_malformed_shapes_and_non_json_values():
    private_key = Ed25519PrivateKey.generate()
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    malformed = [
        None,
        [],
        {"envelope_version": "ztge.envelope.v1", "payload": {}, "integrity": []},
        {
            "envelope_version": "ztge.envelope.v1",
            "payload": {"value": float("nan")},
            "integrity": {"alg": "HMAC-SHA256", "signature": "x", "content_hash": "x"},
        },
        {
            "envelope_version": "ztge.envelope.v1",
            "payload": {"value": float("inf")},
            "integrity": {"alg": "Ed25519", "signature": "x", "content_hash": "x"},
        },
    ]
    for envelope in malformed:
        assert verify_envelope_hmac(envelope, b"test-secret")[0] is False
        assert verify_envelope_ed25519(envelope, public_pem)[0] is False


def test_crypto_verifiers_reject_malformed_keys_and_secret_types_without_crashing():
    assert hmac_verify("abcd", "00", "not-bytes") is False
    assert ed25519_verify("abcd", "00", b"not-a-public-key") is False


def test_historical_ztge_payload_remains_cryptographically_verifiable():
    # Historical reports retain the signature over their original bytes; the
    # current schema validator intentionally checks the new PREDATOR identity.
    historical = {
        "schema_version": "ztge.audit.v1",
        "report_id": "legacy-001",
        "timestamp_utc": "2024-01-01T00:00:00Z",
        "engine": {"name": "clan_subnet_detector", "version": "0.1.0"},
        "graph": {"n": 1, "m": 0, "density": 0, "n_components": 1},
        "findings": [], "checks": {}, "content_hash": "",
    }
    envelope = sign_report_hmac(historical, b"legacy-secret", producer={"service": "clan_subnet_detector"})
    assert verify_envelope_hmac(envelope, b"legacy-secret") == (True, "ok")
    assert validate_report(envelope["payload"])[0] is False


def test_hmac_verifier_rejects_bad_signature_missing_key_and_unsupported_algorithm():
    envelope = sign_report_hmac({"schema_version": "ztge.audit.v1", "value": 3}, b"right")
    bad_signature = {**envelope, "integrity": {**envelope["integrity"], "signature": "00"}}
    assert verify_envelope_hmac(bad_signature, b"right")[0] is False
    assert verify_envelope_hmac(envelope, b"wrong")[0] is False
    missing_integrity = {**envelope}; missing_integrity.pop("integrity")
    assert verify_envelope_hmac(missing_integrity, b"right")[0] is False
    unsupported = {**envelope, "integrity": {**envelope["integrity"], "alg": "UNKNOWN"}}
    ok, reason = verify_envelope_hmac(unsupported, b"right")
    assert not ok and "unexpected alg" in reason
