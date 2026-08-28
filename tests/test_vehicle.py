"""The vehicle and its subsystems."""

from __future__ import annotations

import math

import pytest

from f1_race_engine.core.errors import ConfigError
from f1_race_engine.vehicle import (
    AeroProperties,
    BrakeProperties,
    MassProperties,
    PowerUnit,
    PowerUnitProperties,
    Vehicle,
    VehicleSetup,
    VehicleSpec,
    VehicleState,
)
from f1_race_engine.vehicle.aero import AeroModel
from f1_race_engine.vehicle.brakes import BrakeSystem
from f1_race_engine.vehicle.io import (
    builtin_vehicle_names,
    load_builtin_vehicle,
    load_vehicle_spec,
    save_vehicle_spec,
)


# -- mass --------------------------------------------------------------------


def test_dry_mass_is_car_plus_driver():
    mass = MassProperties(chassis_mass=718.0, driver_mass=80.0)
    assert mass.dry_mass == pytest.approx(798.0)
    assert mass.total_mass(110.0) == pytest.approx(908.0)


def test_weight_distribution_sums_to_one():
    mass = MassProperties(weight_distribution_front=0.45)
    assert mass.weight_distribution_front + mass.weight_distribution_rear == pytest.approx(1.0)


def test_load_transfer_moves_load_rearward_under_acceleration():
    mass = MassProperties(cg_height=0.30, wheelbase=3.6)
    transfer = mass.load_transfer(10.0, 900.0)
    assert transfer == pytest.approx(900.0 * 10.0 * 0.30 / 3.6)
    assert mass.load_transfer(-10.0, 900.0) == pytest.approx(-transfer)
    assert mass.load_transfer(0.0, 900.0) == 0.0


def test_higher_centre_of_gravity_transfers_more_load():
    low = MassProperties(cg_height=0.25)
    high = MassProperties(cg_height=0.40)
    assert high.load_transfer(10.0, 900.0) > low.load_transfer(10.0, 900.0)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"chassis_mass": 0.0},
        {"driver_mass": -1.0},
        {"wheelbase": 0.0},
        {"cg_height": -0.1},
        {"weight_distribution_front": 0.95},
    ],
)
def test_impossible_mass_properties_are_rejected(kwargs):
    with pytest.raises(ConfigError):
        MassProperties(**kwargs)


def test_negative_fuel_is_rejected():
    with pytest.raises(ConfigError):
        MassProperties().total_mass(-5.0)


# -- aero --------------------------------------------------------------------


def test_downforce_and_drag_scale_with_speed_squared(air_density):
    model = AeroModel(AeroProperties())
    assert model.downforce(40.0, air_density, 0.5) == pytest.approx(
        4.0 * model.downforce(20.0, air_density, 0.5)
    )
    assert model.drag(40.0, air_density, 0.5) == pytest.approx(
        4.0 * model.drag(20.0, air_density, 0.5)
    )


def test_downforce_scales_with_air_density():
    model = AeroModel(AeroProperties())
    assert model.downforce(50.0, 1.3, 0.5) > model.downforce(50.0, 1.1, 0.5)


def test_more_wing_means_more_downforce_and_more_drag():
    properties = AeroProperties()
    levels = (0.0, 0.25, 0.5, 0.75, 1.0)
    lift = [properties.downforce_area(w) for w in levels]
    drag = [properties.drag_area(w) for w in levels]
    assert all(b > a for a, b in zip(lift, lift[1:]))
    assert all(b > a for a, b in zip(drag, drag[1:]))


def test_induced_drag_grows_faster_than_downforce():
    """Drag has a ClA^2 term, so each extra wing level costs more than the last.
    That non-linearity is what makes wing level a real decision."""
    properties = AeroProperties()
    first_step = properties.drag_area(0.25) - properties.drag_area(0.0)
    last_step = properties.drag_area(1.0) - properties.drag_area(0.75)
    assert last_step > first_step


def test_drag_area_matches_the_induced_drag_formula():
    properties = AeroProperties(
        min_downforce_area=4.0, max_downforce_area=4.0,
        zero_lift_drag_area=0.7, induced_drag_factor=0.02,
    )
    assert properties.drag_area(0.5) == pytest.approx(0.7 + 0.02 * 16.0)


def test_wing_level_is_clamped():
    properties = AeroProperties()
    assert properties.downforce_area(-1.0) == properties.downforce_area(0.0)
    assert properties.downforce_area(5.0) == properties.downforce_area(1.0)


def test_drs_cuts_drag_and_downforce(air_density):
    model = AeroModel(AeroProperties())
    closed = model.forces(80.0, air_density, 0.5)
    open_ = model.forces(80.0, air_density, 0.5, drs_open=True)
    assert open_.drag < closed.drag
    assert open_.downforce < closed.downforce
    assert open_.drag / closed.drag == pytest.approx(1.0 - model.config.drs_drag_reduction)


def test_aero_balance_splits_downforce(air_density):
    properties = AeroProperties(aero_balance_front=0.44)
    forces = AeroModel(properties).forces(80.0, air_density, 0.5)
    assert forces.downforce_front + forces.downforce_rear == pytest.approx(forces.downforce)
    assert forces.downforce_front / forces.downforce == pytest.approx(0.44)


def test_zero_speed_makes_no_aero_force(air_density):
    forces = AeroModel(AeroProperties()).forces(0.0, air_density, 0.5)
    assert forces.downforce == 0.0 and forces.drag == 0.0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"min_downforce_area": 0.0},
        {"max_downforce_area": 1.0},
        {"zero_lift_drag_area": 0.0},
        {"induced_drag_factor": -0.1},
        {"aero_balance_front": 0.95},
    ],
)
def test_impossible_aero_is_rejected(kwargs):
    with pytest.raises(ConfigError):
        AeroProperties(**kwargs)


# -- power unit --------------------------------------------------------------


def test_low_speed_is_torque_limited_and_high_speed_power_limited():
    unit = PowerUnit(PowerUnitProperties())
    crossover = unit.torque_limit_speed
    below = unit.tractive_force(crossover * 0.5)
    at = unit.tractive_force(crossover * 0.99)
    above = unit.tractive_force(crossover * 2.0)
    assert below == pytest.approx(at, rel=1e-6)
    assert above < at
    assert above == pytest.approx(unit.wheel_power / (crossover * 2.0))


def test_power_limited_force_falls_as_one_over_speed():
    unit = PowerUnit(PowerUnitProperties())
    high = unit.torque_limit_speed * 2.0
    assert unit.tractive_force(high * 2.0) == pytest.approx(
        unit.tractive_force(high) / 2.0
    )


def test_throttle_scales_the_demand():
    unit = PowerUnit(PowerUnitProperties())
    assert unit.tractive_force(50.0, throttle=0.0) == 0.0
    assert unit.tractive_force(50.0, throttle=0.5) == pytest.approx(
        0.5 * unit.tractive_force(50.0)
    )


def test_zero_speed_does_not_divide_by_zero():
    unit = PowerUnit(PowerUnitProperties())
    assert math.isfinite(unit.tractive_force(0.0))
    assert unit.tractive_force(0.0) == PowerUnitProperties().max_tractive_force


def test_drivetrain_efficiency_reduces_wheel_power():
    unit = PowerUnit(PowerUnitProperties(max_power=500_000.0))
    assert unit.wheel_power < 500_000.0
    assert unit.wheel_power == pytest.approx(500_000.0 * unit.config.drivetrain_efficiency)


@pytest.mark.parametrize(
    "kwargs", [{"max_power": 0.0}, {"peak_wheel_torque": -1.0}, {"wheel_radius": 0.0}]
)
def test_impossible_power_unit_is_rejected(kwargs):
    with pytest.raises(ConfigError):
        PowerUnitProperties(**kwargs)


# -- brakes ------------------------------------------------------------------


def test_brake_force_scales_with_demand():
    system = BrakeSystem(BrakeProperties(max_brake_force=60_000.0))
    assert system.brake_force(0.0) == 0.0
    assert system.brake_force(0.5) == pytest.approx(30_000.0)
    assert system.brake_force(1.0) == pytest.approx(60_000.0)
    assert system.brake_force(3.0) == pytest.approx(60_000.0)


def test_brake_system_can_outmuscle_the_tyres():
    """An F1 car must be able to lock its wheels, so braking is grip limited."""
    system = BrakeSystem(BrakeProperties())
    assert system.system_limit() > 45_000.0


@pytest.mark.parametrize("kwargs", [{"max_brake_force": 0.0}, {"brake_bias_front": 0.95}])
def test_impossible_brakes_are_rejected(kwargs):
    with pytest.raises(ConfigError):
        BrakeProperties(**kwargs)


# -- setup -------------------------------------------------------------------


def test_setup_variants_are_copies():
    base = VehicleSetup(wing_level=0.5)
    assert base.with_wing(0.9).wing_level == 0.9
    assert base.wing_level == 0.5
    assert base.with_fuel(10.0).fuel_load == 10.0


@pytest.mark.parametrize(
    "kwargs",
    [{"wing_level": 1.5}, {"wing_level": -0.1}, {"brake_bias_front": 0.1}, {"fuel_load": -1.0}],
)
def test_impossible_setup_is_rejected(kwargs):
    with pytest.raises(ConfigError):
        VehicleSetup(**kwargs)


# -- the vehicle -------------------------------------------------------------


def test_vehicle_composes_its_subsystems(car):
    assert car.aero is not None
    assert car.power_unit is not None
    assert car.brakes is not None
    assert car.tyre_model is not None


def test_setup_overrides_brake_bias(reference_spec):
    default = Vehicle(reference_spec).brake_bias_front
    overridden = Vehicle(reference_spec, VehicleSetup(brake_bias_front=0.62))
    assert overridden.brake_bias_front == pytest.approx(0.62)
    assert default == reference_spec.brakes.brake_bias_front


def test_with_setup_returns_a_new_vehicle(car):
    other = car.with_wing(0.9)
    assert other is not car
    assert other.wing_level == 0.9
    assert car.wing_level == 0.5
    assert other.spec is car.spec


def test_with_spec_keeps_the_setup(car, reference_spec):
    from dataclasses import replace

    lighter = replace(reference_spec, name="Lighter")
    swapped = car.with_spec(lighter)
    assert swapped.setup == car.setup
    assert swapped.name == "Lighter"


def test_total_mass_uses_the_setup_fuel_load(reference_spec):
    car = Vehicle(reference_spec, VehicleSetup(fuel_load=40.0))
    assert car.total_mass() == pytest.approx(reference_spec.mass.dry_mass + 40.0)
    assert car.total_mass(0.0) == pytest.approx(reference_spec.mass.dry_mass)


def test_vehicle_export_is_json_serialisable(car):
    import json

    json.dumps(car.to_dict())


# -- specification data ------------------------------------------------------


def test_spec_round_trip(reference_spec):
    assert VehicleSpec.from_dict(reference_spec.to_dict()) == reference_spec


def test_spec_file_round_trip(reference_spec, tmp_path):
    path = tmp_path / "car.json"
    save_vehicle_spec(reference_spec, path)
    assert load_vehicle_spec(path) == reference_spec


def test_shipped_cars_load():
    assert set(builtin_vehicle_names()) == {
        "aero_biased", "power_biased", "reference_2024",
    }
    for name in builtin_vehicle_names():
        assert load_builtin_vehicle(name).name


def test_unknown_car_lists_what_is_available():
    with pytest.raises(ConfigError, match="available"):
        load_builtin_vehicle("nonexistent")


def test_missing_name_is_rejected():
    with pytest.raises(ConfigError, match="name"):
        VehicleSpec.from_dict({"mass": {}})


def test_unknown_spec_key_is_rejected():
    with pytest.raises(ConfigError, match="unknown"):
        VehicleSpec.from_dict({"name": "X", "turbocharger": {}})


# -- state -------------------------------------------------------------------


def test_vehicle_state_snapshot_is_plain_data():
    payload = VehicleState().snapshot()
    assert payload["speed"] == 0.0
    assert "tyres" in payload


def test_vehicle_state_reset():
    state = VehicleState(distance=500.0, speed=80.0, time=12.0, throttle=1.0)
    state.reset(speed=10.0, fuel_mass=50.0)
    assert state.distance == 0.0 and state.time == 0.0
    assert state.speed == 10.0 and state.fuel_mass == 50.0
    assert state.throttle == 0.0
