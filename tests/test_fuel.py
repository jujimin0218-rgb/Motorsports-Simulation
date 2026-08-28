"""Fuel (project rule 23).

Fuel is mass on board burned in proportion to the work the engine does.  Every
behaviour below follows from that one relationship -- there is no per-lap
consumption figure anywhere in the engine.
"""

from __future__ import annotations

import pytest

from f1_race_engine.core.config import FuelConfig
from f1_race_engine.core.errors import ConfigError
from f1_race_engine.vehicle.fuel import FuelProperties, fuel_burned


def test_fuel_follows_the_work_done():
    idle = fuel_burned(0.0, 10.0)
    single = fuel_burned(2.0e6, 10.0)
    double = fuel_burned(4.0e6, 10.0)
    assert double > single > idle
    assert double - idle == pytest.approx(2.0 * (single - idle))


def test_an_idling_engine_still_burns():
    assert fuel_burned(0.0, 10.0) > 0.0


def test_the_flow_limit_binds():
    """A car cannot burn its way past the regulations however hard it is
    driven, which is why peak power is a rule and not a design choice."""
    properties = FuelProperties(max_flow_rate=0.0278)
    assert fuel_burned(1.0e12, 2.0, properties=properties) == pytest.approx(
        properties.max_flow_rate * 2.0
    )


def test_a_more_efficient_engine_uses_less():
    thirsty = FuelConfig(thermal_efficiency=0.35)
    efficient = FuelConfig(thermal_efficiency=0.55)
    assert fuel_burned(18.0e6, 60.0, config=efficient) < fuel_burned(
        18.0e6, 60.0, config=thirsty
    )


def test_a_zero_length_step_burns_nothing():
    assert fuel_burned(1.0e6, 0.0) == 0.0


def test_consumption_is_in_the_right_ballpark():
    """Rule 39, applied to a number anyone can check: an F1 car uses roughly
    1.5-2.5 kg of fuel a lap.  Order-of-magnitude, from work alone."""
    work_per_lap = 32.0e6
    burned = fuel_burned(work_per_lap, 85.0)
    assert 1.2 < burned < 2.6


def test_properties_round_trip():
    properties = FuelProperties(capacity=105.0, max_flow_rate=0.026)
    assert FuelProperties.from_dict(properties.to_dict()) == properties


def test_impossible_properties_are_rejected():
    with pytest.raises(ConfigError):
        FuelProperties(capacity=0.0)
    with pytest.raises(ConfigError):
        FuelProperties(max_flow_rate=-1.0)


def test_unknown_key_is_rejected():
    with pytest.raises(ConfigError):
        FuelProperties.from_dict({"capacity": 100.0, "octane": 98})


# -- what fuel does to the car -----------------------------------------------


def test_a_full_tank_makes_the_car_slower(fast_track, car, perfect_driver):
    """The reason a race gets faster as it goes on, with no lap-number term
    anywhere: the car is simply lighter."""
    from f1_race_engine.core.rng import RngHub
    from f1_race_engine.simulation import LapSimulator

    simulator = LapSimulator(fast_track, car, perfect_driver, rng=RngHub(5))
    heavy = simulator.simulate(fuel_mass=100.0)
    light = simulator.simulate(fuel_mass=10.0)
    assert light.lap_time < heavy.lap_time


def test_the_car_gets_lighter_over_a_lap(fast_track, car, perfect_driver):
    from f1_race_engine.core.rng import RngHub
    from f1_race_engine.simulation import LapSimulator

    result = LapSimulator(fast_track, car, perfect_driver, rng=RngHub(5)).simulate(
        fuel_mass=90.0
    )
    assert result.fuel_used > 0.0
    assert result.final_state.fuel_mass == pytest.approx(90.0 - result.fuel_used)


def test_a_lap_burns_a_realistic_amount(fast_track, car, perfect_driver):
    from f1_race_engine.core.rng import RngHub
    from f1_race_engine.simulation import LapSimulator

    result = LapSimulator(fast_track, car, perfect_driver, rng=RngHub(5)).simulate(
        fuel_mass=90.0
    )
    assert 0.8 < result.fuel_used < 3.0


def test_a_thirstier_circuit_burns_faster(car, perfect_driver, coarse_build_config):
    """Consumption is a property of the circuit's energy demand, not a number
    attached to its name (rule 2.3).

    Flow, not kilograms: a circuit that asks for more power burns more per
    second.  Per kilometre the ordering reverses, because a slow circuit spends
    longer covering the same ground -- which is also true of the real thing.
    """
    from f1_race_engine.core.rng import RngHub
    from f1_race_engine.simulation import LapSimulator
    from f1_race_engine.track.builder import build_track
    from f1_race_engine.track.io import load_builtin_definition

    flow = {}
    for name in ("synthetic_power_circuit", "synthetic_street_circuit"):
        track = build_track(load_builtin_definition(name), coarse_build_config)
        result = LapSimulator(track, car, perfect_driver, rng=RngHub(5)).simulate(
            fuel_mass=90.0
        )
        flow[name] = result.fuel_used / result.lap_time
    assert flow["synthetic_power_circuit"] > flow["synthetic_street_circuit"]


def test_a_heavier_car_burns_more(fast_track, car, perfect_driver):
    """Which is the feedback that makes a long first stint expensive."""
    from f1_race_engine.core.rng import RngHub
    from f1_race_engine.simulation import LapSimulator

    simulator = LapSimulator(fast_track, car, perfect_driver, rng=RngHub(5))
    assert (
        simulator.simulate(fuel_mass=100.0).fuel_used
        > simulator.simulate(fuel_mass=20.0).fuel_used
    )
