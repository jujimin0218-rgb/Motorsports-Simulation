"""Running a round, one legal step at a time.

Every operation the player can perform on a race weekend goes through here, and
every one of them starts by asking the round whether this is the moment for it.
That check is the security model (project rule 19): a client that posts to the
race endpoint without having qualified gets a refusal, not a race.  Hiding the
button is a courtesy to the player and nothing more.

The order is fixed and the machine only moves forwards:

.. code-block:: text

    NOT_STARTED -> PRACTICE -> QUALIFYING -> STRATEGY -> RACE
                -> RESULT -> DEVELOPMENT -> COMPLETE

Re-running a round is done by loading a save, not by stepping backwards, which
is what keeps a result reproducible instead of merely repeatable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from f1_race_engine.race import QualifyingResult, RaceResult

from ..adapters import session_runner
from ..game.calendar import Round, RoundPhase
from ..game.errors import InvalidGamePhase, RaceAlreadyCompleted
from ..game.standings import RaceOutcome
from ..game.state import GameState

__all__ = [
    "RoundReport",
    "advance_to_next_round",
    "run_development",
    "run_practice",
    "run_qualifying",
    "run_race",
    "start_round",
]


@dataclass(frozen=True, slots=True)
class RoundReport:
    """What one step of a weekend produced."""

    round_number: int
    phase: RoundPhase
    detail: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "round": self.round_number,
            "phase": self.phase.value,
            **self.detail,
        }


def _current(state: GameState) -> Round:
    entry = state.current_round
    if entry is None:
        raise InvalidGamePhase(
            f"the {state.season} season is over; there is no round to run"
        )
    return entry


# -- the weekend -------------------------------------------------------------


def start_round(state: GameState) -> RoundReport:
    """Open the weekend."""
    entry = _current(state)
    entry.require(RoundPhase.NOT_STARTED)
    entry.advance(RoundPhase.NOT_STARTED)
    circuit = state.circuit_for(entry.number)
    return RoundReport(
        entry.number,
        entry.phase,
        {
            "circuit": circuit.to_dict(),
            "laps": state.laps_for(entry.number),
            "full_distance_laps": entry.laps,
        },
    )


def run_practice(state: GameState) -> RoundReport:
    """Run practice.

    Nothing is timed and nothing is reported, which is what practice is for in
    this game so far: the point is that the laps happened.  What it produces is
    an estimate of how the tyres will behave here, taken from the engine's own
    degradation measurement rather than from a table -- so a circuit that eats
    tyres says so before the player has to commit to a strategy.
    """
    entry = _current(state)
    entry.require(RoundPhase.PRACTICE)
    circuit = state.circuit_for(entry.number)
    entry.advance(RoundPhase.PRACTICE)
    return RoundReport(
        entry.number,
        entry.phase,
        {
            "circuit": circuit.id,
            "tyre_stress": circuit.tyre_stress,
            "overtaking_ease": circuit.overtaking_ease,
        },
    )


def run_qualifying(state: GameState) -> RoundReport:
    """Run the engine's knockout qualifying and set the grid."""
    entry = _current(state)
    entry.require(RoundPhase.QUALIFYING)

    result, field = session_runner.run_qualifying(state, entry.number)
    by_number = {item.car_number: item for item in field}
    entry.grid = [
        by_number[car].driver_id for car in result.order if car in by_number
    ]
    entry.advance(RoundPhase.QUALIFYING)

    return RoundReport(
        entry.number,
        entry.phase,
        {
            "pole": entry.grid[0] if entry.grid else None,
            "grid": list(entry.grid),
            "qualifying": _qualifying_summary(result, by_number),
        },
    )


def _qualifying_summary(
    result: QualifyingResult, by_number: dict[int, session_runner.FieldEntry]
) -> list[dict[str, Any]]:
    rows = []
    for position, car in enumerate(result.order, start=1):
        item = by_number.get(car)
        if item is None:  # pragma: no cover
            continue
        rows.append(
            {
                "position": position,
                "driver": item.driver_id,
                "team": item.team_id,
                "best": result.best.get(car),
                "eliminated_in": result.eliminated_in.get(car),
            }
        )
    return rows


def run_race(
    state: GameState,
    *,
    hazards: bool = True,
    on_lap: Any = None,
) -> RoundReport:
    """Run the grand prix, score it, and file it.

    Three things come out of one call to the engine and each goes somewhere
    different: the championship gets the outcomes, the replay gets the engine's
    result whole, and the player gets the summary.

    ``on_lap`` is the engine's own per-lap callback, passed straight through --
    which is how a job reports progress on something that takes minutes.
    """
    entry = _current(state)
    entry.require(RoundPhase.STRATEGY)
    if entry.race_id is not None:
        raise RaceAlreadyCompleted(f"round {entry.number} has already been run")

    grid_numbers = _grid_car_numbers(state, entry)
    result, field = session_runner.run_race(
        state,
        entry.number,
        grid=grid_numbers,
        hazards=hazards and state.settings.hazards,
        laps=state.laps_for(entry.number),
        on_lap=on_lap,
    )
    pole = grid_numbers[0] if grid_numbers else None
    outcomes = session_runner.outcomes_from(result, field, entry.number, pole=pole)

    state.record_outcomes(outcomes)
    race_id = f"{state.season}-{entry.number:02d}"
    entry.race_id = race_id
    state.race_archive[race_id] = _archive(result, field)

    entry.advance(RoundPhase.STRATEGY)  # -> race
    entry.advance(RoundPhase.RACE)  # -> result
    return RoundReport(
        entry.number,
        entry.phase,
        {
            "race_id": race_id,
            "winner": outcomes[0].driver_id if outcomes else None,
            "classification": [o.to_dict() for o in outcomes],
            "retirements": sum(1 for o in outcomes if o.retired),
            "flags": [
                {"lap": lap, "flag": flag, "reason": reason}
                for lap, flag, reason in result.flags
            ],
        },
    )


def _grid_car_numbers(state: GameState, entry: Round) -> list[int]:
    """Turn the stored grid of driver ids into this session's car numbers.

    The field is rebuilt for every session, so the numbers have to be resolved
    against the field that is about to run rather than the one that qualified.
    """
    if not entry.grid:
        return []
    lookup = {
        item.driver_id: item.car_number
        for item in session_runner.build_field(
            state, entry.number, fuel_mass=session_runner.RACE_FUEL_KG
        )
    }
    return [lookup[d] for d in entry.grid if d in lookup]


def _archive(result: RaceResult, field: list[session_runner.FieldEntry]) -> dict[str, Any]:
    """The engine's own result, kept whole for the replay.

    Deliberately the engine's output rather than a summary of it: a replay that
    can only show what the summary kept is not a replay.
    """
    payload = result.to_dict(include_laps=True)
    payload["drivers"] = {
        str(item.car_number): {"driver": item.driver_id, "team": item.team_id}
        for item in field
    }
    return payload


def run_development(state: GameState) -> RoundReport:
    """Close the weekend out.

    Phase 3 spends the round's research here.  For now it books the research
    the round earned and closes the round, so that the season advances.
    """
    entry = _current(state)
    entry.require(RoundPhase.RESULT)
    entry.advance(RoundPhase.RESULT)  # -> development

    rules = state.rules.development
    earned: dict[str, float] = {}
    for team in state.teams.values():
        points = rules.rd_points_per_round_base * (
            1.0 + rules.facility_multiplier_per_level * (team.facilities.average_level - 3)
        )
        team.rd_points += points
        earned[team.id] = round(points, 2)

    entry.advance(RoundPhase.DEVELOPMENT)  # -> complete
    return RoundReport(entry.number, entry.phase, {"rd_points_earned": earned})


def advance_to_next_round(state: GameState) -> RoundReport:
    """Where the season is now."""
    nxt = state.current_round
    if nxt is None:
        return RoundReport(
            len(state.calendar), RoundPhase.COMPLETE, {"season_complete": True}
        )
    return RoundReport(
        nxt.number,
        nxt.phase,
        {"circuit": state.circuit_for(nxt.number).to_dict(), "season_complete": False},
    )
