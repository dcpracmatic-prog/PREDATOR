from predator import hardware_profile


def test_hardware_profile_reports_repeated_empirical_candidates(monkeypatch):
    monkeypatch.setattr(hardware_profile, "system_profile", lambda: {"logical_cpu_count": 2, "effective_cpu_count_estimate": 2.0, "available_memory_bytes": 64 * 1024 * 1024})
    monkeypatch.setattr(hardware_profile, "morph_status", lambda: {"available": False, "reason": "not built"})
    report = hardware_profile.run_profile([64, 128], [10, 20], seed=7, repeats=3)
    assert report["schema"] == "predator.hardware_profile.v1"
    assert report["calibration"]["tested_sizes"] == [64, 128]
    assert report["calibration"]["repeats"] == 3
    assert len(report["samples"]) == 6
    assert all(row["valid"] for row in report["samples"])
    assert all(row["method"] == "gwmin" for row in report["candidate_recommendations"])
    assert all(row["budget_ms"] is None and row["repeat_count"] == 3 for row in report["candidate_recommendations"])
    assert all("median_solution_size" in row and "median_wall_ms" in row for row in report["candidate_recommendations"])
    assert any("representative real inputs" in note for note in report["notes"])


def test_low_memory_profile_skips_sizes_instead_of_forcing_minimum(monkeypatch):
    monkeypatch.setattr(hardware_profile, "system_profile", lambda: {"available_memory_bytes": 1024})
    monkeypatch.setattr(hardware_profile, "morph_status", lambda: {"available": False})
    report = hardware_profile.run_profile([64], [10], repeats=2)
    assert report["calibration"]["tested_sizes"] == []
    assert report["calibration"]["skipped_sizes_for_memory_estimate"] == [64]
    assert report["samples"] == []
    assert report["candidate_recommendations"] == []


def test_profile_rejects_invalid_repeat_count_and_seed():
    import pytest
    with pytest.raises(ValueError, match="repeats"):
        hardware_profile.run_profile([16], [5], repeats=1)
    with pytest.raises(ValueError, match="seed"):
        hardware_profile.run_profile([16], [5], seed=-1)


def test_profile_graph_generation_is_seeded():
    first = hardware_profile._sparse_graph(32, 99)
    second = hardware_profile._sparse_graph(32, 99)
    assert first.edge_count() == second.edge_count()
    assert first.adj == second.adj


def test_effective_cpu_count_can_report_container_fraction():
    from predator.hardware import effective_cpu_count
    assert effective_cpu_count() is None or effective_cpu_count() > 0
