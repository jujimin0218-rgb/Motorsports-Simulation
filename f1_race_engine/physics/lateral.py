"""Lateral physics -- cornering.

Project rule 14.  A corner asks the car for a centripetal acceleration set by
the track alone:

.. code-block:: text

    a_required = v^2 * |curvature|

and the tyres supply what their friction circle allows.  The interesting part
is that the supply depends on the speed too, because downforce grows with
``v^2``: an F1 car that is grip-limited at 80 km/h can be effectively
unlimited at 300 km/h, where the floor is pressing it down harder than gravity.

That makes the cornering speed limit an **implicit** equation.  It is solved
here by bisection rather than by inverting a simplified formula, because the
tyre's load sensitivity makes the closed-form version wrong in exactly the
high-load regime that matters.

Banking is handled properly rather than as a bonus: a banked corner both
increases vertical load and reduces the lateral force the tyres must generate,
and the two effects have different magnitudes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from ..core.units import MetresPerSecond, MetresPerSecondSquared, Newtons
from ..tyres.state import TyreState
from ..vehicle.model import Vehicle
from .grip import normal_loads, slope_angle

__all__ = [
    "LateralCapability",
    "corner_speed_limit",
    "lateral_capability",
    "max_lateral_acceleration",
    "required_lateral_acceleration",
]

#: Speeds above this are not physically reachable by any current F1 car, so the
#: cornering solver treats a corner still unlimited here as flat out.
_ABSOLUTE_SPEED_CEILING: float = 150.0


def required_lateral_acceleration(speed: float, curvature: float) -> float:
    """Centripetal acceleration a corner demands, m/s^2."""
    return speed * speed * abs(curvature)


@dataclass(frozen=True, slots=True)
class LateralCapability:
    """What the car can do laterally at one speed."""

    speed: MetresPerSecond
    normal_load: Newtons
    friction_coefficient: float
    lateral_force: Newtons
    lateral_acceleration: MetresPerSecondSquared
    downforce: Newtons

    @property
    def lateral_g(self) -> float:
        return self.lateral_acceleration / 9.80665

    def to_dict(self) -> dict[str, Any]:
        return {
            "speed": self.speed,
            "normal_load": self.normal_load,
            "friction_coefficient": self.friction_coefficient,
            "lateral_force": self.lateral_force,
            "lateral_acceleration": self.lateral_acceleration,
            "lateral_g": self.lateral_g,
            "downforce": self.downforce,
        }


def lateral_capability(
    vehicle: Vehicle,
    speed: float,
    air_density: float,
    *,
    mass: float | None = None,
    tyre_state: TyreState | None = None,
    surface_grip: float = 1.0,
    banking: float = 0.0,
    gradient: float = 0.0,
    curvature: float = 0.0,
    longitudinal_force_used: float = 0.0,
    drs_open: bool = False,
) -> LateralCapability:
    """Maximum lateral acceleration available at ``speed``.

    ``curvature`` is used only for the banking geometry -- whether the banking
    is helping or hurting -- not to decide the answer.
    """
    config = vehicle.config
    gravity = config.physics.gravity
    car_mass = vehicle.total_mass() if mass is None else mass
    tyres = tyre_state or TyreState()

    downforce = vehicle.aero.downforce(
        speed, air_density, vehicle.wing_level, drs_open=drs_open
    )

    # Banking helps when it leans the same way the corner turns.
    helpful_bank = abs(banking)
    if curvature != 0.0 and banking != 0.0 and (banking * curvature) < 0.0:
        helpful_bank = -abs(banking)

    # Estimate the cornering acceleration to evaluate the banking term, then
    # settle it: the banking contribution to load depends on it.
    lateral_acceleration = required_lateral_acceleration(speed, curvature)
    for _ in range(4):
        loads = normal_loads(
            vehicle.mass,
            car_mass,
            downforce=downforce,
            downforce_balance_front=vehicle.spec.aero.aero_balance_front,
            gradient=gradient,
            banking=helpful_bank,
            lateral_acceleration=lateral_acceleration,
            longitudinal_acceleration=0.0,
            gravity=gravity,
            enable_load_transfer=False,
        )
        limit = vehicle.tyre_model.grip_limit(
            tyres.compound, loads.total, state=tyres, surface_grip=surface_grip
        )
        available_force = vehicle.tyre_model.available_lateral(
            limit, abs(longitudinal_force_used)
        )
        # Gravity along a banked surface contributes to turning the car.
        gravity_assist = (
            car_mass * gravity * math.cos(slope_angle(gradient)) * math.sin(helpful_bank)
        )
        horizontal_force = available_force * math.cos(helpful_bank) + gravity_assist
        new_acceleration = max(horizontal_force, 0.0) / car_mass
        if abs(new_acceleration - lateral_acceleration) < 1e-6:
            lateral_acceleration = new_acceleration
            break
        lateral_acceleration = new_acceleration

    return LateralCapability(
        speed=speed,
        normal_load=loads.total,
        friction_coefficient=limit.friction_coefficient,
        lateral_force=available_force,
        lateral_acceleration=lateral_acceleration,
        downforce=downforce,
    )


def max_lateral_acceleration(
    vehicle: Vehicle, speed: float, air_density: float, **kwargs: Any
) -> MetresPerSecondSquared:
    """Peak lateral acceleration available at ``speed``, m/s^2."""
    return lateral_capability(vehicle, speed, air_density, **kwargs).lateral_acceleration


def corner_speed_limit(
    vehicle: Vehicle,
    curvature: float,
    air_density: float,
    *,
    mass: float | None = None,
    tyre_state: TyreState | None = None,
    surface_grip: float = 1.0,
    banking: float = 0.0,
    gradient: float = 0.0,
    longitudinal_force_used: float = 0.0,
    drs_open: bool = False,
    max_speed: float = _ABSOLUTE_SPEED_CEILING,
    tolerance: float = 1e-4,
    max_iterations: int = 60,
) -> MetresPerSecond:
    """Fastest speed at which this corner can be held, m/s.

    Returns ``max_speed`` when the corner is flat out -- that is, when downforce
    grows fast enough that the tyres never run out of grip.  A straight
    (``curvature == 0``) is always flat out.

    This is a **grip** limit, not a prediction of how fast the car will go
    through the corner.  It can legitimately come back higher than the car's
    top speed, meaning "the tyres would hold this corner faster than the engine
    can ever push"; the speed profile in Phase 3 takes the minimum of this and
    what the car can actually reach.  Pass ``max_speed`` to bound it when the
    answer is going to be shown to a human.
    """
    if curvature == 0.0:
        return max_speed

    def excess(speed: float) -> float:
        """Demand minus supply.  Positive means the corner is too fast."""
        capability = lateral_capability(
            vehicle,
            speed,
            air_density,
            mass=mass,
            tyre_state=tyre_state,
            surface_grip=surface_grip,
            banking=banking,
            gradient=gradient,
            curvature=curvature,
            longitudinal_force_used=longitudinal_force_used,
            drs_open=drs_open,
        )
        return required_lateral_acceleration(speed, curvature) - capability.lateral_acceleration

    if excess(max_speed) <= 0.0:
        return max_speed
    if excess(tolerance) > 0.0:
        # Not even walking pace is sustainable: no grip at all.
        return 0.0

    low, high = 0.0, max_speed
    for _ in range(max_iterations):
        mid = 0.5 * (low + high)
        if excess(mid) > 0.0:
            high = mid
        else:
            low = mid
        if high - low < tolerance:
            break
    return low
