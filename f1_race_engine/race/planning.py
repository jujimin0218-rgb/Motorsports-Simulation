"""Planning a race before it happens (project rule 31).

A strategist's problem is arithmetic over two measured quantities: what each
compound does over a stint, and what a stop costs at this circuit.  Both are
measured here rather than assumed -- the degradation curve is a stint actually
driven, and the pit loss is the difference between two journeys between the
same two points.

That makes planning expensive.  It is also the only version of it that can be
wrong for the right reasons: if the tyre model changes, the strategy changes
with it, and nobody has to remember to update a table.
"""

from __future__ import annotations

from typing import Sequence

from ..core.config import SimulationConfig
from ..core.rng import RngHub
from ..driver.model import Driver
from ..environment.conditions import AmbientConditions
from ..physics.speed_profile import compute_speed_profile
from ..simulation.lap import LapSimulator
from ..track.model import Track
from ..track.surface import TrackConditions
from ..tyres.compound import TyreCompound
from ..tyres.state import TyreState
from ..vehicle.ers import ErsState
from ..vehicle.model import Vehicle
from .pitlane import PitLane, pit_loss
from .strategy import StrategyPlan, degradation_curve, plan_strategy

__all__ = ["measure_degradation", "measure_pit_loss", "plan_race"]


def measure_degradation(
    track: Track,
    vehicle: Vehicle,
    driver: Driver,
    compound: TyreCompound,
    laps: int,
    *,
    rng: RngHub | None = None,
    ambient: AmbientConditions | None = None,
    conditions: TrackConditions | None = None,
    config: SimulationConfig | None = None,
    fuel_mass: float = 60.0,
) -> tuple[float, ...]:
    """Drive a stint on ``compound`` and return the lap times it gave.

    The fuel load is held at a representative mid-race figure so the curve
    isolates the tyre.  A real strategist runs the same test on Friday and has
    the same problem: the car they measured is not quite the car they will
    race.
    """
    simulator = LapSimulator(
        track, vehicle, driver,
        rng=rng or RngHub(0), ambient=ambient, conditions=conditions, config=config,
    )
    energy = ErsState(energy_remaining=vehicle.spec.ers.capacity)

    def one_lap(lap: int, state: TyreState) -> float:
        return simulator.simulate(
            lap=lap, fuel_mass=fuel_mass, tyre_state=state, ers_state=energy,
            record_telemetry=False,
        ).lap_time

    return degradation_curve(one_lap, compound, laps)


def measure_pit_loss(
    track: Track,
    vehicle: Vehicle,
    lane: PitLane,
    *,
    ambient: AmbientConditions | None = None,
    conditions: TrackConditions | None = None,
    mass: float | None = None,
    tyre_state: TyreState | None = None,
    config: SimulationConfig | None = None,
) -> float:
    """What one stop costs at this circuit, in seconds."""
    profile = compute_speed_profile(
        track, vehicle, ambient, mass=mass, tyre_state=tyre_state,
        conditions=conditions, config=config,
    )
    return pit_loss(
        vehicle, lane, profile, ambient=ambient, mass=mass, tyre_state=tyre_state
    ).total


def plan_race(
    track: Track,
    vehicle: Vehicle,
    driver: Driver,
    compounds: Sequence[TyreCompound],
    race_laps: int,
    *,
    lane: PitLane | None = None,
    rng: RngHub | None = None,
    ambient: AmbientConditions | None = None,
    conditions: TrackConditions | None = None,
    config: SimulationConfig | None = None,
    fuel_mass: float = 60.0,
    max_stint: int | None = None,
    max_stops: int = 3,
    minimum_stint: int = 6,
    require_two_compounds: bool = True,
) -> StrategyPlan:
    """Work out how to cover the distance, by measuring and then adding up.

    Every compound is driven until it is either finished or has covered the
    race, the stop is priced, and the search picks the split with the smallest
    total.  Which compound to start on and how many stops to make are outputs.
    """
    lane = lane or PitLane.for_track(track.length)
    horizon = max_stint or race_laps
    curves = {
        compound.code: measure_degradation(
            track, vehicle, driver, compound, min(horizon, race_laps),
            rng=rng, ambient=ambient, conditions=conditions, config=config,
            fuel_mass=fuel_mass,
        )
        for compound in compounds
    }
    loss = measure_pit_loss(
        track, vehicle, lane, ambient=ambient, conditions=conditions, config=config
    )
    return plan_strategy(
        curves, compounds, race_laps, loss,
        max_stops=max_stops, minimum_stint=minimum_stint,
        require_two_compounds=require_two_compounds,
    )
