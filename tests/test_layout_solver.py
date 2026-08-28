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
