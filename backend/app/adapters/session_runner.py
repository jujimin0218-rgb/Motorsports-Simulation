"""Running a round on the race engine.

The management layer never simulates a race.  It assembles the field -- a car
built from each team's ratings, a driver built from each profile, the tyres and
the fuel -- hands it to the engine's own :class:`QualifyingSession` and
:class:`RaceSession`, and reads the answer back.  There is no second race model
anywhere in the game, and the number of laps, the weather, the safety car and
the failures are all the engine's, unchanged.

Two things this layer does own.

**Which randomness.**  Each session gets a hub addressed by season, round and
session name (see :mod:`app.game.rng`), so a round re-run after a load is the
same round.  The engine takes ownership of the hub it is given.

**Entries are built fresh.**  The engine's :class:`RaceEntry` is mutable and a
race writes tyre wear, fuel, damage and retirement into it.  Reusing one across
rounds would carry last week's puncture into this week's race, so every session
gets new ones.

**One sky per weekend.**  The engine has a weather model and a track-evolution
model and both are handed to the session, so a wet qualifying is wet because
the engine made it rain and the tyre choice follows from the water on the road.
Continuity between the sessions is :mod:`app.adapters.conditions`; nothing
about the weather itself is decided here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

from f1_race_engine.core.rng import RngHub
from f1_race_engine.environment import AmbientConditions
from f1_race_engine.race import (
    QualifyingResult,
    RaceEntry,
    RaceResult,
    RaceSession,
    RaceStrategy,
    compound_for_conditions,
)
from f1_race_engine.race.qualifying import DEFAULT_FORMAT, QualifyingSession
from f1_race_engine.track.io import load_track
from f1_race_engine.track.model import Track
from f1_race_engine.tyres.io import load_builtin_compounds
from f1_race_engine.vehicle import VehicleSetup

from ..game.calendar import Circuit
from ..game.standings import RaceOutcome
from ..game.state import GameState
from .car_builder import build_vehicle
from .conditions import RoundConditions, build_conditions

__all__ = [
    "COMPOUND_SET",
    "FieldEntry",
    "build_field",
    "outcomes_from",
    "run_qualifying",
    "run_race",
    "setup_for",
    "track_for",
]

#: The tyres the season is run on.  One set for the whole calendar, as the
#: sport does it.
COMPOUND_SET = "reference_2024"

#: Fuel for a race, in kg.  The engine burns it off over the distance and the
#: car gets quicker as it goes, which is where a real race's lap-time curve
#: comes from.
RACE_FUEL_KG = 100.0

#: Qualifying runs light.
QUALIFYING_FUEL_KG = 20.0


@dataclass(frozen=True, slots=True)
class FieldEntry:
    """One car on the grid, and who is in it.

    The engine's :class:`RaceEntry` knows a car number and not a driver id, so
    this keeps the two together for turning the result back into something the
    championship can score.
    """

    car_number: int
    driver_id: str
    team_id: str
    entry: RaceEntry


def track_for(circuit: Circuit) -> Track:
    """The engine circuit this round is driven on."""
    return load_track(circuit.physics_track)


def setup_for(circuit: Circuit) -> VehicleSetup:
    """How much wing to run here.

    Straight off the circuit's downforce requirement.  Not a lap-time
    correction: the wing level changes the car's actual lift and drag, and the
    engine works out what that is worth -- which is why running the Monaco wing
    at Monza is slow rather than merely suboptimal.
    """
    return VehicleSetup(wing_level=min(1.0, max(0.0, circuit.downforce_requirement)))


def build_field(
    state: GameState,
    round_number: int,
    *,
    fuel_mass: float,
    attacking: bool = True,
    water_depth: float = 0.0,
) -> list[FieldEntry]:
    """Assemble the grid for one session.

    Every car and every driver is built here from the game's own data, so a
    driver signed yesterday and an upgrade fitted this morning are both in the
    car that takes the track.
    """
    circuit = state.circuit_for(round_number)
    setup = setup_for(circuit)
    compounds = load_builtin_compounds(COMPOUND_SET)

    field: list[FieldEntry] = []
    number = 0
    for team in state.teams.values():
        supplier = state.engine_for(team.id)
        for driver_id in team.drivers:
            profile = state.driver(driver_id)
            if profile.retired:
                continue
            number += 1
            vehicle = build_vehicle(team, supplier, setup=setup)
            entry = RaceEntry(
                car_number=number,
                driver=profile.to_engine_driver(attacking=attacking),
                vehicle=vehicle,
                team=team.name,
                fuel_mass=fuel_mass,
                compounds=compounds.compounds,
                strategy=RaceStrategy(),
            )
            # What the car starts on is decided by the water on the road, by
            # the engine's own rule -- not by a default that happens to be a
            # medium whatever the sky is doing.
            entry.fit(compound_for_conditions(compounds.compounds, water_depth))
            field.append(
                FieldEntry(
                    car_number=number,
                    driver_id=driver_id,
                    team_id=team.id,
                    entry=entry,
                )
            )
    return field


def _hub(state: GameState, round_number: int, session: str) -> RngHub:
    return state.round_rng(round_number).engine_hub(session)


def run_qualifying(
    state: GameState,
    round_number: int,
    *,
    ambient: AmbientConditions | None = None,
) -> tuple[QualifyingResult, list[FieldEntry], RoundConditions]:
    """Run knockout qualifying and produce a grid.

    The engine's own session: three segments, cars eliminated at the end of
    each, real out-laps and real flying laps on a track that rubbers in as it
    goes and washes clean when it rains.  Nothing about it is decided here.
    """
    circuit = state.circuit_for(round_number)
    track = track_for(circuit)
    weather = build_conditions(state, round_number, track, session="qualifying")
    field = build_field(
        state,
        round_number,
        fuel_mass=QUALIFYING_FUEL_KG,
        water_depth=weather.evolution.mean_water_depth,
    )
    session = QualifyingSession(
        track,
        [item.entry for item in field],
        segments=DEFAULT_FORMAT,
        rng=_hub(state, round_number, "qualifying"),
        ambient=ambient or weather.ambient,
        conditions=weather.conditions,
        weather=weather.weather,
        evolution=weather.evolution,
        fuel_mass=QUALIFYING_FUEL_KG,
    )
    return session.run(), field, weather


def run_race(
    state: GameState,
    round_number: int,
    *,
    grid: Sequence[int] = (),
    ambient: AmbientConditions | None = None,
    racing: bool = True,
    hazards: bool = True,
    laps: int | None = None,
    on_lap: Callable[..., None] | None = None,
) -> tuple[RaceResult, list[FieldEntry], RoundConditions]:
    """Run the grand prix.

    ``grid`` is the qualifying order as car numbers.  Left empty, the field
    lines up in entry order -- which is what a round run without qualifying
    does, and is useful for testing and for a quick simulation.
    """
    circuit = state.circuit_for(round_number)
    entry_round = state.round(round_number)
    track = track_for(circuit)
    weather = build_conditions(state, round_number, track, session="race")
    field = build_field(
        state,
        round_number,
        fuel_mass=RACE_FUEL_KG,
        water_depth=weather.evolution.mean_water_depth,
    )
    by_number = {item.car_number: item for item in field}

    for position, car_number in enumerate(grid, start=1):
        if car_number in by_number:
            by_number[car_number].entry.grid_position = position
    for item in field:
        if item.entry.grid_position is None:
            item.entry.grid_position = item.car_number

    session = RaceSession(
        track,
        [item.entry for item in field],
        laps=laps if laps is not None else entry_round.laps,
        rng=_hub(state, round_number, "race"),
        ambient=ambient or weather.ambient,
        conditions=weather.conditions,
        weather=weather.weather,
        evolution=weather.evolution,
        racing=racing,
        hazards=hazards,
        standing_start=True,
    )
    return session.run(on_lap=on_lap), field, weather


def outcomes_from(
    result: RaceResult,
    field: Sequence[FieldEntry],
    round_number: int,
    *,
    pole: int | None = None,
    positions: dict[int, int] | None = None,
) -> list[RaceOutcome]:
    """Turn the engine's classification into championship results.

    A projection, not a replacement: the engine's own result is kept whole in
    :attr:`GameState.race_archive` for the replay, and this is only what the
    standings need.

    ``positions`` overrides the finishing order, which is how a time penalty
    reaches the championship: the stewards re-take the order and the points
    follow it rather than the order the cars crossed the line in.
    """
    by_number = {item.car_number: item for item in field}
    fastest = result.fastest_lap.car_number if result.fastest_lap is not None else None

    outcomes: list[RaceOutcome] = []
    for row in result.classification:
        item = by_number.get(row.car_number)
        if item is None:  # pragma: no cover - a car the game did not enter
            continue
        outcomes.append(
            RaceOutcome(
                round_number=round_number,
                driver_id=item.driver_id,
                team_id=item.team_id,
                position=(positions or {}).get(row.car_number, row.position),
                started=item.entry.grid_position or 0,
                laps_completed=row.laps_completed,
                retired=row.retired,
                fastest_lap=(row.car_number == fastest),
                pole=(pole is not None and row.car_number == pole),
            )
        )
    outcomes.sort(key=lambda outcome: outcome.position)
    return outcomes
