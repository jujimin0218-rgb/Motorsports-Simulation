"""The stewards -- the one thing on Phase 6's list the engine does not have.

And it is right that it does not: the engine's job is to say what happened on
the road, and whether that was somebody's fault is a regulation rather than a
force balance.  Everything here is derived from something the engine actually
reported.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.game.penalties import (
    ENGINE_ALLOWANCE,
    Penalty,
    PenaltyKind,
    REFERENCE_LAPS,
    apply_time_penalties,
    grid_drop_for,
    steward,
    track_limit_offences,
)


@dataclass
class FakeRow:
    """Just enough of the engine's classification row."""

    car_number: int
    position: int
    mistakes: int = 0
    retired: bool = False
    total_time: float = 5000.0
    laps_completed: int = 57


def incident(**overrides):
    payload = {
        "kind": "collision",
        "severity": "damage",
        "car_number": 1,
        "lap": 5,
        "involved": [2],
        "system": None,
    }
    payload.update(overrides)

    class Wrapper:
        def to_dict(self):
            return payload

    return Wrapper()


LABELS = {1: ("a", "red"), 2: ("b", "blue"), 3: ("c", "green")}


# -- collisions --------------------------------------------------------------


def test_contact_that_damaged_somebody_is_a_penalty():
    decisions = steward(
        round_number=1,
        incidents=[incident()],
        classification=[],
        labels=LABELS,
        engines_used={},
    )
    assert len(decisions) == 1
    assert decisions[0].kind is PenaltyKind.TIME
    assert decisions[0].seconds == 5.0
    assert decisions[0].driver_id == "a"
    assert "car 2" in decisions[0].reason


def test_contact_that_cost_nobody_anything_is_a_racing_incident():
    """Which is the correct answer far more often than a penalty is."""
    decisions = steward(
        round_number=1,
        incidents=[incident(severity="minor")],
        classification=[],
        labels=LABELS,
        engines_used={},
    )
    assert decisions == []


def test_a_solo_spin_is_nobody_elses_fault():
    decisions = steward(
        round_number=1,
        incidents=[incident(kind="driver_error", involved=[])],
        classification=[],
        labels=LABELS,
        engines_used={},
    )
    assert decisions == []


def test_ending_somebodys_race_costs_more_than_damaging_it():
    def seconds(severity: str) -> float:
        return steward(
            round_number=1,
            incidents=[incident(severity=severity)],
            classification=[],
            labels=LABELS,
            engines_used={},
        )[0].seconds

    assert seconds("retirement") > seconds("damage")


# -- track limits ------------------------------------------------------------


def test_track_limits_are_a_rate_not_a_count():
    """This game runs races at anything from a quarter distance to a full one,
    and the same driving has to earn the same penalty at either."""
    quarter = track_limit_offences(2, REFERENCE_LAPS // 4)
    full = track_limit_offences(8, REFERENCE_LAPS)
    assert quarter == pytest.approx(full, rel=0.05)


def test_only_a_share_of_mistakes_reach_the_stewards():
    """The engine counts every moment -- a lock-up, a snap -- and most of them
    stay on the road."""
    assert track_limit_offences(10, REFERENCE_LAPS) < 10


def test_a_clean_race_earns_nothing():
    decisions = steward(
        round_number=1,
        incidents=[],
        classification=[FakeRow(1, 1, mistakes=0), FakeRow(2, 2, mistakes=2)],
        labels=LABELS,
        engines_used={},
        laps=REFERENCE_LAPS,
    )
    assert decisions == []


def test_a_messy_race_is_warned_then_penalised():
    """Calibrated against what the engine actually produces: a measured field
    averages 0.146 mistakes per driver per lap, and the numbers are set so one
    or two drivers in a race are penalised and a couple more are warned."""
    decisions = steward(
        round_number=1,
        incidents=[],
        classification=[
            FakeRow(1, 1, mistakes=38),  # the messiest driver on the road
            FakeRow(2, 2, mistakes=19),  # untidy
            FakeRow(3, 3, mistakes=8),   # a normal afternoon
        ],
        labels=LABELS,
        engines_used={},
        laps=REFERENCE_LAPS,
    )
    by_driver = {d.driver_id: d for d in decisions}
    assert by_driver["a"].kind is PenaltyKind.TIME
    assert by_driver["b"].kind is PenaltyKind.REPRIMAND
    assert "c" not in by_driver


# -- power units -------------------------------------------------------------


def test_the_allowance_is_free_and_the_ones_after_it_escalate():
    assert grid_drop_for(ENGINE_ALLOWANCE) == 0
    first = grid_drop_for(ENGINE_ALLOWANCE + 1)
    second = grid_drop_for(ENGINE_ALLOWANCE + 2)
    assert first > 0
    assert second > first


def test_a_car_over_the_allowance_drops_places_next_time():
    decisions = steward(
        round_number=4,
        incidents=[],
        classification=[],
        labels=LABELS,
        engines_used={"a": ENGINE_ALLOWANCE + 1, "b": ENGINE_ALLOWANCE},
    )
    assert len(decisions) == 1
    assert decisions[0].kind is PenaltyKind.GRID
    assert decisions[0].driver_id == "a"
    assert decisions[0].places > 0


# -- applying a time penalty -------------------------------------------------


def test_five_seconds_only_costs_a_place_if_somebody_was_within_five():
    """Which is the whole reason a penalised driver spends the last laps
    building a gap."""
    close = [
        FakeRow(1, 1, total_time=5000.0),
        FakeRow(2, 2, total_time=5002.0),
    ]
    far = [
        FakeRow(1, 1, total_time=5000.0),
        FakeRow(2, 2, total_time=5020.0),
    ]
    penalty = [Penalty(1, "a", "red", PenaltyKind.TIME, "contact", seconds=5.0)]

    lost = dict(apply_time_penalties(close, penalty, LABELS))
    kept = dict(apply_time_penalties(far, penalty, LABELS))
    assert lost[1] == 2, "two seconds ahead is not enough to survive five"
    assert kept[1] == 1, "twenty seconds ahead is"


def test_a_retired_car_is_not_reordered_by_seconds_it_never_ran():
    rows = [
        FakeRow(1, 1, total_time=5000.0),
        FakeRow(2, 2, total_time=5001.0),
        FakeRow(3, 3, retired=True, laps_completed=20, total_time=1800.0),
    ]
    penalty = [Penalty(1, "a", "red", PenaltyKind.TIME, "contact", seconds=30.0)]
    order = dict(apply_time_penalties(rows, penalty, LABELS))
    assert order[3] == 3, "a car that stopped stays classified where it stopped"
    assert order[2] == 1 and order[1] == 2


def test_more_laps_beats_less_time():
    """A classification is ordered on laps first.  A car a lap down does not
    move ahead by being quick."""
    rows = [
        FakeRow(1, 1, total_time=5000.0, laps_completed=57),
        FakeRow(2, 2, total_time=4900.0, laps_completed=56),
    ]
    order = dict(
        apply_time_penalties(
            rows, [Penalty(1, "a", "red", PenaltyKind.TIME, "x", seconds=5.0)], LABELS
        )
    )
    assert order[1] == 1


def test_no_penalties_leaves_the_order_alone():
    rows = [FakeRow(1, 1), FakeRow(2, 2)]
    assert apply_time_penalties(rows, [], LABELS) == [(1, 1), (2, 2)]


def test_penalties_round_trip():
    penalty = Penalty(3, "a", "red", PenaltyKind.GRID, "engine", places=10)
    assert Penalty.from_dict(penalty.to_dict()) == penalty
    assert "10-place" in penalty.headline
