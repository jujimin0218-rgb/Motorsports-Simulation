"""The grid, and getting off it (project rule 27).

A standing start is not a lap-time penalty.  It is a car sitting still on a
piece of road some distance behind the line, a driver reacting to the lights,
and then the same acceleration model that produces every other number in this
engine, integrated from zero.

That is worth doing properly because it produces three real things:

* **the grid slot is a distance**, so the car in P10 has further to go to reach
  the line than the car on pole and pays for it in seconds;
* **the launch is the car's**, so a car with more traction gets away better,
  and getting away is worth more at a circuit whose first corner is a long way
  from the line;
* **the reaction is the driver's**, and it happens before the car moves, which
  is the only place in this engine where time is added to anything -- because
  that is literally what a reaction time is.

Phase 9 adds what happens when the cars reach the first corner together.  Until
then they launch into clear air, which is honest rather than pretended.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from ..core.config import SimulationConfig
from ..core.errors import EntryError
from ..core.rng import RngHub
from ..core.units import Metres, Seconds
from ..driver.model import Driver
from ..environment.conditions import AmbientConditions
from ..physics.longitudinal import longitudinal_forces
from ..tyres.state import TyreState
from ..vehicle.model import Vehicle

__all__ = ["GridSlot", "Launch", "launch_from_rest", "reaction_time", "starting_grid"]


@dataclass(frozen=True, slots=True)
class GridSlot:
    """Where one car starts."""

    position: int
    distance_back: Metres
    """How far behind the start line this slot is."""

    def to_dict(self) -> dict[str, Any]:
        return {"position": self.position, "distance_back": self.distance_back}


@dataclass(frozen=True, slots=True)
class Launch:
    """What happened between the lights going out and the start line."""

    reaction: Seconds
    """Time before the car moved."""

    travel: Seconds
    """Time accelerating from rest to the line."""

    exit_speed: float
    """Speed crossing the line, m/s -- the speed lap one starts at."""

    distance: Metres

    @property
    def total(self) -> Seconds:
        return self.reaction + self.travel

    def to_dict(self) -> dict[str, Any]:
        return {
            "reaction": self.reaction,
            "travel": self.travel,
            "total": self.total,
            "exit_speed": self.exit_speed,
            "distance": self.distance,
        }


def starting_grid(
    positions: int,
    *,
    row_spacing: Metres = 8.0,
    first_row: Metres = 8.0,
    stagger: Metres = 4.0,
) -> tuple[GridSlot, ...]:
    """Lay out a grid.

    Two cars to a row and the second column set back, as a real one is: the car
    in P2 starts a few metres behind pole and the car in P3 a row behind that.
    Those metres are the whole of the "grid penalty" in this engine -- a
    distance to cover, not a number of seconds to add.
    """
    if positions < 1:
        raise EntryError("a grid needs at least one position")
    return tuple(
        GridSlot(
            position=position,
            distance_back=(
                first_row
                + row_spacing * ((position - 1) // 2)
                + stagger * ((position - 1) % 2)
            ),
        )
        for position in range(1, positions + 1)
    )


def reaction_time(
    driver: Driver,
    rng: RngHub | None = None,
    *,
    lap: int = 0,
    config: SimulationConfig | None = None,
) -> Seconds:
    """How long this driver takes to react to the lights, s.

    The one place in the engine where seconds are added to a result, because a
    reaction time *is* seconds before anything happens.  Racecraft sets the
    mean and consistency sets the scatter, so a sharp starter is reliably sharp
    and a scattered one is occasionally excellent and occasionally asleep.
    """
    cfg = (config or SimulationConfig()).driver
    attributes = driver.attributes
    mean = cfg.reaction_floor + cfg.reaction_range * (1.0 - attributes.racecraft)
    if rng is None:
        return mean
    stream = rng.stream("driver.start", driver=driver.abbreviation, lap=lap)
    sigma = cfg.reaction_sigma * (1.0 - 0.8 * attributes.consistency)
    return max(stream.normal(mean, sigma), cfg.reaction_floor * 0.5)


def launch_from_rest(
    vehicle: Vehicle,
    distance: Metres,
    *,
    ambient: AmbientConditions | None = None,
    mass: float | None = None,
    tyre_state: TyreState | None = None,
    surface_grip: float = 1.0,
    water_depth: float = 0.0,
    traction_limit: float = 1.0,
    reaction: Seconds = 0.0,
    steps: int = 200,
) -> Launch:
    """Accelerate from a standstill over ``distance`` metres.

    The same force balance the rest of the engine uses, integrated from zero
    with the energy relation ``v1^2 = v0^2 + 2*a*ds``.  Nothing about a start is
    special except the initial condition: a car that puts its power down better
    gets away better, a heavy car gets away worse, and a wet grid punishes both.
    """
    if distance <= 0.0:
        return Launch(reaction=reaction, travel=0.0, exit_speed=0.0, distance=0.0)

    conditions = ambient or AmbientConditions()
    air_density = conditions.air_density
    car_mass = vehicle.total_mass() if mass is None else mass
    tyres = tyre_state or TyreState()
    step = distance / max(steps, 1)

    speed = 0.0
    elapsed = 0.0
    for _ in range(max(steps, 1)):
        # Evaluate at the midpoint of the step, as the profile passes do.
        forces = longitudinal_forces(
            vehicle,
            max(speed, 0.5),
            air_density,
            mass=car_mass,
            throttle=1.0,
            tyre_state=tyres,
            surface_grip=surface_grip * traction_limit,
            water_depth=water_depth,
        )
        acceleration = max(forces.acceleration, 0.01)
        squared = speed * speed + 2.0 * acceleration * step
        next_speed = math.sqrt(squared)
        elapsed += 2.0 * step / (speed + next_speed)
        speed = next_speed

    return Launch(
        reaction=reaction, travel=elapsed, exit_speed=speed, distance=distance
    )
