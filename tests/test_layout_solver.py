"""The design-time closure solver."""

from __future__ import annotations

import math

import pytest

from f1_race_engine.core.errors import TrackBuildError
from f1_race_engine.track.builder import build_track
from f1_race_engine.track.definitions import (
    CornerDefinition,
    CornerDirection,
    StraightDefinition,
    TrackDefinition,
)
from f1_race_engine.track.layout_solver import (
    apply_straight_lengths,
    solve_straight_lengths,
)


def open_layout() -> TrackDefinition:
    """Right turn angles, wrong straights: the loop does not meet itself."""
    return TrackDefinition(
        name="open loop",
        layout=(
            StraightDefinition(1200.0),
            CornerDefinition(60.0, 90.0, CornerDirection.LEFT, corner_id=1),
            StraightDefinition(300.0),
            CornerDefinition(150.0, 90.0, CornerDirection.LEFT, corner_id=2),
            StraightDefinition(400.0),
            CornerDefinition(90.0, 90.0, CornerDirection.LEFT, corner_id=3),
            StraightDefinition(250.0),
            CornerDefinition(120.0, 90.0, CornerDirection.LEFT, corner_id=4),
            StraightDefinition(200.0),
        ),
    )


def closure_error(definition: TrackDefinition) -> float:
    return build_track(definition).centerline().closure_error


def test_solver_closes_an_open_layout():
    definition = open_layout()
    assert closure_error(definition) > 100.0
    solution = solve_straight_lengths(definition)
    assert solution.converged
    assert solution.closure_error < 1e-3
    assert closure_error(apply_straight_lengths(definition, solution.lengths)) < 1e-3


def test_solver_can_pin_the_lap_length():
    definition = open_layout()
    solution = solve_straight_lengths(definition, target_lap_length=4200.0)
    assert solution.converged
    assert solution.lap_length == pytest.approx(4200.0, abs=1e-3)
    assert solution.closure_error < 1e-3


def test_solver_leaves_the_turning_untouched():
    """Only straights move, so the layout's turn angles cannot drift."""
    definition = open_layout()
    solved = apply_straight_lengths(
        definition, solve_straight_lengths(definition).lengths
    )
    assert solved.total_turn_angle == pytest.approx(definition.total_turn_angle)
    assert [c.radius for c in solved.corners] == [c.radius for c in definition.corners]


def test_solver_respects_the_minimum_straight_length():
    definition = open_layout()
    solution = solve_straight_lengths(definition, min_straight_length=150.0)
    assert min(solution.lengths) >= 150.0 - 1e-9


def test_already_closed_layout_is_left_almost_alone(proving_ground_definition):
    solution = solve_straight_lengths(proving_ground_definition)
    assert solution.initial_closure_error < 0.1
    assert solution.closure_error <= solution.initial_closure_error + 1e-9
    assert max(abs(a) for a in solution.adjustments) < 0.1


def test_solution_reports_its_adjustments():
    definition = open_layout()
    solution = solve_straight_lengths(definition)
    assert len(solution.adjustments) == len(definition.straights)
    assert solution.to_dict()["converged"] is True


def test_apply_rejects_a_wrong_number_of_lengths():
    with pytest.raises(TrackBuildError):
        apply_straight_lengths(open_layout(), [1.0, 2.0])


def test_layout_without_straights_is_rejected():
    definition = TrackDefinition(
        name="circle",
        layout=(CornerDefinition(100.0, 360.0, CornerDirection.LEFT, corner_id=1),),
    )
    with pytest.raises(TrackBuildError):
        solve_straight_lengths(definition)


def test_solved_layouts_pass_validation():
    from f1_race_engine.track.definitions import SectorDefinition
    from f1_race_engine.track.validation import validate_track
    from dataclasses import replace

    definition = open_layout()
    solved = apply_straight_lengths(
        definition, solve_straight_lengths(definition).lengths
    )
    solved = replace(
        solved, sectors=SectorDefinition(boundaries=(solved.lap_length / 3.0,
                                                     2.0 * solved.lap_length / 3.0))
    )
    assert validate_track(build_track(solved)).ok


# -- corner angles -----------------------------------------------------------


def closed_lap_with_wrong_angles() -> TrackDefinition:
    """Four right-handers that turn 400 degrees between them, not 360."""
    return TrackDefinition(
        name="over-turned",
        layout=(
            StraightDefinition(length=400.0),
            CornerDefinition(radius=60.0, angle=100.0, direction=CornerDirection.RIGHT),
            StraightDefinition(length=400.0),
            CornerDefinition(radius=60.0, angle=100.0, direction=CornerDirection.RIGHT),
            StraightDefinition(length=400.0),
            CornerDefinition(radius=60.0, angle=100.0, direction=CornerDirection.RIGHT),
            StraightDefinition(length=400.0),
            CornerDefinition(radius=60.0, angle=100.0, direction=CornerDirection.RIGHT),
        ),
    )


def test_corner_angles_are_scaled_until_the_heading_closes():
    from f1_race_engine.track.layout_solver import (
        apply_corner_angles,
        solve_corner_angles,
    )

    solution = solve_corner_angles(closed_lap_with_wrong_angles())
    assert solution.turns == -1
    assert solution.residual_deg == pytest.approx(40.0)
    assert solution.angles == pytest.approx((90.0, 90.0, 90.0, 90.0))
    assert solution.worst_adjustment_fraction == pytest.approx(0.10)

    closed = apply_corner_angles(closed_lap_with_wrong_angles(), solution.angles)
    track = build_track(closed)
    assert track.total_heading_change == pytest.approx(-2.0 * math.pi, abs=1e-9)


def test_the_correction_is_shared_in_proportion_to_each_angle():
    """A big corner read off a map carries proportionally more error."""
    from f1_race_engine.track.layout_solver import solve_corner_angles

    definition = TrackDefinition(
        name="mixed",
        layout=(
            StraightDefinition(length=300.0),
            CornerDefinition(radius=40.0, angle=180.0, direction=CornerDirection.RIGHT),
            StraightDefinition(length=300.0),
            CornerDefinition(radius=40.0, angle=90.0, direction=CornerDirection.RIGHT),
            StraightDefinition(length=300.0),
            CornerDefinition(radius=40.0, angle=130.0, direction=CornerDirection.RIGHT),
        ),
    )
    solution = solve_corner_angles(definition)
    assert sum(solution.angles) == pytest.approx(360.0)
    adjustments = solution.adjustments
    # Ordered the same way as the angles they correct.
    assert abs(adjustments[0]) > abs(adjustments[2]) > abs(adjustments[1])


def test_a_layout_that_does_not_go_round_is_rejected():
    from f1_race_engine.track.layout_solver import solve_corner_angles

    barely_turns = TrackDefinition(
        name="not a lap",
        layout=(
            StraightDefinition(length=500.0),
            CornerDefinition(radius=200.0, angle=20.0, direction=CornerDirection.RIGHT),
        ),
    )
    with pytest.raises(TrackBuildError, match="not close to a whole lap|whole lap"):
        solve_corner_angles(barely_turns)
