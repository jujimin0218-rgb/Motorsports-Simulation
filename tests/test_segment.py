"""Segment invariants."""

from __future__ import annotations

import math

import pytest

from f1_race_engine.track.segment import (
    KerbType,
    SegmentKind,
    SurfaceType,
    TrackSegment,
)


def make(**overrides) -> TrackSegment:
    defaults = dict(
        index=0, distance=100.0, length=10.0,
        curvature_start=0.0, curvature_end=0.02,
        elevation_start=5.0, elevation_end=6.0,
        banking=0.05, surface_grip=1.0, surface_type=SurfaceType.ASPHALT,
        roughness=0.5, track_width=13.0, sector=1, corner_id=3,
        corner_name="T3", drs_zone=None, kerb=KerbType.MEDIUM,
        kind=SegmentKind.CORNER_ENTRY, x=1.0, y=2.0, heading=0.3,
    )
    defaults.update(overrides)
    return TrackSegment(**defaults)


def test_derived_geometry():
    segment = make()
    assert segment.end_distance == 110.0
    assert segment.mid_distance == 105.0
    assert segment.curvature == pytest.approx(0.01)
    assert segment.radius == pytest.approx(100.0)
    assert segment.curvature_change == pytest.approx(0.02)
    assert segment.curvature_rate == pytest.approx(0.002)
    assert segment.heading_change == pytest.approx(0.1)
    assert segment.elevation == pytest.approx(5.5)
    assert segment.gradient == pytest.approx(0.1)
    assert segment.gradient_percent == pytest.approx(10.0)


def test_straight_has_infinite_radius():
    segment = make(curvature_start=0.0, curvature_end=0.0, kind=SegmentKind.STRAIGHT)
    assert math.isinf(segment.radius)
    assert math.isinf(segment.corner_radius)
    assert segment.is_straight
    assert not segment.is_corner


def test_right_hand_corner_has_negative_curvature_but_positive_radius():
    segment = make(curvature_start=-0.02, curvature_end=-0.02)
    assert segment.curvature < 0
    assert segment.radius < 0
    assert segment.corner_radius == pytest.approx(50.0)


def test_interpolation_within_the_segment():
    segment = make()
    assert segment.curvature_at(100.0) == pytest.approx(0.0)
    assert segment.curvature_at(110.0) == pytest.approx(0.02)
    assert segment.curvature_at(105.0) == pytest.approx(0.01)
    assert segment.elevation_at(105.0) == pytest.approx(5.5)
    # Clamped outside the segment.
    assert segment.curvature_at(0.0) == pytest.approx(0.0)
    assert segment.curvature_at(1e6) == pytest.approx(0.02)


def test_heading_follows_the_clothoid_form():
    """Integrating linear curvature gives a quadratic heading."""
    segment = make(heading=0.0, curvature_start=0.0, curvature_end=0.02)
    # theta(s) = k0*s + 0.5*(dk/ds)*s^2, with dk/ds = 0.002
    assert segment.heading_at(105.0) == pytest.approx(0.5 * 0.002 * 25.0)
    assert segment.heading_at(110.0) == pytest.approx(segment.heading_change)


def test_contains_is_half_open():
    segment = make()
    assert segment.contains(100.0)
    assert segment.contains(109.999)
    assert not segment.contains(110.0)
    assert not segment.contains(99.999)


def test_zero_length_segment_does_not_divide_by_zero():
    segment = make(length=0.0)
    assert segment.curvature_rate == 0.0
    assert segment.gradient == 0.0
    assert segment.local_fraction(100.0) == 0.0


def test_segment_is_immutable():
    with pytest.raises(Exception):
        make().length = 5.0  # type: ignore[misc]


def test_round_trip_through_plain_data():
    segment = make()
    assert TrackSegment.from_dict(segment.to_dict()) == segment


def test_export_renders_infinite_radius_as_null():
    segment = make(curvature_start=0.0, curvature_end=0.0)
    assert segment.to_dict()["radius"] is None


def test_enums_serialise_as_strings():
    payload = make().to_dict()
    assert payload["surface_type"] == "asphalt"
    assert payload["kerb"] == "medium"
    assert payload["kind"] == "corner_entry"
