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

from ..adapters import conditions
from ..adapters import replay as replay_builder
from ..adapters import session_runner
from ..game import ai, development, finance
from ..game.calendar import Round, RoundPhase
from ..game.development import Upgrade
from ..game.finance import Ledger
from ..game import penalties as penalties_module
from ..game.errors import InvalidGamePhase, RaceAlreadyCompleted
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

#: Keep every Nth telemetry sample of every lap of every car.
#:
#: The lap simulation produces a sample every few metres, which is more than a
#: trace needs to be read: at ten it is about seventy-five points a lap, one
#: every seventy metres, which draws every braking zone and puts a quarter
#: distance race under a megabyte rather than over twenty.
TELEMETRY_STRIDE = 10


def _trace(samples: Any) -> list[list[float]]:
    """One lap, as the few channels a chart actually draws.

    Compact on purpose: a race is twenty cars over every lap, and named keys
    per sample would be most of the file.  Gear is not here because the engine
    does not model a gearbox -- it reports ``None`` -- and a column of nulls is
    worse than an honest absence.
    """
    return [
        [
            round(sample.distance, 1),
            round(sample.speed_kph, 1),
            round(sample.throttle, 3),
            round(sample.brake, 3),
            1 if sample.drs else 0,
        ]
        for sample in samples
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

    Nothing is timed, which is what practice is for in this game: the point is
    that the laps happened -- rubber goes down, the sky moves on, and qualifying
    starts on the track Friday left behind.

    What it reports is what a player needs before committing to anything: what
    the circuit asks of the tyres, and what the weather is actually doing as
    opposed to what the venue's climate said it probably would.
    """
    entry = _current(state)
    entry.require(RoundPhase.PRACTICE)
    circuit = state.circuit_for(entry.number)
    track = session_runner.track_for(circuit)
    weather = conditions.build_conditions(
        state, entry.number, track, session="practice"
    )
    entry.advance(RoundPhase.PRACTICE)
    return RoundReport(
        entry.number,
        entry.phase,
        {
            "circuit": circuit.id,
            "tyre_stress": circuit.tyre_stress,
            "overtaking_ease": circuit.overtaking_ease,
            "weather": weather.summary(),
            "forecast": {
                "air_temperature": circuit.air_temperature,
                "rain_probability": circuit.rain_probability,
                "relative_humidity": circuit.relative_humidity,
                "wind_speed": circuit.wind_speed,
            },
        },
    )


def run_qualifying(
    state: GameState,
    *,
    on_segment: Any = None,
    on_lap: Any = None,
    on_start: Any = None,
) -> RoundReport:
    """Run the engine's knockout qualifying and set the grid.

    ``on_segment`` is the engine's per-segment callback, passed straight
    through -- which is how a job reports progress on something that takes a
    couple of minutes.  ``on_start`` goes with it, and is what lets that job
    show each segment's order rather than only how many are done.
    """
    entry = _current(state)
    entry.require(RoundPhase.QUALIFYING)

    result, field, weather = session_runner.run_qualifying(
        state,
        entry.number,
        on_segment=on_segment,
        on_lap=on_lap,
        on_start=on_start,
    )
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
            "weather": weather.summary(),
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
    on_start: Any = None,
) -> RoundReport:
    """Run the grand prix, score it, and file it.

    Three things come out of one call to the engine and each goes somewhere
    different: the championship gets the outcomes, the replay gets the engine's
    result whole, and the player gets the summary.

    ``on_lap`` is the engine's own per-lap callback, passed straight through --
    which is how a job reports progress on something that takes minutes.
    ``on_start`` goes with it, and is what lets that job show the race rather
    than only how far through it is.
    """
    entry = _current(state)
    entry.require(RoundPhase.STRATEGY)
    if entry.race_id is not None:
        raise RaceAlreadyCompleted(f"round {entry.number} has already been run")

    grid_numbers = _grid_car_numbers(state, entry)

    # The lap that produced a telemetry trace is gone once the race moves on,
    # so it is kept here as it happens rather than recomputed afterwards from a
    # car whose tyres and fuel have since changed.
    traces: dict[str, dict[str, list[list[float]]]] = {}

    def collect(race_entry: Any, lap_result: Any) -> None:
        samples = getattr(lap_result, "telemetry", None)
        if samples:
            car = traces.setdefault(str(race_entry.car_number), {})
            car[str(lap_result.lap)] = _trace(samples)
        if on_lap is not None:
            on_lap(race_entry, lap_result)

    result, field, weather = session_runner.run_race(
        state,
        entry.number,
        grid=grid_numbers,
        hazards=hazards and state.settings.hazards,
        laps=state.laps_for(entry.number),
        on_lap=collect,
        on_start=on_start,
        telemetry=TELEMETRY_STRIDE,
    )
    pole = grid_numbers[0] if grid_numbers else None

    # The stewards look at what the engine reported and decide what it cost.
    # Time penalties are applied *before* the outcomes are filed, because a
    # five-second penalty that changes a result has to change the points too.
    labels = {
        item.car_number: (item.driver_id, item.team_id) for item in field
    }
    decisions = _steward(state, entry.number, result, field, labels)
    state.penalties.extend(decisions)
    revised = penalties_module.apply_time_penalties(
        result.classification, decisions, labels
    )
    outcomes = session_runner.outcomes_from(
        result, field, entry.number, pole=pole, positions=dict(revised)
    )

    state.record_outcomes(outcomes)
    race_id = f"{state.season}-{entry.number:02d}"
    entry.race_id = race_id
    state.race_archive[race_id] = _archive(result, field)
    state.store_replay(
        race_id,
        replay_builder.build_replay(
            result,
            race_id=race_id,
            lap_length=session_runner.track_for(
                state.circuit_for(entry.number)
            ).length,
            labels={
                item.car_number: {
                    "driver": item.driver_id,
                    "team": item.team_id,
                    "driver_name": state.driver(item.driver_id).name,
                    "team_name": state.team(item.team_id).name,
                }
                for item in field
            },
            telemetry=traces,
        ).to_dict(),
    )

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
            "penalties": [d.to_dict() for d in decisions],
            "weather": weather.summary(),
            "flags": [
                {"lap": lap, "flag": flag, "reason": reason}
                for lap, flag, reason in result.flags
            ],
        },
    )


def _steward(
    state: GameState,
    round_number: int,
    result: Any,
    field: list[session_runner.FieldEntry],
    labels: dict[int, tuple[str, str]],
) -> list[penalties_module.Penalty]:
    """Count the power units, then let the stewards look at the race."""
    for row in result.classification:
        who = labels.get(row.car_number)
        if who is None:
            continue
        driver_id = who[0]
        state.engines_used.setdefault(driver_id, 1)

    # A power-unit failure means a new one for the next race.
    for incident in result.incidents:
        payload = incident.to_dict()
        if payload.get("kind") != "mechanical" or payload.get("system") != "power_unit":
            continue
        who = labels.get(payload.get("car_number"))
        if who is not None:
            state.engines_used[who[0]] = state.engines_used.get(who[0], 1) + 1

    return penalties_module.steward(
        round_number=round_number,
        incidents=result.incidents,
        classification=result.classification,
        labels=labels,
        engines_used={
            labels[row.car_number][0]: state.engines_used.get(
                labels[row.car_number][0], 1
            )
            for row in result.classification
            if row.car_number in labels
        },
        laps=result.laps,
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

    Four things happen here and they happen in this order for a reason.  Parts
    commissioned earlier are fitted *first*, so the research a team banks this
    round is measured against the car it will actually run next time.  Then the
    round is paid for -- salaries, the engine deal, the people, against the
    sponsors.  Then the factory's work is booked.  Then the AI teams spend, with
    the same information the player had.
    """
    entry = _current(state)
    entry.require(RoundPhase.RESULT)
    entry.advance(RoundPhase.RESULT)  # -> development

    fitted = _fit_arriving_upgrades(state, entry.number)
    ledgers = _settle_round(state, entry.number)
    earned = _award_research(state)
    decisions = ai.run_ai_development(state)

    entry.advance(RoundPhase.DEVELOPMENT)  # -> complete
    return RoundReport(
        entry.number,
        entry.phase,
        {
            "upgrades_fitted": [u.to_dict() for u in fitted],
            "rd_points_earned": earned,
            "finances": {tid: led.to_dict() for tid, led in ledgers.items()},
            "ai": [d.to_dict() for d in decisions],
        },
    )


def _fit_arriving_upgrades(state: GameState, round_number: int) -> list[Upgrade]:
    """Fit -- or write off -- every project that has come due.

    A failed project is not a refund: the research and the money went either
    way, which is what makes commissioning one a decision rather than a
    formality.
    """
    fitted: list[Upgrade] = []
    for upgrade in state.upgrades_arriving(round_number):
        stream = state.round_rng(round_number).stream(
            "development.resolve", upgrade=upgrade.id
        )
        development.resolve(upgrade, state.team(upgrade.team_id), stream)
        fitted.append(upgrade)
    return fitted


def _settle_round(state: GameState, round_number: int) -> dict[str, Ledger]:
    """Pay for the round, for everybody."""
    ledgers: dict[str, Ledger] = {}
    for team in state.teams.values():
        ledger = finance.round_costs(state, team.id, round_number=round_number)
        finance.apply(ledger, team)
        ledgers[team.id] = ledger
    return ledgers


def _award_research(state: GameState) -> dict[str, float]:
    """Book the factory's work, on the sliding scale.

    The championship position is *this* season's, so a team that has fallen
    back gets more allowance from the next round onwards -- which is the
    regulation doing what it exists to do, in season rather than after it.
    """
    standings = state.standings()
    earned: dict[str, float] = {}
    for team in state.teams.values():
        points = development.research_earned(
            team,
            state.rules.development,
            position=standings.team_position(team.id) or team.prize_position,
        )
        team.rd_points += points
        earned[team.id] = round(points, 2)
    return earned


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
