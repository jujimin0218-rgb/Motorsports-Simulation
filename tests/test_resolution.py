"""Resolution independence (project rule 7).

    "Resolution을 변경해도 물리 모델의 논리가 달라지지 않아야 한다."

Changing how finely a track is sampled must change *only* the sampling.  Every
quantity the physics will consume -- lap length, turning, corner radii,
elevation, gradient, the track state at a given distance -- has to come out the
same.  If this file ever fails, the speed profile and lap time built on top of
the track model are no longer trustworthy, because a lap time would depend on
an implementation detail rather than on the circuit.
"""

from __future__ import annotations

import math

import pytest

from f1_race_engine.core.config import TrackBuildConfig
from f1_race_engine.track.builder import build_track

#: Sampling settings from very coarse to metre-scale.
CONFIGS = [
    TrackBuildConfig(straight_segment_length=30.0, corner_segment_length=20.0,
                     min_segment_length=5.0, max_segment_length=30.0,
                     max_heading_change_per_segment_deg=8.0,
                     max_curvature_change_per_segment=0.01),
    TrackBuildConfig(),  # defaults
    TrackBuildConfig(straight_segment_length=10.0, corner_segment_length=3.0,
                     min_segment_length=1.0, max_segment_length=10.0,
                     max_heading_change_per_segment_deg=1.0,
                     max_curvature_change_per_segment=0.001),
    TrackBuildConfig(straight_segment_length=1.0, corner_segment_length=1.0,
                     min_segment_length=1.0, max_segment_length=1.0),
]


@pytest.fixture(scope="module")
def tracks(request):
    from f1_race_engine.track.io import load_builtin_definition

    definition = load_builtin_definition("synthetic_proving_ground")
    return [build_track(definition, config) for config in CONFIGS]


def test_sampling_actually_differs(tracks):
    """Guard the guard: the configs must really produce different sampling."""
    counts = [len(track) for track in tracks]
    assert len(set(counts)) == len(counts)
    assert max(counts) > 8 * min(counts)


def test_lap_length_is_identical(tracks):
    reference = tracks[0].length
    for track in tracks[1:]:
        assert track.length == pytest.approx(reference, abs=1e-9)


def test_total_turning_is_identical(tracks):
    reference = tracks[0].total_heading_change
    for track in tracks[1:]:
        assert track.total_heading_change == pytest.approx(reference, abs=1e-9)


def test_minimum_radius_is_identical(tracks):
    reference = tracks[0].min_radius
    for track in tracks[1:]:
        assert track.min_radius == pytest.approx(reference, rel=1e-9)


def test_corner_count_and_geometry_are_identical(tracks):
    reference = tracks[0].corners
    for track in tracks[1:]:
        corners = track.corners
        assert set(corners) == set(reference)
        for corner_id, entry in reference.items():
            assert corners[corner_id]["length"] == pytest.approx(
                float(entry["length"]), rel=1e-9
            )
            assert corners[corner_id]["turn_angle"] == pytest.approx(
                float(entry["turn_angle"]), rel=1e-9
            )
            assert corners[corner_id]["min_radius"] == pytest.approx(
                float(entry["min_radius"]), rel=1e-6
            )


def test_sector_lengths_are_identical(tracks):
    reference = tracks[0].sector_lengths()
    for track in tracks[1:]:
        assert track.sector_lengths() == pytest.approx(reference, abs=1e-9)


def test_track_state_matches_at_every_distance(tracks):
    """The real test: physics queries state by distance, so state must agree."""
    reference = tracks[0]
    probes = [i * reference.length / 997.0 for i in range(997)]
    for track in tracks[1:]:
        for distance in probes:
            a = reference.state_at(distance)
            b = track.state_at(distance)
            assert b.curvature == pytest.approx(a.curvature, abs=2e-4)
            assert b.elevation == pytest.approx(a.elevation, abs=1e-6)
            assert b.gradient == pytest.approx(a.gradient, abs=1e-6)
            assert b.banking == pytest.approx(a.banking, abs=1e-6)
            assert b.track_width == pytest.approx(a.track_width, abs=1e-6)
            assert b.grip == pytest.approx(a.grip, abs=1e-9)
            assert b.sector == a.sector
            assert b.drs_zone == a.drs_zone


def test_curvature_integral_is_resolution_independent(tracks):
    """Turning is the integral of curvature; quadrature must not bias it."""
    for track in tracks:
        total = math.fsum(s.curvature * s.length for s in track.segments)
        assert math.degrees(total) == pytest.approx(360.0, abs=1e-9)


def test_elevation_closes_at_every_resolution(tracks):
    for track in tracks:
        start = track.segments[0].elevation_start
        end = track.segments[-1].elevation_end
        assert end == pytest.approx(start, abs=1e-6)


def test_plan_geometry_converges(tracks):
    """Closure error must not grow as resolution changes."""
    for track in tracks:
        assert track.centerline().closure_error_fraction < 1e-4


def test_building_twice_is_deterministic(proving_ground_definition):
    """Test A applied to the track model: same input, same output."""
    a = build_track(proving_ground_definition)
    b = build_track(proving_ground_definition)
    assert len(a) == len(b)
    assert [s.to_dict() for s in a.segments] == [s.to_dict() for s in b.segments]
