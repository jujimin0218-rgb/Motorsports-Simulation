"""The Track model: distance -> track state (project rule 5)."""

from __future__ import annotations

import math

import pytest

from f1_race_engine.core.errors import TrackError
from f1_race_engine.track.model import Track
from f1_race_engine.track.segment import SegmentKind
from f1_race_engine.track.surface import TrackConditions


def test_distance_wraps_around_the_lap(square_track):
    length = square_track.length
    assert square_track.normalise_distance(length + 100.0) == pytest.approx(100.0)
    assert square_track.normalise_distance(-50.0) == pytest.approx(length - 50.0)
    assert square_track.state_at(length + 100.0).distance == pytest.approx(100.0)


def test_segment_lookup_finds_the_containing_segment(square_track):
    for segment in square_track.segments[::7]:
        assert square_track.segment_at(segment.mid_distance) is segment
        assert square_track.segment_at(segment.distance) is segment


def test_state_is_continuous_in_distance(proving_ground):
    """Physics integrates by distance, so state must not jump between steps."""
    step = 0.25
    previous = proving_ground.state_at(0.0)
    max_jump = 0.0
    distance = step
    while distance < proving_ground.length:
        current = proving_ground.state_at(distance)
        max_jump = max(max_jump, abs(current.curvature - previous.curvature))
        previous = current
        distance += step
    # 0.25 m at the tightest transition rate is a tiny curvature change.
    assert max_jump < 1e-3


def test_curvature_interpolates_within_a_segment(square_track):
    segment = next(s for s in square_track.segments if s.kind is SegmentKind.CORNER_ENTRY)
    start = square_track.state_at(segment.distance).curvature
    end = square_track.state_at(segment.end_distance - 1e-9).curvature
    middle = square_track.state_at(segment.mid_distance).curvature
    assert start != end
    assert middle == pytest.approx(0.5 * (segment.curvature_start + segment.curvature_end), rel=1e-6)


def test_forward_distance_and_gaps(square_track):
    length = square_track.length
    assert square_track.forward_distance(100.0, 300.0) == pytest.approx(200.0)
    assert square_track.forward_distance(300.0, 100.0) == pytest.approx(length - 200.0)
    assert square_track.gap_distance(ahead=300.0, behind=100.0) == pytest.approx(200.0)


def test_sector_ranges_tile_the_lap(square_track):
    ranges = square_track.sector_ranges()
    assert ranges[0][0] == 0.0
    assert ranges[-1][1] == pytest.approx(square_track.length)
    assert math.fsum(square_track.sector_lengths()) == pytest.approx(square_track.length)


def test_corner_summary(square_track):
    corners = square_track.corners
    assert set(corners) == {1, 2, 3, 4}
    for corner in corners.values():
        assert float(corner["min_radius"]) == pytest.approx(80.0, rel=1e-6)
        assert math.degrees(float(corner["turn_angle"])) == pytest.approx(90.0, abs=1e-6)
        assert corner["direction"] == "left"


def test_straight_sections_and_longest_straight(square_track):
    sections = square_track.straight_sections(min_length=100.0)
    assert len(sections) == 4
    assert square_track.longest_straight == pytest.approx(500.0, abs=1.0)


def test_direction_of_travel():
    from f1_race_engine.track.builder import build_track
    from f1_race_engine.track.definitions import (
        CornerDefinition,
        CornerDirection,
        SectorDefinition,
        StraightDefinition,
        TrackDefinition,
    )

    clockwise = build_track(
        TrackDefinition(
            name="cw",
            layout=(
                StraightDefinition(500.0),
                CornerDefinition(80.0, 180.0, CornerDirection.RIGHT, corner_id=1),
                StraightDefinition(500.0),
                CornerDefinition(80.0, 180.0, CornerDirection.RIGHT, corner_id=2),
            ),
            sectors=SectorDefinition(boundaries=(400.0, 800.0)),
        )
    )
    assert clockwise.is_clockwise
    assert clockwise.turn_count == pytest.approx(-1.0, abs=1e-9)


def test_conditions_modify_grip_without_touching_the_track(proving_ground):
    """Session state lives beside the track, never inside it."""
    conditions = TrackConditions(proving_ground.segments)
    dry = proving_ground.state_at(2600.0, conditions)
    static = proving_ground.state_at(2600.0)
    assert dry.grip == pytest.approx(static.grip)

    index = proving_ground.segment_index_at(2600.0)
    conditions[index].water_depth = 0.005
    wet = proving_ground.state_at(2600.0, conditions)
    assert wet.grip < static.grip
    assert wet.is_wet
    # The track itself is untouched, so other sessions are unaffected.
    assert proving_ground.state_at(2600.0).grip == pytest.approx(static.grip)

    conditions.reset()
    assert proving_ground.state_at(2600.0, conditions).grip == pytest.approx(static.grip)


def test_rubbering_in_raises_grip(proving_ground):
    conditions = TrackConditions(proving_ground.segments)
    index = proving_ground.segment_index_at(500.0)
    baseline = proving_ground.state_at(500.0, conditions).grip
    conditions[index].rubber = 1.0
    assert proving_ground.state_at(500.0, conditions).grip > baseline


def test_track_export(proving_ground):
    payload = proving_ground.to_dict()
    assert payload["corner_count"] == proving_ground.corner_count
    assert payload["resolution"]["segments"] == len(proving_ground)
    assert len(payload["drs_zones"]) == len(proving_ground.drs_map)


def test_empty_track_is_rejected():
    with pytest.raises(TrackError):
        Track(name="empty", segments=(), length=100.0)


def test_track_is_iterable_and_indexable(square_track):
    assert len(list(square_track)) == len(square_track)
    assert square_track[0] is square_track.segments[0]


def test_state_at_is_json_serialisable(proving_ground):
    import json

    json.dumps(proving_ground.state_at(1234.5).to_dict())
