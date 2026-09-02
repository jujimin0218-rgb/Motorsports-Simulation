"""The builder must turn definitions into a correctly tiled, continuous track."""

from __future__ import annotations

import math

import pytest

from f1_race_engine.core.config import TrackBuildConfig
from f1_race_engine.core.errors import TrackBuildError
from f1_race_engine.track.builder import TrackBuilder, build_track
from f1_race_engine.track.definitions import (
    BankingDefinition,
    CornerDefinition,
    CornerDirection,
    DrsDefinition,
    ElevationDefinition,
    KerbDefinition,
    KerbRegion,
    SectorDefinition,
    StraightDefinition,
    SurfaceDefinition,
    SurfaceRegionDefinition,
    TrackDefinition,
    WidthDefinition,
)
from f1_race_engine.track.drs import DrsZone
from f1_race_engine.track.segment import KerbType, SegmentKind, SurfaceType


def test_segments_tile_the_lap_exactly(square_track):
    assert square_track.segments[0].distance == 0.0
    for previous, current in zip(square_track.segments, square_track.segments[1:]):
        assert current.distance == pytest.approx(previous.end_distance, abs=1e-9)
    assert square_track.segments[-1].end_distance == pytest.approx(square_track.length)
    assert math.fsum(square_track.segment_lengths) == pytest.approx(square_track.length)


def test_built_length_matches_the_definition(square_definition, square_track):
    assert square_track.length == pytest.approx(square_definition.lap_length)


def test_curvature_is_continuous_everywhere(square_track):
    for previous, current in zip(square_track.segments, square_track.segments[1:]):
        assert current.curvature_start == pytest.approx(previous.curvature_end, abs=1e-12)
    # Including across the start/finish line.
    assert square_track.segments[0].curvature_start == pytest.approx(
        square_track.segments[-1].curvature_end, abs=1e-12
    )


def test_total_turning_is_exact(square_track):
    assert square_track.total_heading_change == pytest.approx(math.tau, abs=1e-12)
    assert square_track.turn_count == pytest.approx(1.0, abs=1e-12)


def test_corners_produce_entry_arc_and_exit_segments(square_track):
    kinds = {s.kind for s in square_track.segments if s.corner_id == 1}
    assert kinds == {
        SegmentKind.CORNER_ENTRY,
        SegmentKind.CORNER,
        SegmentKind.CORNER_EXIT,
    }


def test_transition_curvature_ramps_from_zero_to_the_corner_value(square_track):
    entries = [
        s
        for s in square_track.segments
        if s.corner_id == 1 and s.kind is SegmentKind.CORNER_ENTRY
    ]
    assert entries[0].curvature_start == pytest.approx(0.0, abs=1e-12)
    assert entries[-1].curvature_end == pytest.approx(1.0 / 80.0, rel=1e-9)
    # Monotone ramp, no jumps.
    values = [s.curvature_start for s in entries]
    assert all(b >= a for a, b in zip(values, values[1:]))


def test_resolution_is_adaptive(proving_ground):
    """Straights are sampled coarsely and corners finely -- project rule 7."""
    straight_lengths = [s.length for s in proving_ground.segments if s.is_straight]
    corner_lengths = [s.length for s in proving_ground.segments if s.is_corner]
    assert min(straight_lengths) >= max(corner_lengths) - 1e-9
    # The hairpin gets metre-scale resolution without anyone asking.
    hairpin = [s.length for s in proving_ground.segments if s.corner_radius < 30.0]
    assert min(hairpin) < 2.0


def test_segment_length_floor_is_respected():
    definition = TrackDefinition(
        name="tight",
        layout=(
            StraightDefinition(200.0),
            CornerDefinition(15.0, 180.0, CornerDirection.LEFT, corner_id=1),
            StraightDefinition(200.0),
            CornerDefinition(15.0, 180.0, CornerDirection.LEFT, corner_id=2),
        ),
    )
    for floor in (0.5, 1.0, 2.0):
        track = build_track(
            definition,
            TrackBuildConfig(min_segment_length=floor, corner_segment_length=floor),
        )
        assert min(track.segment_lengths) >= floor - 1e-9


def test_one_metre_resolution_is_reachable(proving_ground_definition):
    """Project rule 7 requires that 1 m resolution be supported."""
    config = TrackBuildConfig(
        straight_segment_length=1.0,
        corner_segment_length=1.0,
        min_segment_length=1.0,
        max_segment_length=1.0,
    )
    track = build_track(proving_ground_definition, config)
    assert max(track.segment_lengths) <= 1.1
    assert len(track) > 4000


def test_overlays_are_sampled_onto_segments():
    lap = 1000.0 + 80.0 * math.pi / 2 + 20.0
    definition = TrackDefinition(
        name="overlays",
        layout=(
            StraightDefinition(500.0),
            CornerDefinition(80.0, 90.0, CornerDirection.LEFT, corner_id=1),
            StraightDefinition(500.0),
        ),
        surface=SurfaceDefinition(
            regions=(
                SurfaceRegionDefinition(
                    0.0, 200.0, SurfaceType.CONCRETE, grip=0.8, roughness=0.9
                ),
            )
        ),
        width=WidthDefinition(control_points=((0.0, 12.0), (400.0, 18.0))),
        kerbs=KerbDefinition(regions=(KerbRegion(500.0, 600.0, KerbType.HIGH),)),
        drs=DrsDefinition(zones=(DrsZone(0, 900.0, 20.0, 300.0, "main"),)),
        sectors=SectorDefinition(boundaries=(400.0, 800.0)),
    )
    track = build_track(definition)

    assert track.state_at(100.0).surface_type is SurfaceType.CONCRETE
    assert track.state_at(100.0).grip == pytest.approx(0.8)
    assert track.state_at(300.0).surface_type is SurfaceType.ASPHALT
    assert track.state_at(100.0).track_width == pytest.approx(13.5, abs=0.5)
    assert track.state_at(550.0).kerb is KerbType.HIGH
    assert track.state_at(100.0).drs_zone == 0
    assert track.state_at(600.0).drs_zone is None
    assert track.state_at(100.0).sector == 1
    assert track.state_at(500.0).sector == 2
    assert track.state_at(900.0).sector == 3


def test_corner_banking_shorthand_is_applied():
    definition = TrackDefinition(
        name="banked",
        layout=(
            StraightDefinition(300.0),
            CornerDefinition(200.0, 90.0, CornerDirection.LEFT, corner_id=1, banking=6.0),
            StraightDefinition(300.0),
        ),
    )
    track = build_track(definition)
    corner_mid = 300.0 + 0.5 * definition.layout[1].arc_length(definition.defaults)
    assert math.degrees(track.state_at(corner_mid).banking) == pytest.approx(6.0, abs=0.3)


def test_elevation_is_sampled_from_the_continuous_profile():
    definition = TrackDefinition(
        name="hilly",
        layout=(
            StraightDefinition(500.0),
            CornerDefinition(80.0, 180.0, CornerDirection.LEFT, corner_id=1),
            StraightDefinition(500.0),
            CornerDefinition(80.0, 180.0, CornerDirection.LEFT, corner_id=2),
        ),
        elevation=ElevationDefinition(control_points=((0.0, 0.0), (600.0, 30.0))),
    )
    track = build_track(definition)
    assert track.state_at(600.0).elevation == pytest.approx(30.0, abs=0.5)
    assert track.elevation_gain > 25.0


def test_out_of_range_overlays_are_rejected_at_build_time():
    """Silently dropping an overlay would hide a data error."""
    base = dict(
        name="bad",
        layout=(
            StraightDefinition(500.0),
            CornerDefinition(80.0, 180.0, CornerDirection.LEFT, corner_id=1),
            StraightDefinition(500.0),
            CornerDefinition(80.0, 180.0, CornerDirection.LEFT, corner_id=2),
        ),
    )
    with pytest.raises(TrackBuildError, match="elevation control point"):
        build_track(
            TrackDefinition(
                **base, elevation=ElevationDefinition(control_points=((0.0, 0.0), (99_000.0, 5.0)))
            )
        )
    with pytest.raises(TrackBuildError, match="DRS"):
        build_track(
            TrackDefinition(**base, drs=DrsDefinition(zones=(DrsZone(0, 10.0, 20.0, 99_000.0),)))
        )
    with pytest.raises(TrackBuildError, match="sector"):
        build_track(TrackDefinition(**base, sectors=SectorDefinition(boundaries=(800.0, 400.0))))


def test_plan_geometry_is_carried_on_each_segment(square_track):
    """Segments carry x/y/heading so a client can draw the track directly."""
    first = square_track.segments[0]
    assert (first.x, first.y, first.heading) == (0.0, 0.0, 0.0)
    moved = square_track.segments[10]
    assert moved.x > 0.0


def test_builder_accepts_a_full_simulation_config(config, square_definition):
    track = TrackBuilder(config).build(square_definition)
    assert track.length > 0


def test_segment_count_criteria():
    builder = TrackBuilder(TrackBuildConfig())
    from f1_race_engine.track.builder import LayoutSpan

    straight = LayoutSpan(SegmentKind.STRAIGHT, 1000.0, 0.0, 0.0)
    assert builder.segment_count(straight) == 40  # 1000 / 25

    # A tight arc is refined by the heading-change criterion.
    tight = LayoutSpan(SegmentKind.CORNER, 40.0, 0.04, 0.04)
    assert builder.segment_count(tight) > builder.segment_count(
        LayoutSpan(SegmentKind.CORNER, 40.0, 0.002, 0.002)
    )

    # A transition is refined by the curvature-change criterion.
    transition = LayoutSpan(SegmentKind.CORNER_ENTRY, 40.0, 0.0, 0.04)
    assert builder.segment_count(transition) > builder.segment_count(
        LayoutSpan(SegmentKind.CORNER_ENTRY, 40.0, 0.0, 0.001)
    )

    assert builder.segment_count(LayoutSpan(SegmentKind.STRAIGHT, 0.0, 0.0, 0.0)) == 0


# -- DRS zones across the timing line ----------------------------------------


def test_a_drs_zone_may_wrap_the_start_finish_line():
    """Monza's main-straight zone does exactly this.

    The timing line is a timing device, not a feature of the road, so a zone
    that happens to straddle it is an ordinary zone and everything about it has
    to keep working.
    """
    zone = DrsZone(0, 4_500.0, 4_800.0, 300.0, "main", lap_length=5_000.0)
    assert zone.wraps
    assert zone.length == pytest.approx(500.0)
    assert zone.contains(4_900.0)
    assert zone.contains(100.0)
    assert not zone.contains(400.0)
    assert not zone.contains(2_500.0)


def test_a_wrapping_zone_needs_the_lap_length_to_be_described():
    with pytest.raises(TrackBuildError, match="wraps the start/finish line"):
        DrsZone(0, 4_500.0, 4_800.0, 300.0)


def test_overlaps_are_found_across_the_timing_line():
    """A wrapping zone must be compared as an arc, not as an interval."""
    from f1_race_engine.track.drs import DrsMap

    wrapping = DrsZone(0, 4_500.0, 4_800.0, 300.0, lap_length=5_000.0)
    overlapping = DrsZone(1, 3_000.0, 100.0, 900.0)
    separate = DrsZone(2, 1_500.0, 1_800.0, 2_600.0)
    assert DrsMap([wrapping, overlapping], 5_000.0).overlaps() == [(0, 1)]
    assert DrsMap([wrapping, separate], 5_000.0).overlaps() == []
