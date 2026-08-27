"""Physics core -- how a car moves.

Kept strictly apart from the race core (project rule 4).  Nothing in here knows
about laps, positions, gaps or pit stops; it knows about forces.

* :mod:`~f1_race_engine.physics.grip` -- vertical load and the friction that
  follows from it
* :mod:`~f1_race_engine.physics.longitudinal` -- the force balance, traction
  and braking
* :mod:`~f1_race_engine.physics.lateral` -- cornering capability and the
  cornering speed limit

Aerodynamic forces live with the platform that produces them, in
:mod:`f1_race_engine.vehicle.aero`, rather than in a separate physics module:
they are a property of the car's shape, and splitting the coefficients from the
force they produce only adds a layer to step through.

The speed profile, braking points and lap time -- which assemble these into a
lap -- are Phase 3 and 4.
"""

from __future__ import annotations

from .grip import AxleLoads, grip_limits, normal_loads, slope_angle
from .lateral import (
    LateralCapability,
    corner_speed_limit,
    lateral_capability,
    max_lateral_acceleration,
    required_lateral_acceleration,
)
from .longitudinal import (
    LongitudinalForces,
    longitudinal_forces,
    max_acceleration,
    max_deceleration,
    traction_limited_force,
)

__all__ = [
    "AxleLoads",
    "LateralCapability",
    "LongitudinalForces",
    "corner_speed_limit",
    "grip_limits",
    "lateral_capability",
    "longitudinal_forces",
    "max_acceleration",
    "max_deceleration",
    "max_lateral_acceleration",
    "normal_loads",
    "required_lateral_acceleration",
    "slope_angle",
    "traction_limited_force",
]
