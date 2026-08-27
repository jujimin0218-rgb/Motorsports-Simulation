"""Longitudinal physics -- how the car speeds up and slows down.

The force balance of project rule 13:

.. code-block:: text

    F_net = F_drive - F_drag - F_rolling - F_brake - m * g * sin(theta)
    a     = F_net / m

Every term is a real force with a real source, so the behaviour that follows is
not tuned: a heavier car accelerates less because ``m`` appears twice, a
draggier car has a lower top speed because ``F_drag`` grows as ``v^2``, and a
car on a slope loses or gains exactly ``m * g * sin(theta)``.

Two limits sit on top of the balance, and which one binds is what makes a lap
interesting:

* **Drive** is capped by the powertrain *and* by what the driven axle can put
  down.  Traction is implicit -- grip depends on load, load depends on
  acceleration, acceleration depends on grip -- so it is solved by fixed-point
  iteration.
* **Braking** is capped by the brake system *and* by tyre friction.  On an F1
  car the tyres always lose that argument, which is why braking performance is
  a grip question.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from ..core.config import SimulationConfig
from ..core.interpolation import clamp
from ..core.units import MetresPerSecondSquared, Newtons
from ..tyres.state import TyreState
from ..vehicle.model import Vehicle
from .grip import AxleLoads, normal_loads, slope_angle

__all__ = [
    "LongitudinalForces",
    "longitudinal_forces",
    "max_acceleration",
    "max_deceleration",
    "traction_limited_force",
]


@dataclass(frozen=True, slots=True)
class LongitudinalForces:
    """The complete longitudinal force balance at one instant, in newtons."""

    drive: Newtons
    drag: Newtons
    rolling_resistance: Newtons
    gradient: Newtons
    """Component of weight along the road.  Negative going uphill."""

    brake: Newtons
    net: Newtons
    acceleration: MetresPerSecondSquared
    loads: AxleLoads

    @property
    def resistance(self) -> Newtons:
        """Everything opposing motion apart from the brakes, N."""
        return self.drag + self.rolling_resistance - self.gradient

    def to_dict(self) -> dict[str, Any]:
        return {
            "drive": self.drive,
            "drag": self.drag,
            "rolling_resistance": self.rolling_resistance,
            "gradient": self.gradient,
            "brake": self.brake,
            "net": self.net,
            "acceleration": self.acceleration,
            "loads": self.loads.to_dict(),
        }


def _gravity(config: SimulationConfig) -> float:
    return config.physics.gravity


def traction_limited_force(
    vehicle: Vehicle,
    speed: float,
    air_density: float,
    *,
    mass: float,
    tyre_state: TyreState | None = None,
    surface_grip: float = 1.0,
    gradient: float = 0.0,
    banking: float = 0.0,
    lateral_acceleration: float = 0.0,
    lateral_force_used: float = 0.0,
    drs_open: bool = False,
) -> Newtons:
    """Maximum drive force the rear tyres can transmit, N.

    Implicit, and solved as such: more acceleration transfers more load onto
    the driven axle, which raises the grip available, which allows more
    acceleration.  A handful of fixed-point passes converge quickly because the
    feedback gain ``mu * h_cg / wheelbase`` is well under one.

    Cornering is charged as a **fraction of the whole car's friction circle**,
    not as a force against the rear axle's own circle.  That consistency
    matters: because the friction coefficient falls with load, two axles
    evaluated separately have more grip between them than the same load
    evaluated as one lump.  Mixing the two bases would leave a car sitting at
    its cornering limit still believing it had drive available -- and the speed
    profile would then accelerate through an apex.
    """
    config = vehicle.config
    tyres = tyre_state or TyreState()
    compound = tyres.compound
    downforce = vehicle.aero.downforce(
        speed, air_density, vehicle.wing_level, drs_open=drs_open
    )
    balance = vehicle.spec.aero.aero_balance_front

    acceleration = 0.0
    force = 0.0
    for _ in range(config.powertrain.traction_solver_iterations):
        loads = normal_loads(
            vehicle.mass,
            mass,
            downforce=downforce,
            downforce_balance_front=balance,
            gradient=gradient,
            banking=banking,
            lateral_acceleration=lateral_acceleration,
            longitudinal_acceleration=acceleration,
            gravity=_gravity(config),
            enable_load_transfer=config.powertrain.longitudinal_load_transfer,
        )
        rear_limit = vehicle.tyre_model.grip_limit(
            compound, loads.rear, state=tyres, surface_grip=surface_grip
        )
        # How much of the car's total friction circle cornering is already
        # spending.  Evaluated on the same lumped basis as the lateral model.
        total_limit = vehicle.tyre_model.grip_limit(
            compound, loads.total, state=tyres, surface_grip=surface_grip
        )
        lateral_used = abs(lateral_force_used)
        if total_limit.capacity > 0.0 and lateral_used > 0.0:
            exponent = config.tyres.combined_grip_exponent
            utilisation = min(lateral_used / total_limit.capacity, 1.0)
            reserve = (1.0 - utilisation**exponent) ** (1.0 / exponent)
            available = rear_limit.capacity * reserve
        else:
            available = rear_limit.capacity
        if available <= force and force > 0.0:
            force = available
            break
        force = available
        acceleration = force / mass
    return max(force, 0.0)


def longitudinal_forces(
    vehicle: Vehicle,
    speed: float,
    air_density: float,
    *,
    mass: float | None = None,
    throttle: float = 0.0,
    brake: float = 0.0,
    gradient: float = 0.0,
    banking: float = 0.0,
    tyre_state: TyreState | None = None,
    surface_grip: float = 1.0,
    lateral_acceleration: float = 0.0,
    lateral_force_used: float = 0.0,
    drs_open: bool = False,
) -> LongitudinalForces:
    """Resolve the full longitudinal force balance.

    ``throttle`` and ``brake`` are demands in ``[0, 1]``; both limits are
    applied, so asking for more than the tyres can deliver simply yields the
    tyres' answer.
    """
    config = vehicle.config
    gravity = _gravity(config)
    car_mass = vehicle.total_mass() if mass is None else mass
    tyres = tyre_state or TyreState()
    throttle = clamp(throttle, 0.0, 1.0)
    brake = clamp(brake, 0.0, 1.0)

    downforce = vehicle.aero.downforce(
        speed, air_density, vehicle.wing_level, drs_open=drs_open
    )
    drag = vehicle.aero.drag(speed, air_density, vehicle.wing_level, drs_open=drs_open)

    pitch = slope_angle(gradient)
    gradient_force = -car_mass * gravity * math.sin(pitch)

    drive = 0.0
    if throttle > 0.0:
        powertrain = vehicle.power_unit.tractive_force(speed, throttle=throttle)
        traction = traction_limited_force(
            vehicle,
            speed,
            air_density,
            mass=car_mass,
            tyre_state=tyres,
            surface_grip=surface_grip,
            gradient=gradient,
            banking=banking,
            lateral_acceleration=lateral_acceleration,
            lateral_force_used=lateral_force_used,
            drs_open=drs_open,
        )
        drive = min(powertrain, traction)

    # Load state used for rolling resistance and the braking limit.
    loads = normal_loads(
        vehicle.mass,
        car_mass,
        downforce=downforce,
        downforce_balance_front=vehicle.spec.aero.aero_balance_front,
        gradient=gradient,
        banking=banking,
        lateral_acceleration=lateral_acceleration,
        longitudinal_acceleration=drive / car_mass if drive else 0.0,
        gravity=gravity,
        enable_load_transfer=config.powertrain.longitudinal_load_transfer,
    )

    rolling = 0.0
    if speed > config.physics.epsilon:
        rolling = vehicle.tyre_model.rolling_resistance_force(
            tyres.compound, loads.total
        )

    brake_force = 0.0
    if brake > 0.0:
        grip = vehicle.tyre_model.grip_limit(
            tyres.compound, loads.total, state=tyres, surface_grip=surface_grip
        )
        grip_limit = vehicle.tyre_model.available_longitudinal(
            grip, abs(lateral_force_used)
        )
        brake_force = min(vehicle.brakes.brake_force(brake), grip_limit)

    net = drive - drag - rolling - brake_force + gradient_force
    return LongitudinalForces(
        drive=drive,
        drag=drag,
        rolling_resistance=rolling,
        gradient=gradient_force,
        brake=brake_force,
        net=net,
        acceleration=net / car_mass,
        loads=loads,
    )


def max_acceleration(
    vehicle: Vehicle, speed: float, air_density: float, **kwargs: Any
) -> MetresPerSecondSquared:
    """Best longitudinal acceleration available at ``speed``, m/s^2."""
    return longitudinal_forces(
        vehicle, speed, air_density, throttle=1.0, brake=0.0, **kwargs
    ).acceleration


def max_deceleration(
    vehicle: Vehicle, speed: float, air_density: float, **kwargs: Any
) -> MetresPerSecondSquared:
    """Hardest braking available at ``speed``, m/s^2 (a positive number).

    Drag and rolling resistance help, which is why an F1 car decelerates hardest
    at the highest speed -- and why braking distance does not scale with ``v^2``
    the way a road car's does.
    """
    forces = longitudinal_forces(
        vehicle, speed, air_density, throttle=0.0, brake=1.0, **kwargs
    )
    return -forces.acceleration
