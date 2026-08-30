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

__all__ = [
    "AxleLoads",
    "grip_limits",
    "lateral_transfer_factor",
    "normal_loads",
    "normal_loads_core",
    "road_trigonometry",
    "slope_angle",
]


def _axle_transfer_factor(shift: float, exponent: float) -> float:
    """Grip left on one axle when load has moved across it by ``shift``.

    ``shift`` is the load moved onto the outside tyre as a share of what it was
    carrying, so 1.0 is the point where the inside wheel lifts.
    """
    shift = min(max(shift, 0.0), 1.0)
    outside = (1.0 + shift) ** exponent
    inside = (1.0 - shift) ** exponent if shift < 1.0 else 0.0
    return 0.5 * (outside + inside)


def lateral_transfer_factor(
    total_load: float,
    transfer: float,
    load_sensitivity: float,
    *,
    front_load: float | None = None,
    rear_load: float | None = None,
    roll_stiffness_front: float | None = None,
) -> float:
    """Share of cornering grip left after load moves onto the outside tyres.

    Friction coefficient falls with load, so a given total load buys less grip
    split unevenly than shared evenly.  Cornering does exactly that split, and
    the harder the car corners the worse it gets -- which is why a wide car
    with a low centre of gravity corners better than a narrow tall one carrying
    the same downforce.

    ``capacity ~ N^(1 - k)`` per contact patch, so the factor is scale free and
    depends only on how far the load has moved as a share of what each tyre was
    carrying.  Past the point where the inside wheels lift they carry nothing
    and stop contributing, which the model reaches by itself.

    Given the axle loads and a roll stiffness distribution, the transfer is
    split between the axles the way the springs and bars actually split it, and
    each axle is charged for its own share.  That matters because the same
    penalty is concave: an axle taking more than its share of the transfer
    loses more grip than the other one gains back, so **any** distribution away
    from the load split costs the car total grip.  Which is the real reason a
    setup change at one end is felt as a balance change rather than as free
    lap time, and why the stiff end is the end that lets go first.
    """
    if total_load <= 0.0 or transfer <= 0.0 or load_sensitivity <= 0.0:
        return 1.0
    exponent = 1.0 - load_sensitivity

    if (
        front_load is None
        or rear_load is None
        or roll_stiffness_front is None
        or front_load <= 0.0
        or rear_load <= 0.0
    ):
        # No distribution supplied: the transfer splits evenly, which is what
        # a car whose roll stiffness matches its weight distribution does.
        return _axle_transfer_factor(2.0 * transfer / total_load, exponent)

    share = min(max(roll_stiffness_front, 0.0), 1.0)
    front = _axle_transfer_factor(share * transfer / (front_load / 2.0), exponent)
    rear = _axle_transfer_factor(
        (1.0 - share) * transfer / (rear_load / 2.0), exponent
    )
    # Steady state: the axles corner together, so the car's capacity is the sum
    # of theirs and the combination is weighted by the load each one carries.
    return (front_load * front + rear_load * rear) / (front_load + rear_load)


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


def road_trigonometry(gradient: float, banking: float) -> tuple[float, float, float]:
    """``(cos pitch, cos bank, sin bank)`` for a piece of road.

    Split out because every solver in the engine settles a loop against a
    *fixed* piece of road: the gradient and banking under the car do not change
    while the acceleration converges, so the three values are worth exactly one
    evaluation per query rather than one per pass.
    """
    return math.cos(math.atan(gradient)), math.cos(banking), math.sin(banking)


def normal_loads_core(
    mass_properties: MassProperties,
    mass: float,
    downforce: Newtons,
    downforce_balance_front: float,
    cos_pitch: float,
    cos_bank: float,
    sin_bank: float,
    lateral_acceleration: float,
    longitudinal_acceleration: float,
    gravity: float,
    enable_load_transfer: bool,
) -> tuple[float, float, float, float, float, float]:
    """The load calculation itself, as a tuple of plain floats.

    ``(total, front, rear, weight_component, banking_component, transfer)``.

    The solvers that call this run it a few hundred thousand times per lap and
    read three of the six numbers, so they take it in this form and skip
    building a frozen dataclass they would immediately unpack.  Positional
    arguments, and the road's trigonometry already evaluated by
    :func:`road_trigonometry`, for the same reason.  :func:`normal_loads` is
    the same calculation with an angle-shaped signature and the result wrapped
    up, and is what everything outside the solvers uses.
    """
    weight_component = mass * gravity * cos_pitch * cos_bank

    # A banked corner leans part of the cornering demand into the road.
    banking_component = mass * lateral_acceleration * sin_bank

    aero = downforce * cos_bank
    total = weight_component + aero + banking_component
    if total < 0.0:
        total = 0.0

    transfer = 0.0
    if enable_load_transfer:
        transfer = (
            mass
            * longitudinal_acceleration
            * mass_properties.cg_height
            / mass_properties.wheelbase
        )

    front_share = mass_properties.weight_distribution_front
    rear_share = mass_properties.weight_distribution_rear
    front = (
        weight_component * front_share
        + aero * downforce_balance_front
        + banking_component * front_share
        - transfer
    )
    rear = (
        weight_component * rear_share
        + aero * (1.0 - downforce_balance_front)
        + banking_component * rear_share
        + transfer
    )
    if front < 0.0:
        front = 0.0
    if rear < 0.0:
        rear = 0.0

    return total, front, rear, weight_component, banking_component, transfer


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
    cos_pitch, cos_bank, sin_bank = road_trigonometry(gradient, banking)
    total, front, rear, weight_component, banking_component, transfer = (
        normal_loads_core(
            mass_properties,
            mass,
            downforce,
            downforce_balance_front,
            cos_pitch,
            cos_bank,
            sin_bank,
            lateral_acceleration,
            longitudinal_acceleration,
            gravity,
            enable_load_transfer,
        )
    )
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
