"""Energy recovery (project rule 24).

    "ERS는 단순히 '랩타임 -0.5초' 방식으로 구현하지 않는다."

So nothing here awards lap time.  The store has a capacity, a deployment
budget and two recovery paths, and the lap time is whatever falls out of
spending the energy on drive force.
"""

from __future__ import annotations

import pytest

from f1_race_engine.core.config import ErsConfig
from f1_race_engine.core.errors import ConfigError
from f1_race_engine.core.rng import RngHub
from f1_race_engine.simulation import LapSimulator
from f1_race_engine.vehicle.ers import (
    ErsProperties,
    ErsState,
    deploy_power,
    harvest_power,
    thermal_harvest_power,
)


def _store(**overrides) -> tuple[ErsState, ErsProperties]:
    properties = ErsProperties(**overrides)
    return ErsState(energy_remaining=properties.capacity), properties


# -- deployment --------------------------------------------------------------


def test_deploying_takes_energy_out_of_the_store():
    state, properties = _store()
    before = state.energy_remaining
    power = deploy_power(state, properties, speed=70.0, dt=0.5)
    assert power > 0.0
    assert state.energy_remaining < before
    assert state.deployed_this_lap == pytest.approx(before - state.energy_remaining)


def test_an_empty_store_deploys_nothing():
    """The point of the whole model: it runs out."""
    state, properties = _store()
    state.energy_remaining = 0.0
    assert deploy_power(state, properties, speed=70.0, dt=0.5) == 0.0


def test_the_lap_budget_binds_before_the_store_does():
    state, properties = _store(capacity=8.0e6, deployment_limit_per_lap=1.0e6)
    state.energy_remaining = 8.0e6
    for _ in range(200):
        deploy_power(state, properties, speed=70.0, dt=0.5)
    assert state.deployed_this_lap == pytest.approx(1.0e6)
    assert state.energy_remaining > 0.0


def test_a_new_lap_restores_the_budget_but_not_the_store():
    state, properties = _store()
    for _ in range(200):
        deploy_power(state, properties, speed=70.0, dt=0.5)
    spent = state.energy_remaining
    state.start_lap()
    assert state.deployed_this_lap == 0.0
    assert state.energy_remaining == pytest.approx(spent)


def test_deployment_is_pointless_at_a_standstill():
    """Below a walking pace the extra torque only spins the wheels, so the
    energy is not spent."""
    state, properties = _store()
    assert deploy_power(state, properties, speed=1.0, dt=0.5) == 0.0
    assert state.energy_remaining == pytest.approx(properties.capacity)


def test_a_partial_request_spends_proportionally():
    full, properties = _store()
    half, _ = _store()
    deploy_power(full, properties, speed=70.0, dt=0.5, request=1.0)
    deploy_power(half, properties, speed=70.0, dt=0.5, request=0.5)
    assert half.deployed_this_lap == pytest.approx(0.5 * full.deployed_this_lap)


def test_deployment_loses_something_on_the_way_to_the_road():
    state, properties = _store()
    delivered = deploy_power(state, properties, speed=70.0, dt=1.0)
    assert delivered < state.deployed_this_lap / 1.0


# -- recovery ----------------------------------------------------------------


def test_braking_recovers_energy():
    state, properties = _store()
    state.energy_remaining = 0.0
    recovered = harvest_power(state, properties, braking_power=400_000.0, dt=1.0)
    assert recovered > 0.0
    assert state.energy_remaining == pytest.approx(recovered)


def test_a_full_store_cannot_recover():
    """Real, and it bites at circuits with heavy braking and short laps."""
    state, properties = _store()
    assert harvest_power(state, properties, braking_power=400_000.0, dt=1.0) == 0.0


def test_recovery_is_capped_by_the_motor_not_the_brakes():
    state, properties = _store(max_harvest_power=120_000.0)
    state.energy_remaining = 0.0
    recovered = harvest_power(state, properties, braking_power=5.0e6, dt=1.0)
    assert recovered <= 120_000.0


def test_the_harvest_budget_binds():
    state, properties = _store(harvest_limit_per_lap=0.5e6)
    state.energy_remaining = 0.0
    for _ in range(100):
        harvest_power(state, properties, braking_power=1.0e6, dt=0.5)
    assert state.harvested_this_lap == pytest.approx(0.5e6)


def test_the_exhaust_recovers_while_the_car_is_on_the_throttle():
    """The other recovery path, and the one that actually sustains a stint:
    it runs when the brakes are not."""
    state, properties = _store()
    state.energy_remaining = 0.0
    recovered = thermal_harvest_power(state, properties, engine_power=500_000.0, dt=1.0)
    assert recovered > 0.0
    assert state.thermal_this_lap == pytest.approx(recovered)
    assert state.harvested_this_lap == 0.0


def test_the_exhaust_path_is_not_budgeted_per_lap():
    """Unlike the brakes -- which is exactly why a car can deploy more per lap
    than it could ever recover under braking."""
    state, properties = _store(harvest_limit_per_lap=0.1e6)
    state.energy_remaining = 0.0
    for _ in range(100):
        thermal_harvest_power(state, properties, engine_power=500_000.0, dt=0.5)
    assert state.thermal_this_lap > properties.harvest_limit_per_lap


def test_recovery_cannot_overfill_the_store():
    state, properties = _store()
    state.energy_remaining = properties.capacity - 1000.0
    for _ in range(50):
        thermal_harvest_power(state, properties, engine_power=500_000.0, dt=1.0)
        harvest_power(state, properties, braking_power=1.0e6, dt=1.0)
    assert state.energy_remaining <= properties.capacity


def test_state_of_charge_is_a_fraction():
    state, properties = _store()
    assert state.state_of_charge(properties) == pytest.approx(1.0)
    state.energy_remaining *= 0.25
    assert state.state_of_charge(properties) == pytest.approx(0.25)


def test_state_snapshot_is_plain_data():
    state, _ = _store()
    payload = state.snapshot()
    assert set(payload) >= {"energy_remaining", "deployed_this_lap", "thermal_this_lap"}
    assert all(isinstance(value, float) for value in payload.values())


# -- properties --------------------------------------------------------------


def test_properties_round_trip():
    properties = ErsProperties(capacity=3.5e6, max_deploy_power=110_000.0)
    assert ErsProperties.from_dict(properties.to_dict()) == properties


def test_impossible_properties_are_rejected():
    with pytest.raises(ConfigError):
        ErsProperties(capacity=0.0)
    with pytest.raises(ConfigError):
        ErsProperties(harvest_limit_per_lap=-1.0)


def test_unknown_key_is_rejected():
    with pytest.raises(ConfigError):
        ErsProperties.from_dict({"capacity": 4.0e6, "turbo": True})


# -- what it is worth on the road --------------------------------------------


def test_deployment_is_worth_lap_time(fast_track, car, perfect_driver):
    """Not because a bonus is subtracted, but because 120 kW of drive force
    accelerates the car harder out of every corner."""
    simulator = LapSimulator(fast_track, car, perfect_driver, rng=RngHub(7))
    charged = simulator.simulate(ers_state=ErsState(energy_remaining=car.spec.ers.capacity))
    flat = simulator.simulate(ers_state=ErsState(energy_remaining=0.0))
    assert charged.lap_time < flat.lap_time
    assert charged.energy_deployed > 0.0
    assert flat.energy_deployed == 0.0


def test_more_energy_is_worth_more_time(fast_track, car, perfect_driver):
    simulator = LapSimulator(fast_track, car, perfect_driver, rng=RngHub(7))
    times = [
        simulator.simulate(ers_state=ErsState(energy_remaining=budget)).lap_time
        for budget in (0.0, 1.0e6, 2.0e6, 4.0e6)
    ]
    assert all(b < a for a, b in zip(times, times[1:]))


def test_a_lap_cannot_deploy_more_than_the_regulations_allow(
    fast_track, car, perfect_driver
):
    simulator = LapSimulator(fast_track, car, perfect_driver, rng=RngHub(7))
    result = simulator.simulate(
        ers_state=ErsState(energy_remaining=car.spec.ers.capacity * 10.0)
    )
    assert result.energy_deployed <= car.spec.ers.deployment_limit_per_lap * 1.001


def test_a_stint_settles_at_what_it_can_recover(fast_track, car, perfect_driver):
    """The equilibrium every real hybrid runs at, and nowhere is it written
    down: it emerges from spending and recovering."""
    simulator = LapSimulator(fast_track, car, perfect_driver, rng=RngHub(7))
    energy = ErsState(energy_remaining=car.spec.ers.capacity)
    laps = [
        simulator.simulate(lap=lap, ers_state=energy, record_telemetry=False)
        for lap in range(1, 13)
    ]
    assert energy.energy_remaining >= 0.0
    settled = laps[-1]
    assert settled.energy_deployed == pytest.approx(settled.energy_harvested, rel=0.1)


def test_the_energy_books_balance(fast_track, car, perfect_driver):
    """Rule 39: whatever left the store plus whatever is still in it must be
    what went in."""
    simulator = LapSimulator(fast_track, car, perfect_driver, rng=RngHub(7))
    start = 2.0e6
    energy = ErsState(energy_remaining=start)
    for lap in range(1, 6):
        simulator.simulate(lap=lap, ers_state=energy, record_telemetry=False)
    assert energy.energy_remaining == pytest.approx(
        start + energy.recovered_total - energy.deployed_total
    )


def test_minimum_deploy_speed_is_configurable():
    state, properties = _store()
    config = ErsConfig(minimum_deploy_speed=50.0)
    assert deploy_power(state, properties, speed=40.0, dt=0.5, config=config) == 0.0
    assert deploy_power(state, properties, speed=60.0, dt=0.5, config=config) > 0.0
