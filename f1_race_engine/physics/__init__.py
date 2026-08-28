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

* :mod:`~f1_race_engine.physics.speed_profile` -- the cornering, braking and
  acceleration limits, and the forward/backward passes that combine them
* :mod:`~f1_race_engine.physics.braking` / :mod:`~f1_race_engine.physics.acceleration`
  -- braking points and corner-exit analysis read out of the profile
* :mod:`~f1_race_engine.physics.lap_time` -- the limit lap

The *driver* -- imperfection, consistency, mistakes -- is Phase 4, and attaches
through :class:`~f1_race_engine.physics.speed_profile.PerformanceLimits`.
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
from .acceleration import AccelerationZone, acceleration_zones
from .braking import BrakingZone, braking_zones
from .lap_time import LapTimeResult, compute_lap_time, format_lap_result
from .longitudinal import (
    LongitudinalForces,
    longitudinal_forces,
    max_acceleration,
    max_deceleration,
    traction_limited_force,
)
from .speed_profile import (
    PerformanceLimits,
    SpeedProfile,
    compute_speed_profile,
    cornering_limits,
)

__all__ = [
    "AccelerationZone",
    "AxleLoads",
    "BrakingZone",
    "LapTimeResult",
    "LateralCapability",
    "LongitudinalForces",
    "PerformanceLimits",
    "SpeedProfile",
    "acceleration_zones",
    "braking_zones",
    "compute_lap_time",
    "compute_speed_profile",
    "corner_speed_limit",
    "cornering_limits",
    "format_lap_result",
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
