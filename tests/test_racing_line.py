"""The line a car drives, which is not the centre of the road.

The tests here are about the *shape* of the answer rather than a number, for a
reason worth stating: the obvious yardstick -- the outside-apex-outside
construction from a corner's chord and sagitta -- is wrong, and checking
against it is what made this look broken when it was not.  That construction
assumes the line can be at the outside edge at turn-in and the inside edge at
the apex, and says nothing about the *cost* of moving across.  Getting eight
metres sideways over forty metres of track is itself a ninety-metre radius,
which is tighter than most of the corners it is meant to be easing.  So the
line a minimum-curvature solve finds gains far less than the construction
suggests, and that is the physics rather than a failure to converge.
"""

from __future__ import annotations

import math

import pytest

from f1_race_engine.track.racing_line import CAR_WIDTH, solve_racing_line


def corner(
    radius: float,
    degrees: float,
    *,
    width: float = 12.0,
    step: float = 2.0,
    transition: float = 40.0,
):
    """A corner between two long straights, with clothoid entry and exit.

    The transitions are not decoration.  A road whose curvature steps from zero
    to 1/R at a point does not exist -- a car cannot steer instantly and a
    circuit is not built that way, which is why the engine's own builder puts
    clothoids in.  Handed that step anyway, the solve produces a line that
    spikes at the discontinuity and comes out *tighter* than the road, and it
    took measuring the same corner with and without transitions to see that the
    input was the unphysical part rather than the solver.
    """
    arc = radius * math.radians(abs(degrees))
    straight = int(300 / step)
    ease = min(int(transition / step), int(arc / step) // 3)
    turning = max(1, int(arc / step) - 2 * ease)
    sign = 1.0 if degrees > 0 else -1.0

    curvature = [0.0] * straight
    curvature += [sign * (i + 1) / (ease + 1) / radius for i in range(ease)]
    curvature += [sign / radius] * turning
    curvature += [sign * (ease - i) / (ease + 1) / radius for i in range(ease)]
    curvature += [0.0] * straight

    line = solve_racing_line(curvature, [width] * len(curvature), step)
    return line, straight, turning + 2 * ease


# -- the shape ---------------------------------------------------------------


def test_the_apex_is_on_the_inside():
    """The one thing that has to be true.  With the sign the other way round
    the solve puts the apex on the outside, every radius comes back tighter
    than the road, and the model is worse than not having one."""
    line, straight, turning = corner(80.0, 90.0)
    apex = line.offset[straight + turning // 2]
    assert apex > 0.0, "a left-hand corner is apexed to the left"

    right, straight, turning = corner(80.0, -90.0)
    assert right.offset[straight + turning // 2] < 0.0


def test_the_line_is_straighter_than_the_road():
    line, _, _ = corner(80.0, 90.0)
    assert line.tightest_line_radius > line.tightest_centreline_radius


def test_it_uses_the_road_it_is_given_and_no_more():
    line, _, _ = corner(80.0, 90.0, width=12.0)
    room = (12.0 - CAR_WIDTH) / 2.0
    assert 0.0 < line.width_used <= 1.0 + 1e-9
    assert max(abs(n) for n in line.offset) <= room + 1e-9


def test_a_wider_road_buys_more():
    narrow, _, _ = corner(80.0, 90.0, width=10.0)
    wide, _, _ = corner(80.0, 90.0, width=20.0)
    assert wide.tightest_line_radius > narrow.tightest_line_radius


def test_a_road_no_wider_than_the_car_buys_nothing():
    line, _, _ = corner(80.0, 90.0, width=CAR_WIDTH)
    assert all(abs(n) < 1e-9 for n in line.offset)
    assert line.tightest_line_radius == pytest.approx(
        line.tightest_centreline_radius, rel=1e-6
    )


def test_a_straight_stays_straight():
    step = 2.0
    curvature = [0.0] * 400
    line = solve_racing_line(curvature, [12.0] * 400, step)
    assert max(abs(k) for k in line.curvature) < 1e-6


# -- the size of it ----------------------------------------------------------


def test_the_gain_is_the_size_a_racing_line_actually_is():
    """Twenty to ninety per cent of radius on a twelve-metre road with normal
    transitions -- not the two hundred per cent the chord-and-sagitta
    construction predicts, because that construction does not charge for what
    the lateral movement itself costs: getting eight metres sideways over forty
    metres of track is a ninety-metre radius on its own."""
    for radius, degrees in ((50.0, 90.0), (100.0, 90.0), (200.0, 45.0)):
        line, _, _ = corner(radius, degrees)
        ratio = line.tightest_line_radius / line.tightest_centreline_radius
        assert 1.05 < ratio < 2.2, f"R={radius} {degrees}deg came out at {ratio:.2f}"


def test_a_long_shallow_bend_gains_more_than_a_hairpin():
    """A hairpin has nowhere to go: the road is the same width but the corner
    turns so far that straightening it would need more room than exists."""
    hairpin, _, _ = corner(30.0, 180.0)
    sweeper, _, _ = corner(200.0, 45.0)
    assert (
        sweeper.tightest_line_radius / sweeper.tightest_centreline_radius
        > hairpin.tightest_line_radius / hairpin.tightest_centreline_radius
    )


# -- convergence -------------------------------------------------------------


def test_the_answer_stops_moving():
    """A coarse-to-fine cascade rather than plain relaxation, because the line
    is almost entirely long-wavelength and relaxation alone cannot see it."""
    step = 2.0
    arc = 200.0 * math.radians(45.0)
    straight, turning = int(300 / step), int(arc / step)
    curvature = [0.0] * straight + [1 / 200.0] * turning + [0.0] * straight

    settled = [
        solve_racing_line(
            curvature, [12.0] * len(curvature), step, sweeps=sweeps
        ).tightest_line_radius
        for sweeps in (200, 800)
    ]
    assert settled[1] == pytest.approx(settled[0], rel=0.02)


def test_a_lap_that_is_too_short_to_solve_is_handed_back_unchanged():
    line = solve_racing_line([0.01, 0.01], [12.0, 12.0], 2.0)
    assert line.curvature == (0.01, 0.01)
    assert line.offset == (0.0, 0.0)
