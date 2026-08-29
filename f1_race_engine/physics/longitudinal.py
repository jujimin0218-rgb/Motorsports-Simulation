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
  a grip question -- and, like traction, it is an *axle* question.  The brake
  bias is fixed while the car is stopping, so the axle that saturates first
  ends the argument for both of them.  Braking is therefore solved the same
  implicit way as traction, in the opposite direction: decelerating harder
  moves load onto the front axle, which can then take more of the bias.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable

from ..core.config import SimulationConfig
from ..core.interpolation import clamp
from ..core.units import MetresPerSecondSquared, Newtons
from ..tyres.state import TyreState
from ..vehicle.model import Vehicle
from .grip import AxleLoads, normal_loads, normal_loads_core, road_trigonometry

__all__ = [
    "LongitudinalForces",
    "braking_limited_force",
    "longitudinal_acceleration",
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
    water_depth: float = 0.0,
    headwind: float = 0.0,
    downforce_factor: float = 1.0,
    ceiling: float | None = None,
    downforce: float | None = None,
    road_trig: tuple[float, float, float] | None = None,
) -> Newtons:
    """Maximum drive force the rear tyres can transmit, N.

    Implicit, and solved as such: more acceleration transfers more load onto
    the driven axle, which raises the grip available, which allows more
    acceleration.  A handful of fixed-point passes converge quickly because the
    feedback gain ``mu * h_cg / wheelbase`` is well under one.

    ``ceiling`` is a force the caller is going to take the minimum against
    anyway -- the engine's own output, usually.  The iteration only ever climbs
    (more acceleration transfers more load onto the driven axle, which can only
    raise the grip), so the moment a pass clears the ceiling the answer to
    ``min(ceiling, traction)`` is settled and the remaining passes cannot change
    it.  That is exact, not an approximation, and it skips the solve on most of
    a lap, where the engine and not the tyre is what limits the car.

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
    if downforce is None:
        air_speed = max(speed + headwind, 0.0)
        downforce = downforce_factor * vehicle.aero.downforce(
            air_speed, air_density, vehicle.wing_level, drs_open=drs_open
        )
    balance = vehicle.spec.aero.aero_balance_front

    acceleration = 0.0
    force = 0.0
    tolerance = config.powertrain.traction_solver_tolerance
    # Everything the loop does not change, looked up once: it runs up to a
    # dozen times per query and the query runs once per segment per pass.
    mass_properties = vehicle.mass
    tyre_model = vehicle.tyre_model
    gravity = config.physics.gravity
    transfer_enabled = config.powertrain.longitudinal_load_transfer
    exponent = config.tyres.combined_grip_exponent
    lateral_used = abs(lateral_force_used)
    cos_pitch, cos_bank, sin_bank = road_trig or road_trigonometry(gradient, banking)
    for _ in range(config.powertrain.traction_solver_iterations):
        total_load, _front, rear_load, _w, _b, _t = normal_loads_core(
            mass_properties,
            mass,
            downforce,
            balance,
            cos_pitch,
            cos_bank,
            sin_bank,
            lateral_acceleration,
            acceleration,
            gravity,
            transfer_enabled,
        )
        rear_capacity = tyre_model.grip_capacity(
            compound, rear_load, tyres=2, state=tyres, surface_grip=surface_grip,
            water_depth=water_depth, speed=speed,
        )
        # How much of the car's total friction circle cornering is already
        # spending.  Evaluated on the same lumped basis as the lateral model.
        available = rear_capacity
        if lateral_used > 0.0:
            total_capacity = tyre_model.grip_capacity(
                compound, total_load, state=tyres, surface_grip=surface_grip,
                water_depth=water_depth, speed=speed,
            )
            if total_capacity > 0.0:
                utilisation = min(lateral_used / total_capacity, 1.0)
                reserve = (1.0 - utilisation**exponent) ** (1.0 / exponent)
                available = rear_capacity * reserve
        if ceiling is not None and available >= ceiling:
            return ceiling
        settled = abs(available - force) <= tolerance * max(available, 1.0)
        force = available
        if settled:
            break
        acceleration = force / mass
    return max(force, 0.0)


def braking_limited_force(
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
    water_depth: float = 0.0,
    headwind: float = 0.0,
    downforce_factor: float = 1.0,
    downforce: float | None = None,
    road_trig: tuple[float, float, float] | None = None,
) -> Newtons:
    """Maximum retarding force the tyres can transmit, N.

    Braking is an axle question for the same reason traction is, and the
    argument is sharper: the brake bias is *fixed* while the car is stopping.
    A driver cannot send more effort to the axle that still has grip, so the
    first axle to reach its friction limit ends the braking for both of them::

        F_total = min( F_front_limit / bias ,  F_rear_limit / (1 - bias) )

    Treating the car as one lump instead -- charging the total retarding force
    against the total load -- quietly assumes a bias that follows the load
    transfer around, which no car has.  It overstates braking badly at high
    speed, where downforce is large and the transfer with it: it lets the front
    axle carry far more than its share of the effort, and the deceleration that
    comes out exceeds anything a real Formula 1 car achieves.

    Like traction the problem is implicit, and in the opposite direction:
    decelerating harder moves load onto the front axle, which raises the front
    limit and lowers the rear one.  The two feedbacks pull opposite ways, so
    each axle is solved on its own and the smaller answer wins -- see the
    comment below for why iterating on the minimum instead does not converge.

    Cornering is charged as a fraction of the whole car's friction circle, the
    same basis :func:`traction_limited_force` uses, so that a car at its
    cornering limit has no braking left on either axle.
    """
    config = vehicle.config
    tyres = tyre_state or TyreState()
    compound = tyres.compound
    if downforce is None:
        air_speed = max(speed + headwind, 0.0)
        downforce = downforce_factor * vehicle.aero.downforce(
            air_speed, air_density, vehicle.wing_level, drs_open=drs_open
        )
    bias = vehicle.brake_bias_front
    transfer_enabled = config.powertrain.longitudinal_load_transfer

    # Only the transfer term depends on how hard the car is stopping, so the
    # standing loads are computed once and the iteration just moves load
    # between the axles.  That keeps the solve to a handful of friction
    # lookups, which matters: this runs for every segment of every backward
    # pass of every lap of every car.
    mass_properties = vehicle.mass
    cos_pitch, cos_bank, sin_bank = road_trig or road_trigonometry(gradient, banking)
    base_total, base_front, base_rear, _w, _b, _t = normal_loads_core(
        mass_properties,
        mass,
        downforce,
        vehicle.spec.aero.aero_balance_front,
        cos_pitch,
        cos_bank,
        sin_bank,
        lateral_acceleration,
        0.0,
        config.physics.gravity,
        False,
    )

    tyre_model = vehicle.tyre_model
    cg_height = mass_properties.cg_height
    wheelbase = mass_properties.wheelbase

    def axle_capacity(load: float) -> float:
        return tyre_model.grip_capacity(
            compound, load, tyres=2, state=tyres, surface_grip=surface_grip,
            water_depth=water_depth, speed=speed,
        )

    # Load transfer moves grip between the axles but not the total, so the
    # cornering reserve is the same on every pass and is computed once.
    reserve = 1.0
    lateral_used = abs(lateral_force_used)
    if lateral_used > 0.0:
        total_capacity = tyre_model.grip_capacity(
            compound, base_total, state=tyres, surface_grip=surface_grip,
            water_depth=water_depth, speed=speed,
        )
        if total_capacity <= 0.0:
            return 0.0
        exponent = config.tyres.combined_grip_exponent
        utilisation = min(lateral_used / total_capacity, 1.0)
        reserve = (1.0 - utilisation**exponent) ** (1.0 / exponent)
        if reserve <= 0.0:
            return 0.0

    # The same expression MassProperties.load_transfer evaluates, in the same
    # order, so the answer is bit for bit the one the method gives -- floating
    # point multiplication does not associate, and a solver that runs to a
    # tolerance is exactly where that would show.
    def front_branch(deceleration: float) -> float:
        shift = mass * deceleration * cg_height / wheelbase
        return axle_capacity(max(base_front + shift, 0.0)) * reserve / bias

    def rear_branch(deceleration: float) -> float:
        shift = mass * deceleration * cg_height / wheelbase
        return axle_capacity(max(base_rear - shift, 0.0)) * reserve / (1.0 - bias)

    if not transfer_enabled:
        limits = []
        if bias > 0.0:
            limits.append(front_branch(0.0))
        if bias < 1.0:
            limits.append(rear_branch(0.0))
        return max(min(limits), 0.0) if limits else 0.0

    # The two axles are solved *separately* and the smaller answer wins.
    #
    # That is not a shortcut, it is what makes the solve well behaved.  Braking
    # harder loads the front and unloads the rear, so the front branch grows
    # with the answer and the rear branch shrinks; each on its own is a
    # contraction and settles in a few passes.  Iterating on the minimum of the
    # two instead makes the map jump between branches from pass to pass and it
    # never settles at all.  Both branches are monotone in the force, so each
    # admits exactly one crossing, and every force below both crossings
    # satisfies both axles -- so the smaller crossing is the limit.
    tolerance = config.powertrain.traction_solver_tolerance
    iterations = config.powertrain.traction_solver_iterations
    limit = math.inf
    if bias > 0.0:
        limit = min(limit, _axle_braking_crossing(front_branch, mass, tolerance, iterations))
    if bias < 1.0:
        limit = min(limit, _axle_braking_crossing(rear_branch, mass, tolerance, iterations))
    return max(limit, 0.0) if math.isfinite(limit) else 0.0


def _axle_braking_crossing(
    branch: Callable[[float], float],
    mass: float,
    tolerance: float,
    max_iterations: int,
) -> Newtons:
    """Solve ``F = branch(F / mass)`` for one axle.

    The branch is monotone in the force and its slope is well under one, so a
    secant step converges in two or three evaluations where plain substitution
    needs eight.  This is called for every segment of every backward pass, so
    the difference is worth the ten lines.
    """
    previous_force = 0.0
    previous_residual = branch(0.0)
    force = previous_residual
    for _ in range(max_iterations):
        value = branch(force / mass)
        residual = value - force
        if abs(residual) <= tolerance * max(abs(value), 1.0):
            return value
        denominator = residual - previous_residual
        candidate = value
        if denominator != 0.0:
            secant = force - residual * (force - previous_force) / denominator
            if math.isfinite(secant) and secant >= 0.0:
                candidate = secant
        previous_force, previous_residual = force, residual
        force = candidate
    return force


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
    ers_power: float = 0.0,
    water_depth: float = 0.0,
    headwind: float = 0.0,
    downforce_factor: float = 1.0,
    drag_factor: float = 1.0,
) -> LongitudinalForces:
    """Resolve the full longitudinal force balance.

    ``ers_power`` is electrical power reaching the wheels, added to what the
    engine makes.  It is still subject to the traction limit -- deploying into a
    slow corner exit only spins the wheels, which is why the energy is worth
    more on a straight.

    ``water_depth`` is the standing water the tyres have to clear; what that
    costs depends on the tread, and the tyre model answers it.

    ``downforce_factor`` and ``drag_factor`` are what the air the car is
    driving through has been done to -- by the wake of a car in front, which is
    the only thing that currently does it.  They are multipliers on the two
    aerodynamic forces and nothing else, so what dirty air *costs* is worked
    out by the same model that decides everything else, and it comes out
    different at a circuit with fast corners than at one without.

    ``headwind`` is the wind component opposing the car, m/s.  Only the *aero*
    forces see it -- a headwind changes the air the car is driving through, not
    how fast the road is going past -- which is why a lap into a headwind and
    back out of it is slower than the same lap in still air rather than being a
    wash.

    ``throttle`` and ``brake`` are demands in ``[0, 1]``; both limits are
    applied, so asking for more than the tyres can deliver simply yields the
    tyres' answer.
    """
    (
        drive,
        drag,
        rolling,
        gradient_force,
        brake_force,
        net,
        car_mass,
        load_values,
        downforce,
    ) = _resolve_longitudinal(
        vehicle, speed, air_density, mass, throttle, brake, gradient, banking,
        tyre_state, surface_grip, lateral_acceleration, lateral_force_used,
        drs_open, ers_power, water_depth, headwind, downforce_factor, drag_factor,
    )
    total, front, rear, weight_component, banking_component, transfer = load_values
    return LongitudinalForces(
        drive=drive,
        drag=drag,
        rolling_resistance=rolling,
        gradient=gradient_force,
        brake=brake_force,
        net=net,
        acceleration=net / car_mass,
        loads=AxleLoads(
            total=total,
            front=front,
            rear=rear,
            weight_component=weight_component,
            downforce=downforce,
            banking_component=banking_component,
            transfer=transfer,
        ),
    )


def longitudinal_acceleration(
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
    ers_power: float = 0.0,
    water_depth: float = 0.0,
    headwind: float = 0.0,
    downforce_factor: float = 1.0,
    drag_factor: float = 1.0,
) -> MetresPerSecondSquared:
    """Net longitudinal acceleration alone, m/s^2.

    The same force balance :func:`longitudinal_forces` resolves -- it is the
    same code -- returning only the number the speed profile actually reads.
    The profile asks this question tens of thousands of times a lap and throws
    the breakdown away every time, and two frozen dataclasses per question is a
    real share of the cost of a lap.
    """
    net, car_mass = _resolve_longitudinal(
        vehicle, speed, air_density, mass, throttle, brake, gradient, banking,
        tyre_state, surface_grip, lateral_acceleration, lateral_force_used,
        drs_open, ers_power, water_depth, headwind, downforce_factor, drag_factor,
    )[5:7]
    return net / car_mass


def _resolve_longitudinal(
    vehicle: Vehicle,
    speed: float,
    air_density: float,
    mass: float | None,
    throttle: float,
    brake: float,
    gradient: float,
    banking: float,
    tyre_state: TyreState | None,
    surface_grip: float,
    lateral_acceleration: float,
    lateral_force_used: float,
    drs_open: bool,
    ers_power: float,
    water_depth: float,
    headwind: float,
    downforce_factor: float,
    drag_factor: float,
) -> tuple[
    float, float, float, float, float, float, float,
    tuple[float, float, float, float, float, float], float,
]:
    """The force balance itself, as plain numbers.

    Positional arguments and a tuple result: this is the innermost thing in the
    engine and it is called once per corrector step per segment per pass.
    """
    config = vehicle.config
    gravity = config.physics.gravity
    car_mass = vehicle.total_mass() if mass is None else mass
    tyres = tyre_state or TyreState()
    throttle = clamp(throttle, 0.0, 1.0)
    brake = clamp(brake, 0.0, 1.0)

    air_speed = max(speed + headwind, 0.0)
    raw_downforce, raw_drag = vehicle.aero.downforce_and_drag(
        air_speed, air_density, vehicle.wing_level, drs_open=drs_open
    )
    downforce = downforce_factor * raw_downforce
    drag = drag_factor * raw_drag

    trig = road_trigonometry(gradient, banking)
    cos_pitch, cos_bank, sin_bank = trig
    gradient_force = -car_mass * gravity * math.sin(math.atan(gradient))

    drive = 0.0
    if throttle > 0.0:
        powertrain = vehicle.power_unit.tractive_force(speed, throttle=throttle)
        if ers_power > 0.0:
            effective_speed = max(speed, config.powertrain.min_tractive_speed)
            powertrain += ers_power * min(throttle, 1.0) / effective_speed
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
            water_depth=water_depth,
            headwind=headwind,
            downforce_factor=downforce_factor,
            ceiling=powertrain,
            downforce=downforce,
            road_trig=trig,
        )
        drive = min(powertrain, traction)

    # Load state used for rolling resistance and the braking limit.
    load_values = normal_loads_core(
        vehicle.mass,
        car_mass,
        downforce,
        vehicle.spec.aero.aero_balance_front,
        cos_pitch,
        cos_bank,
        sin_bank,
        lateral_acceleration,
        drive / car_mass if drive else 0.0,
        gravity,
        config.powertrain.longitudinal_load_transfer,
    )

    rolling = 0.0
    if speed > config.physics.epsilon:
        rolling = vehicle.tyre_model.rolling_resistance_force(
            tyres.compound, load_values[0]
        )

    brake_force = 0.0
    if brake > 0.0:
        grip_limit = braking_limited_force(
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
            water_depth=water_depth,
            headwind=headwind,
            downforce_factor=downforce_factor,
            downforce=downforce,
            road_trig=trig,
        )
        brake_force = min(vehicle.brakes.brake_force(brake), grip_limit)

    net = drive - drag - rolling - brake_force + gradient_force
    return (
        drive, drag, rolling, gradient_force, brake_force, net, car_mass,
        load_values, downforce,
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
