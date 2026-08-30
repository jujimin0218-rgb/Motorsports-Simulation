"""Driver inputs -- the abstraction between the driver and the physics.

Project rule 19.  The physics does not take orders from a driver object; it
takes throttle, brake and steering.  Keeping that boundary explicit is what
allows the Phase 4 controller below to be replaced by a learned or search-based
driving model later without touching a line of the physics.

The Phase 4 controller is **feed-forward**: it knows the speed the profile says
it should be carrying at the end of this segment, works out the acceleration
that requires, and asks for the pedal position that delivers it.  That is a
legitimate driver model -- it is what a driver who knows the circuit does -- and
it has the property that a perfect driver reproduces the speed profile exactly,
which makes it testable against Phase 3.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..core.interpolation import clamp

__all__ = ["DriverInput", "control_input"]


@dataclass(frozen=True, slots=True)
class DriverInput:
    """What the driver is asking the car to do at one instant."""

    throttle: float = 0.0
    """0 to 1."""

    brake: float = 0.0
    """0 to 1.  Never simultaneously positive with ``throttle`` here; a real
    trail-braking overlap belongs to a future driving model."""

    steering: float = 0.0
    """Normalised steering, -1 (full left) to +1 (full right).

    Phase 4 derives it from the path curvature the car is following.  A driving
    model that chooses its own line will set it directly."""

    gear: int | None = None
    """Selected gear.  ``None`` until the gearbox model arrives in Phase 12;
    the field exists so telemetry and any future model have a place for it."""

    ers_deployment: float = 0.0
    """Fraction of the deployment limit being used.  Driven by the ERS model in
    Phase 5; zero until then."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "throttle": self.throttle,
            "brake": self.brake,
            "steering": self.steering,
            "gear": self.gear,
            "ers_deployment": self.ers_deployment,
        }

    @property
    def is_braking(self) -> bool:
        return self.brake > 0.0


def control_input(
    *,
    speed: float,
    target_speed: float,
    distance_step: float,
    mass: float,
    coast_acceleration: float,
    powertrain_force: float,
    brake_system_force: float,
    curvature: float,
    max_curvature: float,
) -> DriverInput:
    """Work out the pedal position that reaches ``target_speed``.

    The required acceleration follows from the energy relation the speed
    profile itself uses, ``a = (v_target^2 - v^2) / (2 ds)``.

    The pedal is then solved in **force** space, not acceleration space, because
    that is what a pedal actually controls: opening the throttle adds drive
    force on top of whatever drag and gradient are already doing, so the
    quantity to divide by is the force the powertrain can add, not the net
    acceleration it ends up producing.  Getting that wrong makes a perfect
    driver a second a lap slower than the car is capable of, with the error
    concentrated exactly where drag is largest.

    Asking for more than the car has simply saturates the pedal; the tyres then
    decide what actually reaches the road.
    """
    if distance_step <= 0.0:
        return DriverInput()

    required = (target_speed * target_speed - speed * speed) / (2.0 * distance_step)
    steering = 0.0
    if max_curvature > 0.0:
        steering = clamp(curvature / max_curvature, -1.0, 1.0)

    # What the car does with no pedal at all is the baseline; the driver only
    # has to supply the difference.
    delta_force = mass * (required - coast_acceleration)

    if delta_force >= 0.0:
        if powertrain_force <= 0.0:
            return DriverInput(throttle=1.0, steering=steering)
        return DriverInput(
            throttle=clamp(delta_force / powertrain_force, 0.0, 1.0), steering=steering
        )

    if brake_system_force <= 0.0:
        return DriverInput(brake=1.0, steering=steering)
    return DriverInput(
        brake=clamp(-delta_force / brake_system_force, 0.0, 1.0), steering=steering
    )
