"""The automatic lap checks (project rules 39, 40, 47)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from f1_race_engine.core.errors import PhysicsValidationError
from f1_race_engine.core.validation import Severity
from f1_race_engine.physics.lap_validation import (
    LAP_CHECKS,
    LapContext,
    check_more_power_gives_a_faster_lap,
    check_profile_respects_the_cornering_limit,
    check_sector_times_add_up,
    validate_lap,
)
from f1_race_engine.environment import AmbientConditions
from f1_race_engine.physics import compute_lap_time
from f1_race_engine.vehicle import MEDIUM_DOWNFORCE, Vehicle


def result_baseline(track, car):
    """A lap to build a check context around, without the zone analysis."""
    return compute_lap_time(track, car, analyse_zones=False)


@pytest.fixture(scope="module")
def report(request):
    from f1_race_engine.core.config import TrackBuildConfig
    from f1_race_engine.track.builder import build_track
    from f1_race_engine.track.io import load_builtin_definition
    from f1_race_engine.vehicle.io import load_builtin_vehicle

    track = build_track(
        load_builtin_definition("synthetic_proving_ground"),
        TrackBuildConfig(
            straight_segment_length=30.0, corner_segment_length=20.0,
            min_segment_length=5.0, max_segment_length=30.0,
            max_heading_change_per_segment_deg=8.0,
            max_curvature_change_per_segment=0.01,
        ),
    )
    car = Vehicle(load_builtin_vehicle("reference_2024"), MEDIUM_DOWNFORCE)
    return validate_lap(track, car), track, car


def test_the_reference_lap_is_clean(report):
    result, _, _ = report
    assert result.clean, result.format()


def test_the_suite_reports_measured_numbers(report):
    result, _, _ = report
    assert result.infos
    checks = {issue.check for issue in result.of_severity(Severity.INFO)}
    assert {"test_c_power", "mass_lap_time", "setup_sensitivity"} <= checks


def test_every_registered_check_runs(report):
    """Each check must run without raising and be reachable from the suite."""
    result, track, car = report
    assert len(LAP_CHECKS) >= 10
    context = LapContext(track, car, AmbientConditions(), result_baseline(track, car))
    for check in LAP_CHECKS:
        check(context)  # must not raise
    reported = {issue.check for issue in result.issues}
    assert len(reported) >= len(LAP_CHECKS) - 3


def test_report_names_the_car_and_circuit(report):
    result, track, car = report
    assert car.name in result.subject
    assert track.name in result.subject


def test_a_broken_profile_is_caught(report):
    """If the profile ever exceeded the cornering limit, the check must fire."""
    _, track, car = report
    lap = result_baseline(track, car)
    broken_profile = replace(
        lap.profile,
        speed=tuple(v * 1.5 for v in lap.profile.speed),
    )
    broken_lap = replace(lap, profile=broken_profile)
    context = LapContext(track, car, AmbientConditions(), broken_lap)
    issues = check_profile_respects_the_cornering_limit(context)
    assert any(issue.severity is Severity.ERROR for issue in issues)


def test_mismatched_sector_times_are_caught(report):
    _, track, car = report
    lap = result_baseline(track, car)
    broken = replace(lap, sector_times=(1.0, 1.0, 1.0))
    context = LapContext(track, car, AmbientConditions(), broken)
    issues = check_sector_times_add_up(context)
    assert any(issue.severity is Severity.ERROR for issue in issues)


def test_test_c_fires_when_power_stops_mattering(report, monkeypatch):
    _, track, car = report
    context = LapContext(track, car, AmbientConditions(), result_baseline(track, car))
    monkeypatch.setattr(
        LapContext, "lap_for", lambda self, vehicle, **kw: self.baseline
    )
    issues = check_more_power_gives_a_faster_lap(context)
    assert any(issue.severity is Severity.ERROR for issue in issues)


def test_report_raises_on_errors(report):
    from f1_race_engine.core.validation import ValidationIssue
    from f1_race_engine.physics.lap_validation import LapReport

    result, _, _ = report
    result.raise_for_errors()
    broken = LapReport("x", (ValidationIssue("c", Severity.ERROR, "no"),))
    with pytest.raises(PhysicsValidationError):
        broken.raise_for_errors()


def test_export_is_json_serialisable(report):
    import json

    result, _, _ = report
    json.dumps(result.to_dict())
