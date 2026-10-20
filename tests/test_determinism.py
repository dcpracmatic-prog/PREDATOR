from __future__ import annotations

import json
import sys

import pytest

from ztge.determinism import Meter, best_of_k, code_identity, count_work, evidence_manifest, expected_work

_GLOBAL_CONFIG = {"threshold": 3}


def _linear(hops: int) -> int:
    total = 0
    for value in range(hops):
        total += value
    return total


def test_meter_requires_start_and_measures_nonnegative_time():
    with pytest.raises(RuntimeError):
        Meter().stop()
    meter = Meter().start()
    assert sum(range(100)) == 4950
    result = meter.stop()
    assert result.wall_ns >= 0
    assert result.python and result.platform


def test_best_of_k_reports_samples_and_validates_arguments():
    result = best_of_k(lambda x: x * 2, 4, k=3, warmups=1)
    assert result.last_value == 8
    assert len(result.samples_ns) == 3
    assert result.minimum_ns <= result.median_ns <= result.maximum_ns
    for invalid in (True, 0, -1, 1.5):
        with pytest.raises(ValueError):
            best_of_k(lambda: None, k=invalid)
    with pytest.raises(ValueError):
        best_of_k(lambda: None, warmups=True)


def test_identity_changes_when_defaults_and_mutable_globals_change():
    def target(value=2):
        return value + _GLOBAL_CONFIG["threshold"]

    before = code_identity([target])
    target.__defaults__ = (5,)
    changed_default = code_identity([target])
    assert before["sha256"] != changed_default["sha256"]
    _GLOBAL_CONFIG["threshold"] = 9
    changed_global = code_identity([target])
    assert changed_default["sha256"] != changed_global["sha256"]
    _GLOBAL_CONFIG["threshold"] = 3


def test_identity_includes_closure_state():
    def factory(initial):
        value = initial
        def target():
            return value
        return target

    assert code_identity([factory(1)])["sha256"] != code_identity([factory(2)])["sha256"]


def test_identity_marks_uninspectable_objects_incomplete():
    class MutableObject:
        pass
    opaque = MutableObject()
    def target():
        return opaque
    result = code_identity([target])
    assert not result["complete"]
    assert result["opaque_bindings"]


def test_count_work_counts_selected_code_and_returns_value():
    result = count_work(_linear, 8)
    assert result.value == 28
    assert result.calls == 1
    assert result.line_events > 0
    assert sys.gettrace() is None


def test_count_work_does_not_overwrite_existing_trace_hook():
    def existing(frame, event, arg):
        return existing
    sys.settrace(existing)
    try:
        with pytest.raises(RuntimeError):
            count_work(_linear, 2)
        assert sys.gettrace() is existing
    finally:
        sys.settrace(None)


def test_count_work_restores_trace_after_exception():
    def fails():
        raise LookupError("expected")
    with pytest.raises(LookupError):
        count_work(fails)
    assert sys.gettrace() is None


def test_expected_work_rejects_bool_negative_and_nonfinite_inputs():
    assert expected_work(4, intercept=2, slope=3) == 14.0
    for hops in (True, -1, 1.2):
        with pytest.raises(ValueError):
            expected_work(hops, intercept=1, slope=1)
    for value in (True, float("nan"), float("inf"), -1, 10**10000):
        with pytest.raises(ValueError):
            expected_work(1, intercept=value, slope=1)
    with pytest.raises(ValueError):
        expected_work(10**100, intercept=1e308, slope=1e308)


def test_manifest_is_json_safe_and_non_authoritative():
    meter = Meter().start()
    _linear(4)
    measured = meter.stop()
    manifest = evidence_manifest(identity=code_identity([_linear]), measurement=measured, work=count_work(_linear, 4))
    encoded = json.dumps(manifest, allow_nan=False)
    assert '"authoritative": false' in encoded
    assert manifest["work"]["line_events"] > 0
    assert manifest["limitations"]
