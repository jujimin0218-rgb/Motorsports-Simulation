"""Validation must catch broken geometry -- and only broken geometry.

Two halves matter equally.  A check that never fires is decoration; a check
that fires on a good circuit is worse, because it trains everyone to ignore the
report.  So every check is tested against a deliberately broken track *and*
against the shipped circuits.
"""

from __future__ import annotations

import math
from dataclasses import replace

import pytest

from f1_race_engine.core.config import TrackValidationConfig
from f1_race_engine.core.errors import TrackValidationError
from f1_race_engine.track.builder import build_track
from f1_race_engine.track.definitions import (
    CornerDefinition,
    CornerDirection,
    ElevationDefinition,
    SectorDefinition,
    StraightDefinition,
    TrackDefinition,
)
from f1_race_engine.track.drs import DrsMap, DrsZone
from f1_race_engine.track.model import Track
from f1_race_engine.track.validation import (
    Severity,
    ValidationIssue,
    ValidationReport,
    check_curvature_continuity,
    check_curvature_spikes,
    check_distance_continuity,
    check_drs_zones,
    check_elevation,
    check_heading_closure,
    check_sectors,
    check_surface_grip,
    check_track_width,
    validate_track,
)


def _codes(report: ValidationReport, severity: Severity | None = None) -> set[str]:
    issues = report.issues if severity is None else report.of_severity(severity)
    return {issue.check for issue in issues}


# -- the good case -----------------------------------------------------------


def test_shipped_circuits_validate_cleanly(builtin_track):
    report = validate_track(builtin_track)
    assert report.ok, report.format()
    assert not report.warnings, report.format()


def test_a_clean_report_raises_nothing(square_track):
    assert validate_track(square_track).raise_for_errors().ok


# -- broken geometry ---------------------------------------------------------


def test_curvature_discontinuity_is_caught(square_track):
    """A corner without a transition is a step change in curvature."""
    broken = list(square_track.segments)
    broken[50] = replace(broken[50], curvature_start=0.05, curvature_end=0.05)
    track = replace(square_track, segments=tuple(broken))
    issues = check_curvature_continuity(track, TrackValidationConfig())
    assert issues and all(i.severity is Severity.ERROR for i in issues)
    assert "curvature jumps" in issues[0].message


def test_distance_gap_is_caught(square_track):
    broken = list(square_track.segments)
    broken[20] = replace(broken[20], distance=broken[20].distance + 5.0)
    track = replace(square_track, segments=tuple(broken))
    issues = check_distance_continuity(track, TrackValidationConfig())
    assert any("gap" in i.message or "overlap" in i.message for i in issues)


def test_layout_that_does_not_close_is_caught():
    """Turning through 270 degrees never returns to the start/finish line."""
    definition = TrackDefinition(
        name="open",
        layout=(
            StraightDefinition(500.0),
            CornerDefinition(80.0, 90.0, CornerDirection.LEFT, corner_id=1),
            StraightDefinition(500.0),
            CornerDefinition(80.0, 90.0, CornerDirection.LEFT, corner_id=2),
            StraightDefinition(500.0),
            CornerDefinition(80.0, 90.0, CornerDirection.LEFT, corner_id=3),
            StraightDefinition(500.0),
        ),
        sectors=SectorDefinition(boundaries=(500.0, 1000.0)),
    )
    report = validate_track(build_track(definition))
    assert not report.ok
    assert "heading_closure" in _codes(report, Severity.ERROR)


def test_position_closure_failure_is_caught():
    """Right turning angles, wrong straight lengths: the loop misses itself."""
    definition = TrackDefinition(
        name="lopsided",
        layout=(
            StraightDefinition(2000.0),
            CornerDefinition(80.0, 90.0, CornerDirection.LEFT, corner_id=1),
            StraightDefinition(100.0),
            CornerDefinition(80.0, 90.0, CornerDirection.LEFT, corner_id=2),
            StraightDefinition(200.0),
            CornerDefinition(80.0, 90.0, CornerDirection.LEFT, corner_id=3),
            StraightDefinition(100.0),
            CornerDefinition(80.0, 90.0, CornerDirection.LEFT, corner_id=4),
        ),
        sectors=SectorDefinition(boundaries=(800.0, 1600.0)),
    )
    report = validate_track(build_track(definition))
    assert "position_closure" in _codes(report, Severity.ERROR)


def test_impossible_gradient_is_caught():
    definition = TrackDefinition(
        name="cliff",
        layout=(
            StraightDefinition(500.0),
            CornerDefinition(80.0, 180.0, CornerDirection.LEFT, corner_id=1),
            StraightDefinition(500.0),
            CornerDefinition(80.0, 180.0, CornerDirection.LEFT, corner_id=2),
        ),
        elevation=ElevationDefinition(control_points=((0.0, 0.0), (300.0, 250.0))),
        sectors=SectorDefinition(boundaries=(400.0, 800.0)),
    )
    report = validate_track(build_track(definition))
    assert "elevation" in _codes(report, Severity.ERROR)


def test_elevation_that_does_not_close_is_caught(square_track):
    broken = list(square_track.segments)
    broken[-1] = replace(broken[-1], elevation_end=25.0)
    track = replace(square_track, segments=tuple(broken), elevation_profile=None)
    issues = check_elevation(track, TrackValidationConfig())
    assert any("does not close" in i.message for i in issues)


def test_too_tight_a_corner_is_caught():
    definition = TrackDefinition(
        name="impossible",
        layout=(
            StraightDefinition(500.0),
            CornerDefinition(3.0, 180.0, CornerDirection.LEFT, corner_id=1),
            StraightDefinition(500.0),
            CornerDefinition(3.0, 180.0, CornerDirection.LEFT, corner_id=2),
        ),
        sectors=SectorDefinition(boundaries=(400.0, 800.0)),
    )
    report = validate_track(build_track(definition))
    assert "curvature_magnitude" in _codes(report, Severity.ERROR)


def test_tight_but_possible_corner_only_warns():
    definition = TrackDefinition(
        name="hairpin",
        layout=(
            StraightDefinition(700.0),
            CornerDefinition(8.5, 180.0, CornerDirection.LEFT, corner_id=1),
            StraightDefinition(700.0),
            CornerDefinition(8.5, 180.0, CornerDirection.LEFT, corner_id=2),
        ),
        sectors=SectorDefinition(boundaries=(500.0, 1000.0)),
    )
    report = validate_track(build_track(definition))
    assert "curvature_magnitude" in _codes(report, Severity.WARNING)
    assert "curvature_magnitude" not in _codes(report, Severity.ERROR)


def test_isolated_curvature_spike_is_caught(square_track):
    """The check that matters for imported, noisy telemetry."""
    broken = list(square_track.segments)
    target = broken[5]
    broken[5] = replace(target, curvature_start=0.0, curvature_end=0.3)
    track = replace(square_track, segments=tuple(broken))
    issues = check_curvature_spikes(track, TrackValidationConfig())
    assert issues and issues[0].segment_index == 5


def test_a_genuine_transition_is_not_reported_as_a_spike(proving_ground):
    assert check_curvature_spikes(proving_ground, TrackValidationConfig()) == []


def test_out_of_range_width_and_grip_are_caught(square_track):
    broken = list(square_track.segments)
    broken[0] = replace(broken[0], track_width=100.0, surface_grip=9.0)
    track = replace(square_track, segments=tuple(broken))
    assert check_track_width(track, TrackValidationConfig())
    assert check_surface_grip(track, TrackValidationConfig())


def test_missing_sectors_are_caught(square_definition):
    definition = replace(square_definition, sectors=SectorDefinition(boundaries=()))
    report = validate_track(build_track(definition))
    assert "sectors" in _codes(report, Severity.ERROR)


def test_sectors_can_be_optional():
    config = TrackValidationConfig(require_sectors=False)
    track = build_track(
        TrackDefinition(
            name="x",
            layout=(
                StraightDefinition(500.0),
                CornerDefinition(80.0, 180.0, CornerDirection.LEFT, corner_id=1),
                StraightDefinition(500.0),
                CornerDefinition(80.0, 180.0, CornerDirection.LEFT, corner_id=2),
            ),
        )
    )
    assert check_sectors(track, config) == []


def test_overlapping_drs_zones_are_caught(square_track):
    track = replace(
        square_track,
        drs_map=DrsMap(
            [DrsZone(0, 10.0, 100.0, 400.0), DrsZone(1, 200.0, 300.0, 600.0)],
            square_track.length,
        ),
    )
    issues = check_drs_zones(track, TrackValidationConfig())
    assert any("overlap" in i.message for i in issues)


def test_drs_zone_outside_the_lap_is_caught(square_track):
    track = replace(
        square_track,
        drs_map=DrsMap([DrsZone(0, 10.0, 100.0, 99_000.0)], square_track.length),
    )
    issues = check_drs_zones(track, TrackValidationConfig())
    assert any("outside the lap" in i.message for i in issues)


def test_drs_zone_requires_a_forward_activation():
    with pytest.raises(Exception):
        DrsZone(0, 10.0, 400.0, 100.0)


def test_duplicate_corner_ids_are_caught(square_definition):
    """The same corner id in two places would confuse every consumer."""
    layout = list(square_definition.layout)
    layout[3] = replace(layout[3], corner_id=1)
    report = validate_track(build_track(replace(square_definition, layout=tuple(layout))))
    assert "corner_continuity" in _codes(report, Severity.ERROR)


# -- the report itself -------------------------------------------------------


def test_report_raises_only_on_errors():
    warning_only = ValidationReport(
        "t", (ValidationIssue("c", Severity.WARNING, "careful"),)
    )
    assert warning_only.ok
    assert not warning_only.clean
    warning_only.raise_for_errors()

    with pytest.raises(TrackValidationError):
        ValidationReport("t", (ValidationIssue("c", Severity.ERROR, "broken"),)).raise_for_errors()


def test_raised_error_carries_the_report():
    report = ValidationReport("t", (ValidationIssue("c", Severity.ERROR, "broken"),))
    with pytest.raises(TrackValidationError) as info:
        report.raise_for_errors()
    assert info.value.report is report


def test_report_formatting_and_export(proving_ground):
    report = validate_track(proving_ground)
    text = report.format()
    assert proving_ground.name in text
    assert "0 error(s)" in text
    assert report.format(min_severity=Severity.ERROR).endswith("(nothing to report)")
    payload = report.to_dict()
    assert payload["ok"] is True
    assert isinstance(payload["issues"], list)


def test_custom_check_list_is_honoured(square_track):
    report = validate_track(square_track, checks=[check_heading_closure])
    assert _codes(report) == {"heading_closure"}


def test_figure_of_eight_closes_at_no_net_turning():
    """A lap that crosses itself turns nowhere in total, and that is a lap.

    Two tangent loops, one each way: the plan view comes back to the start
    exactly, and the heading does too, having made no net turn at all.  This is
    Suzuka's shape, and the check has to accept it -- the thing that proves a
    lap closes is where it ends up, which ``check_position_closure`` measures.
    """
    definition = TrackDefinition(
        name="figure of eight",
        layout=(
            CornerDefinition(120.0, 360.0, CornerDirection.RIGHT, corner_id=1),
            CornerDefinition(120.0, 360.0, CornerDirection.LEFT, corner_id=2),
        ),
        sectors=SectorDefinition(boundaries=(250.0, 500.0)),
    )
    report = validate_track(build_track(definition), checks=[check_heading_closure])
    assert not _codes(report, Severity.ERROR)
    assert "figure of eight" in report.format()


def test_real_suzuka_is_a_figure_of_eight_and_validates():
    """The recovered Suzuka is the case this exists for, end to end."""
    from f1_race_engine.track.io import load_track

    track = load_track("suzuka")
    assert abs(math.degrees(track.total_heading_change)) < 1.0
    assert validate_track(track).ok
