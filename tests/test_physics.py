"""The physics core: loads, the force balance, and cornering."""

from __future__ import annotations

import math

import pytest

from f1_race_engine.core.units import kph_to_ms, ms_to_kph
from f1_race_engine.physics import (
    corner_speed_limit,
    lateral_capability,
    longitudinal_forces,
    max_acceleration,
    max_deceleration,
    max_lateral_acceleration,
    normal_loads,
    required_lateral_acceleration,
    braking_limited_force,
    slope_angle,
    traction_limited_force,
)
from f1_race_engine.tyres import TyreState
from f1_race_engine.vehicle import MassProperties


# -- normal load -------------------------------------------------------------


def test_static_load_is_weight():
    mass = MassProperties()
    loads = normal_loads(mass, 900.0, gravity=9.81)
    assert loads.total == pytest.approx(900.0 * 9.81)
    assert loads.front + loads.rear == pytest.approx(loads.total)


def test_weight_distribution_splits_static_load():
    mass = MassProperties(weight_distribution_front=0.45)
    loads = normal_loads(mass, 900.0, enable_load_transfer=False)
    assert loads.front / loads.total == pytest.approx(0.45)


def test_downforce_adds_to_normal_load():
    mass = MassProperties()
    without = normal_loads(mass, 900.0)
    with_aero = normal_loads(mass, 900.0, downforce=20_000.0)
    assert with_aero.total == pytest.approx(without.total + 20_000.0)


def test_aero_balance_splits_downforce_separately_from_weight():
    """Aero balance and weight distribution are different numbers, and the
    model must not conflate them."""
    mass = MassProperties(weight_distribution_front=0.45)
    loads = normal_loads(
        mass, 900.0, downforce=20_000.0, downforce_balance_front=0.30,
        enable_load_transfer=False,
    )
    static = 900.0 * 9.80665
    assert loads.front == pytest.approx(static * 0.45 + 20_000.0 * 0.30)


def test_uphill_reduces_normal_load():
    mass = MassProperties()
    flat = normal_loads(mass, 900.0)
    steep = normal_loads(mass, 900.0, gradient=0.18)
    assert steep.total < flat.total


def test_acceleration_transfers_load_to_the_rear():
    mass = MassProperties()
    static = normal_loads(mass, 900.0, longitudinal_acceleration=0.0)
    accelerating = normal_loads(mass, 900.0, longitudinal_acceleration=10.0)
    braking = normal_loads(mass, 900.0, longitudinal_acceleration=-10.0)
    assert accelerating.rear > static.rear
    assert accelerating.front < static.front
    assert braking.front > static.front
    # Transfer conserves total load.
    assert accelerating.front + accelerating.rear == pytest.approx(static.total)


def test_load_transfer_can_be_switched_off():
    mass = MassProperties()
    loads = normal_loads(
        mass, 900.0, longitudinal_acceleration=10.0, enable_load_transfer=False
    )
    assert loads.transfer == 0.0


def test_banking_adds_normal_load_when_it_helps():
    mass = MassProperties()
    flat = normal_loads(mass, 900.0, lateral_acceleration=30.0, banking=0.0)
    banked = normal_loads(mass, 900.0, lateral_acceleration=30.0, banking=0.15)
    assert banked.total > flat.total


def test_loads_never_go_negative():
    mass = MassProperties()
    loads = normal_loads(mass, 900.0, lateral_acceleration=-500.0, banking=0.5)
    assert loads.total >= 0.0 and loads.front >= 0.0 and loads.rear >= 0.0


def test_slope_angle():
    assert slope_angle(0.0) == 0.0
    assert math.degrees(slope_angle(1.0)) == pytest.approx(45.0)


# -- longitudinal ------------------------------------------------------------


def test_force_balance_adds_up(car, air_density):
    forces = longitudinal_forces(car, 50.0, air_density, throttle=1.0)
    expected = (
        forces.drive
        - forces.drag
        - forces.rolling_resistance
        - forces.brake
        + forces.gradient
    )
    assert forces.net == pytest.approx(expected)
    assert forces.acceleration == pytest.approx(forces.net / car.total_mass())


def test_coasting_decelerates(car, air_density):
    forces = longitudinal_forces(car, 60.0, air_density, throttle=0.0, brake=0.0)
    assert forces.drive == 0.0
    assert forces.acceleration < 0.0


def test_drag_grows_with_speed(car, air_density):
    slow = longitudinal_forces(car, 20.0, air_density, throttle=1.0)
    fast = longitudinal_forces(car, 80.0, air_density, throttle=1.0)
    assert fast.drag > slow.drag * 8.0  # ~16x from v^2


def test_uphill_costs_acceleration(car, air_density):
    flat = max_acceleration(car, 50.0, air_density, gradient=0.0)
    uphill = max_acceleration(car, 50.0, air_density, gradient=0.10)
    downhill = max_acceleration(car, 50.0, air_density, gradient=-0.10)
    assert uphill < flat < downhill


def test_gradient_force_matches_the_weight_component(car, air_density):
    mass = car.total_mass()
    forces = longitudinal_forces(car, 50.0, air_density, gradient=0.10)
    expected = -mass * car.config.physics.gravity * math.sin(slope_angle(0.10))
    assert forces.gradient == pytest.approx(expected)


def test_heavier_car_accelerates_less(car, air_density):
    """Project rule 39: mass up, acceleration down."""
    light = max_acceleration(car, kph_to_ms(150.0), air_density, mass=800.0)
    heavy = max_acceleration(car, kph_to_ms(150.0), air_density, mass=950.0)
    assert heavy < light


def test_standing_start_is_traction_limited(car, air_density):
    """From rest the rear tyres, not the engine, are the constraint."""
    powertrain = car.power_unit.tractive_force(0.5)
    traction = traction_limited_force(car, 0.5, air_density, mass=car.total_mass())
    assert traction < powertrain


def test_traction_improves_with_downforce(car, air_density):
    slow = traction_limited_force(car, 5.0, air_density, mass=car.total_mass())
    fast = traction_limited_force(car, 70.0, air_density, mass=car.total_mass())
    assert fast > slow


def test_load_transfer_helps_the_launch(car, air_density):
    """Ignoring load transfer understates standing acceleration."""
    from dataclasses import replace

    from f1_race_engine.vehicle import Vehicle

    without = Vehicle(
        car.spec,
        car.setup,
        car.config.merged({"powertrain": {"longitudinal_load_transfer": False}}),
    )
    assert max_acceleration(car, 0.5, air_density) > max_acceleration(
        without, 0.5, air_density
    )


def test_braking_is_grip_limited_not_brake_limited(car, air_density):
    forces = longitudinal_forces(car, kph_to_ms(200.0), air_density, brake=1.0)
    assert forces.brake < car.brakes.system_limit()


def test_braking_is_stronger_at_high_speed(car, air_density):
    """Downforce, which a road car does not have, is why."""
    slow = max_deceleration(car, kph_to_ms(60.0), air_density)
    fast = max_deceleration(car, kph_to_ms(280.0), air_density)
    assert fast > slow * 2.0


def test_using_lateral_grip_reduces_braking(car, air_density):
    """The friction ellipse applies to the longitudinal axis too."""
    limit = car.tyre_model.grip_limit(TyreState().compound, car.total_mass() * 9.81)
    free = max_deceleration(car, kph_to_ms(150.0), air_density)
    cornering = max_deceleration(
        car, kph_to_ms(150.0), air_density, lateral_force_used=0.7 * limit.capacity
    )
    assert cornering < free


def test_braking_is_limited_by_an_axle_not_by_the_car(car, air_density):
    """The bias is fixed, so the first axle to saturate stops the car.

    Charging the whole retarding force against the whole load instead assumes a
    bias that follows the load transfer around, which no car has, and it lets
    the car brake harder than either axle can actually hold.
    """
    speed = kph_to_ms(280.0)
    mass = car.total_mass()
    bias = car.brake_bias_front
    limit = braking_limited_force(car, speed, air_density, mass=mass)

    from f1_race_engine.physics import normal_loads

    loads = normal_loads(
        car.mass,
        mass,
        downforce=car.aero.downforce(speed, air_density, car.wing_level),
        downforce_balance_front=car.spec.aero.aero_balance_front,
        longitudinal_acceleration=-limit / mass,
    )
    front = car.tyre_model.grip_limit(TyreState().compound, loads.front, tyres=2)
    rear = car.tyre_model.grip_limit(TyreState().compound, loads.rear, tyres=2)

    # Neither axle is over its own limit ...
    assert limit * bias <= front.capacity * 1.001
    assert limit * (1.0 - bias) <= rear.capacity * 1.001
    # ... and one of them is right on it, or the car is leaving grip unused.
    assert (
        limit * bias >= front.capacity * 0.999
        or limit * (1.0 - bias) >= rear.capacity * 0.999
    )


def test_brake_bias_has_an_interior_optimum(car, air_density):
    """Too much either way wastes the other axle, so the middle is quickest."""
    from dataclasses import replace

    speed = kph_to_ms(280.0)

    def decel(bias: float) -> float:
        spec = replace(
            car.spec, brakes=replace(car.spec.brakes, brake_bias_front=bias)
        )
        return max_deceleration(car.with_spec(spec), speed, air_density)

    values = {bias: decel(bias) for bias in (0.40, 0.50, 0.57, 0.68, 0.78)}
    best = max(values, key=values.__getitem__)
    assert 0.40 < best < 0.78, f"best bias {best} sits at the end of the range"
    assert values[best] > values[0.40]
    assert values[best] > values[0.78]


def test_axle_grip_sums_to_the_whole_car(car):
    """Load sensitivity is a per-patch property, so the bases must agree.

    Split evenly, two axles must offer exactly what the whole car offers.  If
    they offered more, the axle solvers would be inventing grip that the
    lateral model does not believe in.
    """
    compound = TyreState().compound
    for load in (8_000.0, 20_000.0, 35_000.0):
        whole = car.tyre_model.grip_limit(compound, load).capacity
        axles = 2.0 * car.tyre_model.grip_limit(compound, load / 2.0, tyres=2).capacity
        assert axles == pytest.approx(whole, rel=1e-9)


def test_an_axle_load_is_less_forgiving_than_the_same_car_load(car):
    """Half the load on half the tyres presses each patch just as hard."""
    compound = TyreState().compound
    axle = car.tyre_model.friction_coefficient(compound, 10_000.0, tyres=2)
    whole = car.tyre_model.friction_coefficient(compound, 10_000.0)
    assert axle < whole


def test_rolling_resistance_vanishes_at_rest(car, air_density):
    assert longitudinal_forces(car, 0.0, air_density).rolling_resistance == 0.0


def test_forces_export_is_plain_data(car, air_density):
    import json

    json.dumps(longitudinal_forces(car, 50.0, air_density, throttle=1.0).to_dict())


# -- lateral -----------------------------------------------------------------


def test_required_lateral_acceleration():
    assert required_lateral_acceleration(50.0, 1.0 / 100.0) == pytest.approx(25.0)
    assert required_lateral_acceleration(50.0, 0.0) == 0.0
    # Sign of curvature does not change the magnitude of the demand.
    assert required_lateral_acceleration(50.0, -0.01) == pytest.approx(25.0)


def test_lateral_capability_grows_with_speed(car, air_density):
    """Downforce is why: the same tyres do far more at 300 km/h."""
    values = [
        lateral_capability(car, kph_to_ms(s), air_density).lateral_acceleration
        for s in (60, 120, 200, 300)
    ]
    assert all(b > a for a, b in zip(values, values[1:]))


def test_low_speed_cornering_is_mechanical_grip(car, air_density):
    """With almost no downforce, lateral g must be near the friction
    coefficient -- roughly 1.7-2 g, not a high-speed number."""
    g = lateral_capability(car, kph_to_ms(50.0), air_density).lateral_g
    assert 1.4 < g < 2.5


def test_tighter_corners_are_slower(car, air_density):
    """Project rule 39: radius down, cornering speed down."""
    speeds = [corner_speed_limit(car, 1.0 / r, air_density) for r in (25, 50, 100, 200)]
    assert all(b > a for a, b in zip(speeds, speeds[1:]))


def test_a_straight_is_never_speed_limited(car, air_density):
    assert corner_speed_limit(car, 0.0, air_density, max_speed=95.0) == 95.0


def test_corner_speed_matches_the_capability_it_solves_for(car, air_density):
    """The solver's answer must actually satisfy demand == supply."""
    speed = corner_speed_limit(car, 1.0 / 80.0, air_density)
    demand = required_lateral_acceleration(speed, 1.0 / 80.0)
    supply = lateral_capability(
        car, speed, air_density, curvature=1.0 / 80.0
    ).lateral_acceleration
    assert demand == pytest.approx(supply, rel=1e-3)


def test_helpful_banking_raises_corner_speed(car, air_density):
    """Banking is signed like curvature: it helps when the signs match."""
    flat = corner_speed_limit(car, 1.0 / 100.0, air_density, banking=0.0)
    helped = corner_speed_limit(car, 1.0 / 100.0, air_density, banking=0.12)
    hindered = corner_speed_limit(car, 1.0 / 100.0, air_density, banking=-0.12)
    assert helped > flat > hindered


def test_more_grip_raises_corner_speed(car, air_density, compounds):
    """Project rule 40, Test D."""
    soft = corner_speed_limit(
        car, 1.0 / 100.0, air_density, tyre_state=TyreState(compound=compounds["S"])
    )
    hard = corner_speed_limit(
        car, 1.0 / 100.0, air_density, tyre_state=TyreState(compound=compounds["H"])
    )
    assert soft > hard


def test_lower_surface_grip_lowers_corner_speed(car, air_density):
    dry = corner_speed_limit(car, 1.0 / 100.0, air_density, surface_grip=1.0)
    slippery = corner_speed_limit(car, 1.0 / 100.0, air_density, surface_grip=0.7)
    assert slippery < dry


def test_no_grip_means_no_cornering(car, air_density):
    assert corner_speed_limit(car, 1.0 / 100.0, air_density, surface_grip=1e-9) < 1.0


def test_using_longitudinal_grip_reduces_cornering(car, air_density):
    limit = car.tyre_model.grip_limit(TyreState().compound, car.total_mass() * 9.81)
    free = lateral_capability(car, kph_to_ms(150.0), air_density).lateral_acceleration
    braking = lateral_capability(
        car, kph_to_ms(150.0), air_density, longitudinal_force_used=0.8 * limit.capacity
    ).lateral_acceleration
    assert braking < free


def test_capability_export_is_plain_data(car, air_density):
    import json

    json.dumps(lateral_capability(car, 60.0, air_density).to_dict())


# -- load across the car, not just along it ----------------------------------


def test_cornering_costs_grip_by_loading_the_outside_of_the_car(car, air_density):
    """The lateral counterpart of load transfer, and it works the same way.

    Friction coefficient falls with load, so a given total load buys less grip
    split unevenly across four tyres than shared evenly.  Cornering does
    exactly that split, so cornering costs grip simply by cornering.
    """
    from dataclasses import replace

    from f1_race_engine.core.config import default_config
    from f1_race_engine.vehicle import Vehicle

    config = default_config()
    without = Vehicle(
        car.spec,
        car.setup,
        config=replace(
            config, suspension=replace(config.suspension, lateral_load_transfer=False)
        ),
    )
    speed = kph_to_ms(250.0)
    assert max_lateral_acceleration(car, speed, air_density) < max_lateral_acceleration(
        without, speed, air_density
    )


def test_a_wider_car_corners_better_than_a_narrow_one(car, air_density):
    """Transfer is ``m * a_y * h / track``, so the wider the car the less of it
    there is -- which is why track width is on the car and not in a lap-time
    correction."""
    from dataclasses import replace

    narrow = car.with_spec(replace(car.spec, mass=replace(car.spec.mass, track_width=1.4)))
    wide = car.with_spec(replace(car.spec, mass=replace(car.spec.mass, track_width=1.8)))
    speed = kph_to_ms(250.0)
    assert max_lateral_acceleration(wide, speed, air_density) > max_lateral_acceleration(
        narrow, speed, air_density
    )


def test_a_higher_centre_of_gravity_corners_worse(car, air_density):
    from dataclasses import replace

    low = car.with_spec(replace(car.spec, mass=replace(car.spec.mass, cg_height=0.25)))
    high = car.with_spec(replace(car.spec, mass=replace(car.spec.mass, cg_height=0.42)))
    speed = kph_to_ms(250.0)
    assert max_lateral_acceleration(high, speed, air_density) < max_lateral_acceleration(
        low, speed, air_density
    )


def test_the_transfer_costs_more_the_harder_the_car_corners(car, air_density):
    """It is not a constant tax: the split widens with lateral acceleration."""
    from f1_race_engine.physics.grip import lateral_transfer_factor

    gentle = lateral_transfer_factor(20_000.0, 3_000.0, 0.08)
    hard = lateral_transfer_factor(20_000.0, 9_000.0, 0.08)
    assert 1.0 > gentle > hard


def test_lifting_the_inside_wheels_is_the_end_of_it(car):
    """Past the point where the inside wheels come up they carry nothing, and
    the model reaches that by itself rather than by a special case."""
    from f1_race_engine.physics.grip import lateral_transfer_factor

    lifted = lateral_transfer_factor(20_000.0, 10_000.0, 0.08)
    beyond = lateral_transfer_factor(20_000.0, 14_000.0, 0.08)
    assert lifted == pytest.approx(beyond)
