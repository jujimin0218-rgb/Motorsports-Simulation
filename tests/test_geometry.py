"""Plan-view geometry must match analytic results."""

from __future__ import annotations

import math

import pytest

from f1_race_engine.track.geometry import centerline_from_segments, integrate_arc


def test_straight_advances_along_its_heading():
    x, y, heading = integrate_arc(0.0, 0.0, 0.0, 0.0, 0.0, 100.0)
    assert (x, y) == pytest.approx((100.0, 0.0))
    assert heading == pytest.approx(0.0)

    x, y, heading = integrate_arc(0.0, 0.0, math.pi / 2, 0.0, 0.0, 100.0)
    assert (x, y) == pytest.approx((0.0, 100.0), abs=1e-9)


def test_quarter_circle_matches_the_analytic_result():
    radius = 100.0
    curvature = 1.0 / radius
    length = 0.5 * math.pi * radius
    x, y, heading = integrate_arc(0.0, 0.0, 0.0, curvature, curvature, length, intervals=64)
    assert (x, y) == pytest.approx((radius, radius), abs=1e-5)
    assert heading == pytest.approx(math.pi / 2)


def test_right_hand_corner_turns_the_other_way():
    radius = 100.0
    curvature = -1.0 / radius
    length = 0.5 * math.pi * radius
    x, y, _ = integrate_arc(0.0, 0.0, 0.0, curvature, curvature, length, intervals=64)
    assert (x, y) == pytest.approx((radius, -radius), abs=1e-5)


def test_full_circle_closes_exactly():
    radius = 100.0
    curvature = 1.0 / radius
    length = math.tau * radius
    x, y, heading = 0.0, 0.0, 0.0
    for _ in range(64):
        x, y, heading = integrate_arc(x, y, heading, curvature, curvature, length / 64)
    assert math.hypot(x, y) == pytest.approx(0.0, abs=1e-6)
    assert heading == pytest.approx(math.tau)


def test_clothoid_heading_is_exact():
    """Heading over a linear-curvature span is 0.5*(k0+k1)*L in closed form."""
    _, _, heading = integrate_arc(0.0, 0.0, 0.0, 0.0, 0.04, 20.0)
    assert heading == pytest.approx(0.5 * 0.04 * 20.0)


def test_zero_length_span_is_a_no_op():
    assert integrate_arc(3.0, 4.0, 1.0, 0.02, 0.02, 0.0) == (3.0, 4.0, 1.0)


def test_odd_interval_count_is_rejected():
    with pytest.raises(ValueError):
        integrate_arc(0.0, 0.0, 0.0, 0.0, 0.0, 10.0, intervals=7)


def test_centerline_of_a_built_track(square_track):
    centerline = square_track.centerline()
    assert len(centerline) == len(square_track.segments) + 1
    assert centerline.length == pytest.approx(square_track.length)
    assert centerline.closure_error < 0.01
    assert centerline.total_heading_change == pytest.approx(math.tau, abs=1e-9)


def test_centerline_sampling_does_not_move_the_endpoint(square_track):
    coarse = square_track.centerline(samples_per_segment=1)
    fine = square_track.centerline(samples_per_segment=8)
    assert fine.points[-1].x == pytest.approx(coarse.points[-1].x, abs=1e-6)
    assert fine.points[-1].y == pytest.approx(coarse.points[-1].y, abs=1e-6)
    assert len(fine) > len(coarse)


def test_normalised_projection_fits_its_box(square_track):
    points = square_track.centerline().normalised(width=800.0, height=600.0, padding=20.0)
    assert all(20.0 - 1e-6 <= x <= 780.0 + 1e-6 for x, _ in points)
    assert all(20.0 - 1e-6 <= y <= 580.0 + 1e-6 for _, y in points)


def test_empty_segment_list_gives_an_empty_centerline():
    centerline = centerline_from_segments([])
    assert len(centerline) == 0
    assert centerline.closure_error == 0.0
    assert centerline.bounds == (0.0, 0.0, 0.0, 0.0)
