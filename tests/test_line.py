"""The line a car drives, and the road that is put back underneath it.

The property that matters most here is the last one: a car on the racing line
drives the radii the circuit was authored with.  Everything else in this file
is about there being somewhere else to go; that one is about it costing
nothing to have added it.
"""

from __future__ import annotations

import bisect
import math

import pytest

from f1_race_engine import load_track
from f1_race_engine.world import build_world
from f1_race_engine.world.geometry import Vec2
from f1_race_engine.world.line import (
    Lines,
    curvature_at,
    curvature_between,
    curvature_of,
    road_under_line,
    solve_lines,
)


@pytest.fixture(scope="module")
def world():
    return build_world(load_track("bahrain"))


@pytest.fixture(scope="module")
def solved(world):
    """The lines the world already solved.

    Deliberately not solved again here: ``world.centre`` is the reconstructed
    *road*, so re-solving on it would put a road under a road and measure
    something that never happens in a race.
    """
    assert world.lines is not None
    return world.centre, world.lines


# -- the curvature of a path -------------------------------------------------


def test_three_points_on_a_circle_give_its_curvature():
    radius = 50.0
    points = [
        Vec2(radius * math.cos(angle), radius * math.sin(angle))
        for angle in (0.0, 0.05, 0.10)
    ]
    assert curvature_at(*points) == pytest.approx(1.0 / radius, rel=1e-3)


def test_curvature_is_positive_turning_left():
    left = curvature_at(Vec2(0.0, 0.0), Vec2(1.0, 0.0), Vec2(2.0, 0.5))
    right = curvature_at(Vec2(0.0, 0.0), Vec2(1.0, 0.0), Vec2(2.0, -0.5))
    assert left > 0.0
    assert right < 0.0


def test_a_straight_line_has_no_curvature():
    points = tuple(Vec2(float(x), 0.0) for x in range(5))
    assert curvature_at(points[0], points[1], points[2]) == 0.0


def test_repeated_points_do_not_divide_by_zero():
    here = Vec2(3.0, 4.0)
    assert curvature_at(here, here, here) == 0.0


# -- the road under the line -------------------------------------------------


def test_the_road_is_offset_from_the_line(world):
    width = tuple(2.0 * half for half in world.half_width)
    offset = road_under_line(world.centre, world.headings, width, world.step)
    assert len(offset) == len(world.centre)
    # It uses the road it is given rather than sitting in the middle of it.
    assert max(abs(value) for value in offset) > 1.0


def test_the_line_stays_on_the_road(solved, world):
    _, lines = solved
    for index, room in enumerate(lines.room):
        assert abs(lines.optimal.offsets[index]) <= room + 1e-6


def test_a_circuit_too_short_to_solve_is_left_alone():
    line = tuple(Vec2(float(x), 0.0) for x in range(4))
    offset = road_under_line(line, (0.0,) * 4, (12.0,) * 4, 4.0)
    assert offset == (0.0, 0.0, 0.0, 0.0)


# -- out, in, out ------------------------------------------------------------


def test_the_line_goes_out_in_out_through_a_corner(world, solved):
    """Wide on the way in, against the inside at the apex, wide on the way out.

    Measured at the circuit's tightest corner and stated in terms of *this*
    corner's inside, so the assertion reads the same whichever way it turns.
    """
    _, lines = solved
    curvature = curvature_of(world.centre)
    count = len(curvature)
    apex = max(range(count), key=lambda index: abs(curvature[index]))
    side = 1.0 if curvature[apex] > 0.0 else -1.0

    def inside_by(delta: int) -> float:
        index = (apex + delta) % count
        return lines.optimal.offsets[index] * side

    approach = inside_by(-20)
    through = max(inside_by(delta) for delta in range(-8, 5))
    exit_ = inside_by(20)

    assert approach < -1.0, "should be out wide on the way in"
    assert through > 3.0, "should get to the inside through the corner"
    assert exit_ < -1.0, "should run wide again on the way out"


def test_the_edges_are_on_opposite_sides_of_the_road(solved):
    _, lines = solved
    for index in range(len(lines.side)):
        assert lines.inside_edge[index] == pytest.approx(-lines.outside_edge[index])


def test_every_sample_has_an_inside(solved):
    _, lines = solved
    assert all(-1.0 <= value <= 1.0 for value in lines.side)
    assert any(abs(value) > 0.5 for value in lines.side)


def test_the_inside_never_jumps_across_the_road(world, solved):
    """A side that flipped between two samples would be a kink, and a kink is a
    radius the physics would charge a defending car for."""
    _, lines = solved
    count = len(lines.inside_edge)
    worst = max(
        abs(lines.inside_edge[(index + 1) % count] - lines.inside_edge[index])
        for index in range(count)
    )
    assert worst < 1.5, f"the inside edge jumped {worst:.2f} m between samples"


# -- choosing a line ---------------------------------------------------------


def test_bias_runs_from_outside_through_optimal_to_inside(solved):
    _, lines = solved
    index = 300
    assert lines.at(index, 0.0) == pytest.approx(lines.optimal.offsets[index])
    assert lines.at(index, 1.0) == pytest.approx(lines.inside_edge[index])
    assert lines.at(index, -1.0) == pytest.approx(lines.outside_edge[index])


def test_a_car_off_the_racing_line_drives_a_different_radius(world, solved):
    """The point of the whole module: a chosen line has its own curvature.

    Measured as the worst of a corner rather than at one sample.  At the apex
    itself the racing line is already hard against the inside, so there is
    barely a line to change to; the price of the inside line is paid on the
    way in, where the racing line is out wide and the defensive one is not.
    """
    centre, lines = solved
    curvature = curvature_of(world.centre)
    count = len(curvature)
    apex = max(range(count), key=lambda index: abs(curvature[index]))

    def worst(bias: float) -> float:
        return max(
            abs(curvature_between(centre, world.headings, lines, (apex + d) % count, bias))
            for d in range(-20, 21)
        )

    assert worst(1.0) > worst(0.0) * 1.05


def test_room_on_the_inside_shrinks_as_a_car_moves_over(solved):
    _, lines = solved
    index = 300
    assert lines.room_at(index, 1.0) < lines.room_at(index, 0.0)


# -- the property that protects every lap time this engine has produced ------


def test_the_racing_line_drives_the_authored_radii(world, solved):
    """A car on the racing line goes round the radii the circuit was authored
    and validated with, so putting a road underneath it changes no lap time.

    Checked against the engine's own track model rather than against anything
    this package derived, because that model is what the physics reads.
    """
    _, lines = solved
    track = load_track("bahrain")
    anchors = [Vec2(segment.x, segment.y) for segment in track.segments]
    starts = [segment.distance for segment in track.segments]

    def authored(distance: float) -> Vec2:
        """The path the circuit was authored as, walked the way the world walks
        it before the road is put underneath."""
        wrapped = distance % track.length
        index = max(0, min(bisect.bisect_right(starts, wrapped) - 1, len(anchors) - 1))
        here = anchors[index]
        there = anchors[(index + 1) % len(anchors)]
        span = (
            starts[index + 1] - starts[index]
            if index + 1 < len(starts)
            else track.length - starts[index]
        )
        if span <= 0.0:
            return here
        return here + (there - here) * ((wrapped - starts[index]) / span)

    worst = max(
        (point - authored(index * world.step)).length
        for index, point in enumerate(lines.optimal.points)
    )
    assert worst < 1e-9, f"the racing line left the authored path by {worst} m"


def test_solving_twice_gives_the_same_lines(world):
    """A seed replays a race, so nothing here may wander between runs."""
    width = tuple(2.0 * half for half in world.half_width)
    first = solve_lines(world.centre, world.headings, width, world.step)[1]
    second = solve_lines(world.centre, world.headings, width, world.step)[1]
    assert first.optimal.offsets == second.optimal.offsets
    assert first.inside_edge == second.inside_edge
    assert first.outside_edge == second.outside_edge
