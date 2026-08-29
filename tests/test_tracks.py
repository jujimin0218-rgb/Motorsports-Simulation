"""The shipped circuits: correctness, and genuinely different character.

Project rule 10 requires that circuits demand different things of a car, and
rule 2.3 forbids achieving that with per-track corrections.  The only way to
satisfy both is for the *geometry* to differ, so these tests assert on geometry
-- the raw material a vehicle model will later respond to.
"""

from __future__ import annotations

import math

import pytest

from f1_race_engine.track.curvature import CornerSpeedClass
from f1_race_engine.track.io import builtin_track_names, load_track
from f1_race_engine.track.report import format_track_report, track_report
from f1_race_engine.track.validation import validate_track


def test_every_circuit_is_a_closed_loop(builtin_track):
    turns = builtin_track.total_heading_change / math.tau
    assert abs(turns - round(turns)) < 1e-6
    assert round(turns) != 0


def test_every_circuit_closes_in_plan_view(builtin_track):
    assert builtin_track.centerline().closure_error_fraction < 1e-3


def test_every_circuit_validates_without_warnings(builtin_track):
    report = validate_track(builtin_track)
    assert report.clean, report.format()


def test_every_circuit_has_plausible_dimensions(builtin_track):
    assert 3000.0 < builtin_track.length < 8000.0
    assert builtin_track.corner_count >= 5
    assert builtin_track.sector_count == 3
    assert all(length > 0 for length in builtin_track.sector_lengths())


def test_every_circuit_has_drs_zones(builtin_track):
    assert builtin_track.drs_map is not None
    assert len(builtin_track.drs_map) >= 1
    assert 0.0 < builtin_track.drs_map.coverage < 0.6


def test_elevation_returns_to_its_starting_height(builtin_track):
    start = builtin_track.segments[0].elevation_start
    end = builtin_track.segments[-1].elevation_end
    assert end == pytest.approx(start, abs=1e-6)


def test_proving_ground_exercises_the_whole_model(proving_ground):
    """Phase 1 requires a circuit with straights and corners of every speed."""
    report = track_report(proving_ground)
    mix = report["corners"]["by_speed_class"]
    assert mix["low_speed"] >= 1
    assert mix["medium_speed"] >= 1
    assert mix["high_speed"] >= 1
    # Long enough to matter, expressed against the lap rather than as a round
    # number: Monza's main straight is 19% of its lap and Silverstone's Hangar
    # Straight 13% of its.  A reference circuit needs one the car can reach top
    # speed on, or DRS and the tow have nothing to work with.
    assert report["composition"]["longest_straight"] > 0.12 * proving_ground.length
    assert report["corners"]["by_direction"]["right"] >= 1
    assert report["corners"]["by_direction"]["left"] >= 1
    assert report["elevation"]["range"] > 10.0
    assert report["banking"]["max_deg"] > 1.0
    assert report["banking"]["min_deg"] < -0.5
    assert report["drs"]["zone_count"] >= 2
    # Two surface types and a varying width.
    assert len({s.surface_type for s in proving_ground.segments}) >= 2
    assert report["width"]["max"] - report["width"]["min"] > 1.0


def test_circuits_differ_in_character():
    """Different circuits must ask different questions of a car."""
    power = load_track("synthetic_power_circuit")
    street = load_track("synthetic_street_circuit")

    # The power circuit is longer, faster and far less busy.
    assert power.length > street.length * 1.8
    assert power.longest_straight > street.longest_straight * 2.0
    assert power.min_radius > street.min_radius * 2.5
    assert street.corner_count > power.corner_count

    power_mix = track_report(power)["corners"]["by_speed_class"]
    street_mix = track_report(street)["corners"]["by_speed_class"]
    # What separates them is the fast end, not the slow one.  A power circuit
    # is allowed slow corners -- Monza is the fastest circuit in Formula 1 and
    # the Rettifilo chicane is among the slowest corners on the calendar.  What
    # a street circuit cannot have is anywhere to go quickly.
    assert power_mix["high_speed"] > 0
    assert street_mix["high_speed"] == 0
    assert street_mix["low_speed"] > 0

    # A street circuit is narrower, which will drive overtaking difficulty.
    assert min(s.track_width for s in street.segments) < min(
        s.track_width for s in power.segments
    )


def test_report_contains_every_phase_one_metric(proving_ground):
    report = track_report(proving_ground)
    for key in (
        "length", "corner_count", "geometry", "composition", "corners",
        "sectors", "elevation", "banking", "width", "drs", "resolution",
    ):
        assert key in report
    text = format_track_report(report)
    assert "TRACK REPORT" in text
    assert proving_ground.name in text
    assert "RESOLUTION" in text


def test_report_is_json_serialisable(builtin_track):
    import json

    json.dumps(track_report(builtin_track))


def test_all_expected_circuits_are_shipped():
    assert set(builtin_track_names()) == {
        "synthetic_power_circuit",
        "synthetic_proving_ground",
        "synthetic_street_circuit",
    }
