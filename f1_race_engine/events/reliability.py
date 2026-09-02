"""Mechanical failures as a hazard, never as a coin flip.

Project rule 36 forbids scattered randomness, and rule 35 wants failures in the
event layer.  What this module adds is the shape of the risk:

.. code-block:: text

    P(failure over a distance) = 1 - exp(-rate * distance * stress)

A **rate per kilometre**, not a probability per lap.  That is not a detail: a
per-lap probability would make Monaco's 78 laps twice as hard on a car as
Spa's 44, when Spa is the longer race by distance and the harder one on a power
unit.  Expressed as a hazard, the answer is the same however finely it is
sampled, and a long circuit is genuinely harder because the car covers more
ground.

Each system carries its own rate and its own **stressor** -- the thing that
makes that part work hard.  A power unit is stressed by the energy it delivers,
brakes by the energy they absorb, cooling by the ambient air it has to reject
heat into.  So a hot race breaks more cars, a power circuit breaks more engines
and a heavy-braking circuit breaks more brakes, without any of that being
written down.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from ..core.config import ReliabilityConfig
from ..core.interpolation import clamp
from ..core.rng import RandomStream
from ..core.units import Metres
from .incident import Incident, IncidentKind, IncidentSeverity

__all__ = [
    "SystemStress",
    "cooling_stress",
    "failure_probability",
    "sample_failure",
    "stress_from_lap",
]


@dataclass(frozen=True, slots=True)
class SystemStress:
    """How hard each system was worked over the distance being assessed.

    Every field is a ratio against a reference lap: 1.0 is a normal racing lap,
    above one is harder than that.  They come from the lap the car actually
    drove, so managing the car genuinely makes it last.
    """

    power_unit: float = 1.0
    """Energy delivered, against a reference lap."""

    gearbox: float = 1.0
    hydraulics: float = 1.0
    cooling: float = 1.0
    """Set from ambient temperature by :func:`sample_failure`."""

    brakes: float = 1.0
    """Energy absorbed under braking, against a reference lap."""

    suspension: float = 1.0
    """Kerb and surface punishment, against a reference lap."""

    def as_dict(self) -> dict[str, float]:
        return {
            "power_unit": self.power_unit,
            "gearbox": self.gearbox,
            "hydraulics": self.hydraulics,
            "cooling": self.cooling,
            "brakes": self.brakes,
            "suspension": self.suspension,
        }


def _rates(config: ReliabilityConfig) -> dict[str, float]:
    """Base hazard per metre for each system."""
    per_thousand_km = {
        "power_unit": config.power_unit_rate,
        "gearbox": config.gearbox_rate,
        "hydraulics": config.hydraulics_rate,
        "cooling": config.cooling_rate,
        "brakes": config.brake_rate,
        "suspension": config.suspension_rate,
    }
    return {name: rate / 1.0e6 for name, rate in per_thousand_km.items()}


def failure_probability(
    distance: Metres,
    stress: SystemStress | None = None,
    *,
    config: ReliabilityConfig | None = None,
) -> dict[str, float]:
    """Chance each system fails over ``distance``, as a mapping.

    Exposed on its own because it is the honest way to check the calibration:
    summed over a race distance it has to land on the retirement rate the sport
    actually has, and that is a number anybody can look up.
    """
    cfg = config or ReliabilityConfig()
    loads = (stress or SystemStress()).as_dict()
    probabilities: dict[str, float] = {}
    for system, rate in _rates(cfg).items():
        factor = clamp(
            max(loads.get(system, 1.0), 0.0) ** cfg.stress_exponent,
            0.0,
            cfg.max_stress_factor,
        )
        probabilities[system] = -math.expm1(-rate * max(distance, 0.0) * factor)
    return probabilities


def cooling_stress(
    air_temperature: float, config: ReliabilityConfig | None = None
) -> float:
    """Cooling stress from the air the car has to reject heat into."""
    cfg = config or ReliabilityConfig()
    excess = air_temperature - cfg.reference_ambient
    return max(1.0 + cfg.cooling_sensitivity * excess, 0.0)


def sample_failure(
    stream: RandomStream,
    *,
    car_number: int,
    lap: int,
    distance: Metres,
    stress: SystemStress | None = None,
    air_temperature: float | None = None,
    config: ReliabilityConfig | None = None,
) -> Incident | None:
    """Draw whether anything broke over ``distance``.

    One draw per system per assessment, from a stream addressed by car and
    system, so adding a car to the grid cannot change what breaks on any other
    car (rule 36).
    """
    cfg = config or ReliabilityConfig()
    live = stress or SystemStress()
    if air_temperature is not None:
        live = SystemStress(
            power_unit=live.power_unit,
            gearbox=live.gearbox,
            hydraulics=live.hydraulics,
            cooling=live.cooling * cooling_stress(air_temperature, cfg),
            brakes=live.brakes,
            suspension=live.suspension,
        )

    for system, probability in failure_probability(distance, live, config=cfg).items():
        if stream.derive(system).chance(probability):
            # Where the car stops is a separate draw from whether it stopped.
            # A driver with a warning gets it out of the way; without one, it
            # is left where it has to be recovered -- and that, not the failure
            # itself, is what can bring out a flag.
            blocks = stream.derive(system, "position").chance(
                cfg.stops_on_circuit_share
            )
            return Incident(
                kind=IncidentKind.MECHANICAL,
                severity=(
                    IncidentSeverity.BLOCKING if blocks else IncidentSeverity.RETIREMENT
                ),
                car_number=car_number,
                lap=lap,
                distance=distance,
                system=system,
                description=f"{system.replace('_', ' ')} failure",
            )
    return None


def stress_from_lap(
    *,
    fuel_used: float,
    energy_harvested: float,
    distance: Metres,
    commitment: float = 1.0,
    config: ReliabilityConfig | None = None,
) -> SystemStress:
    """Work out how hard a lap was on each system, from the lap itself.

    Everything here comes from what the car actually did rather than from a
    per-circuit table: fuel burned per kilometre is what the power unit was
    asked for, energy recovered per kilometre is what the brakes were asked
    for, and commitment is how hard the driver was leaning on the rest of it.
    A car being managed is genuinely more likely to see the flag.
    """
    cfg = config or ReliabilityConfig()
    kilometres = max(distance, 1.0) / 1000.0
    power = (fuel_used / kilometres) / cfg.reference_fuel_per_km
    braking = (energy_harvested / kilometres) / cfg.reference_harvest_per_km
    effort = max(commitment, 0.0)
    return SystemStress(
        power_unit=max(power, 0.0),
        # Torque through the drivetrain tracks what the engine is delivering.
        gearbox=max(0.5 * (power + effort), 0.0),
        hydraulics=effort,
        cooling=1.0,
        brakes=max(braking, 0.0),
        suspension=effort,
    )
