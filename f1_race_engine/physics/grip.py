"""Vertical load, and the grip that follows from it.

Everything a tyre can do is set by how hard it is pressed into the road, so
this module answers one question precisely: **what is the normal load?**

Four contributions, each of which matters somewhere on a lap:

* **weight**, reduced by the cosine of the slope -- a car going up Eau Rouge
  presses down slightly less than one on the flat;
* **downforce**, which at 300 km/h is more than twice the car's weight and is
  the reason an F1 car corners the way it does;
* **banking**, which converts part of the cornering demand into vertical load
  rather than lateral demand;
* **load transfer** between the axles, which decides how much the *driven*
  axle can put down.

The last one is why traction is an axle question, not a car question: a
rear-drive car launches on its rear tyres alone.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from ..core.units import Newtons
from ..tyres.compound import TyreCompound
from ..tyres.model import GripLimit, TyreModel
from ..tyres.state import TyreState
from ..vehicle.mass import MassProperties

__all__ = ["AxleLoads", "normal_loads", "slope_angle", "grip_limits"]


def slope_angle(gradient: float) -> float:
    """Road slope angle, radians, from a dimensionless gradient ``dz/ds``."""
    return math.atan(gradient)


@dataclass(frozen=True, slots=True)
class AxleLoads:
    """Vertical load on the car and on each axle, N."""

    total: Newtons
    front: Newtons
    rear: Newtons
    weight_component: Newtons
    downforce: Newtons
    banking_component: Newtons
    transfer: Newtons
    """Load moved from the front axle to the rear, N.  Positive under
    acceleration."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "front": self.front,
            "rear": self.rear,
            "weight_component": self.weight_component,
            "downforce": self.downforce,
            "banking_component": self.banking_component,
            "transfer": self.transfer,
        }


def normal_loads(
    mass_properties: MassProperties,
    mass: float,
    *,
    downforce: Newtons = 0.0,
    downforce_balance_front: float = 0.44,
    gradient: float = 0.0,
    banking: float = 0.0,
    lateral_acceleration: float = 0.0,
    longitudinal_acceleration: float = 0.0,
    gravity: float = 9.80665,
    enable_load_transfer: bool = True,
) -> AxleLoads:
    """Vertical load on the tyres.

    ``banking`` is signed the same way as curvature, and
    ``lateral_acceleration`` should carry the sign of the corner, so that a
    corner banked the right way increases load and one banked the wrong way
    reduces it.
    """
    pitch = slope_angle(gradient)
    bank = banking

    weight_component = mass * gravity * math.cos(pitch) * math.cos(bank)

    # A banked corner leans part of the cornering demand into the road.
    banking_component = mass * lateral_acceleration * math.sin(bank)

    total = weight_component + downforce * math.cos(bank) + banking_component
    total = max(total, 0.0)

    transfer = 0.0
    if enable_load_transfer:
        transfer = mass_properties.load_transfer(longitudinal_acceleration, mass)

    static_front = weight_component * mass_properties.weight_distribution_front
    static_rear = weight_component * mass_properties.weight_distribution_rear
    aero_front = downforce * math.cos(bank) * downforce_balance_front
    aero_rear = downforce * math.cos(bank) * (1.0 - downforce_balance_front)
    bank_front = banking_component * mass_properties.weight_distribution_front
    bank_rear = banking_component * mass_properties.weight_distribution_rear

    front = max(static_front + aero_front + bank_front - transfer, 0.0)
    rear = max(static_rear + aero_rear + bank_rear + transfer, 0.0)

    return AxleLoads(
        total=total,
        front=front,
        rear=rear,
        weight_component=weight_component,
        downforce=downforce,
        banking_component=banking_component,
        transfer=transfer,
    )


def grip_limits(
    tyre_model: TyreModel,
    compound: TyreCompound,
    loads: AxleLoads,
    *,
    tyre_state: TyreState | None = None,
    surface_grip: float = 1.0,
) -> tuple[GripLimit, GripLimit, GripLimit]:
    """Friction circles for the whole car, the front axle and the rear axle."""
    return (
        tyre_model.grip_limit(
            compound, loads.total, state=tyre_state, surface_grip=surface_grip
        ),
        tyre_model.grip_limit(
            compound, loads.front, state=tyre_state, surface_grip=surface_grip
        ),
        tyre_model.grip_limit(
            compound, loads.rear, state=tyre_state, surface_grip=surface_grip
        ),
    )
