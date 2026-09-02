"""Lap simulation (project rule 26): a car actually driving a lap."""

from __future__ import annotations

import statistics

import pytest

from f1_race_engine.core.rng import RngHub
from f1_race_engine.driver import Driver, DriverAttributes
from f1_race_engine.physics import compute_lap_time
from f1_race_engine.simulation import LapSimulator, simulate_lap
from f1_race_engine.vehicle.ers import ErsState


def _driver(**overrides) -> Driver:
    base = dict(
        pace=0.90, qualifying=0.90, racecraft=0.90, consistency=1.0,
        tyre_management=0.90, braking=0.85, cornering=0.90,
        throttle_control=0.85, wet_skill=0.90, risk_management=1.0,
    )
    base.update(overrides)
    return Driver(name="Test", abbreviation="TST", attributes=DriverAttributes(**base))


# -- the stepping is right ---------------------------------------------------


def test_a_perfect_driver_reproduces_the_limit_lap(fast_track, car, simulator):
    """The test that says the step-by-step integration is correct.

    Phase 3 computes the lap as an integral over a speed profile; Phase 4 steps
    the vehicle state forward segment by segment with pedal inputs.  With a
    driver who leaves nothing on the table, the two must agree.

    Phase 5 gave the car consumables, so the comparison holds them still: an
    empty energy store and no fuel to burn off.  What is under test is the
    integration, not what the car is carrying.
    """
    stepped = simulator.simulate(
        mass=car.total_mass(), fuel_mass=0.0,
        ers_state=ErsState(energy_remaining=0.0),
    )
    limit = compute_lap_time(fast_track, car, analyse_zones=False)
    assert stepped.lap_time == pytest.approx(limit.lap_time, rel=2e-4)
    # The two evaluate the segment capability at slightly different points, so
    # they agree to numerical noise rather than to the bit.
    assert stepped.top_speed == pytest.approx(limit.top_speed, rel=1e-4)
    assert stepped.minimum_speed == pytest.approx(limit.minimum_speed, rel=1e-4)


def test_sector_times_sum_to_the_lap(simulator):
    result = simulator.simulate()
    assert sum(result.sector_times) == pytest.approx(result.lap_time, abs=1e-9)
    assert len(result.sector_times) == 3


def test_the_lap_is_deterministic(fast_track, car, perfect_driver):
    """Rule 40, Test A, at the simulation level."""
    first = LapSimulator(fast_track, car, perfect_driver, rng=RngHub(4242)).simulate(lap=3)
    second = LapSimulator(fast_track, car, perfect_driver, rng=RngHub(4242)).simulate(lap=3)
    assert first.lap_time == second.lap_time
    assert first.telemetry.channel("speed") == second.telemetry.channel("speed")


def test_a_different_seed_changes_an_inconsistent_driver(fast_track, car):
    driver = _driver(consistency=0.7, risk_management=0.7)
    a = LapSimulator(fast_track, car, driver, rng=RngHub(1)).simulate(lap=1)
    b = LapSimulator(fast_track, car, driver, rng=RngHub(2)).simulate(lap=1)
    assert a.lap_time != b.lap_time


def test_the_car_completes_the_lap(fast_track, car, simulator):
    result = simulator.simulate()
    assert result.final_state.distance == pytest.approx(fast_track.length, rel=1e-9)
    assert result.minimum_speed > 0.0


# -- the driver changes the lap ----------------------------------------------


def test_a_better_driver_is_faster(fast_track, car):
    weak = LapSimulator(fast_track, car, _driver(pace=0.75, cornering=0.75),
                        rng=RngHub(1)).simulate()
    strong = LapSimulator(fast_track, car, _driver(pace=0.98, cornering=0.98),
                          rng=RngHub(1)).simulate()
    assert strong.lap_time < weak.lap_time


def test_driver_spread_is_realistic(fast_track, car, lineup):
    """Best to worst in equal machinery, as a fraction of the lap.

    A fraction rather than a count of seconds, because the answer has to hold
    on a circuit of any length.  A real Formula 1 grid spans about 1% in equal
    cars; the shipped lineup runs wider than that on purpose because it ends
    with a rookie, who is not on the grid.
    """
    times = [
        LapSimulator(fast_track, car, driver, rng=RngHub(20260812)).simulate().lap_time
        for driver in lineup
    ]
    spread = (max(times) - min(times)) / min(times)
    assert 0.002 < spread < 0.045


def test_each_ability_is_worth_more_where_it_matters(fast_track, car,
                                                     coarse_build_config):
    """Braking ability must pay off in proportion to how much braking a
    circuit asks for."""
    from f1_race_engine.track.builder import build_track
    from f1_race_engine.track.io import load_builtin_definition

    reference = _driver()
    better_brakes = _driver(braking=0.99)
    gains = {}
    fractions = {}
    for name in ("synthetic_power_circuit", "synthetic_street_circuit"):
        track = build_track(load_builtin_definition(name), coarse_build_config)
        base = LapSimulator(track, car, reference, rng=RngHub(3)).simulate()
        quick = LapSimulator(track, car, better_brakes, rng=RngHub(3)).simulate()
        gains[name] = base.lap_time - quick.lap_time
        fractions[name] = base.telemetry.braking_fraction
    assert fractions["synthetic_street_circuit"] > fractions["synthetic_power_circuit"]
    assert gains["synthetic_street_circuit"] > gains["synthetic_power_circuit"]


def test_traction_is_worth_more_than_braking(fast_track, car):
    """A model result worth pinning down: you gain more on exit than entry,
    because a lap spends far longer accelerating than braking."""
    reference = _driver()
    braker = _driver(braking=0.99)
    tractor = _driver(throttle_control=0.99)
    base = LapSimulator(fast_track, car, reference, rng=RngHub(3)).simulate().lap_time
    with_brakes = LapSimulator(fast_track, car, braker, rng=RngHub(3)).simulate().lap_time
    with_traction = LapSimulator(fast_track, car, tractor, rng=RngHub(3)).simulate().lap_time
    assert base - with_traction > base - with_brakes > 0.0


def test_qualifying_trim_is_faster_for_a_one_lap_specialist(fast_track, car):
    specialist = _driver(qualifying=0.99)
    simulator = LapSimulator(fast_track, car, specialist, rng=RngHub(6))
    assert simulator.simulate(qualifying=True).lap_time < simulator.simulate().lap_time


def test_commitment_is_reported(simulator):
    result = simulator.simulate()
    assert result.commitment.cornering == pytest.approx(1.0)
    assert result.commitment.braking == pytest.approx(1.0)


# -- consistency and mistakes cost time through the driving ------------------


def test_an_inconsistent_driver_varies_lap_to_lap(fast_track, car):
    steady = LapSimulator(fast_track, car, _driver(consistency=0.99), rng=RngHub(8))
    erratic = LapSimulator(fast_track, car, _driver(consistency=0.70), rng=RngHub(8))
    steady_times = [steady.simulate(lap=i).lap_time for i in range(1, 16)]
    erratic_times = [erratic.simulate(lap=i).lap_time for i in range(1, 16)]
    assert statistics.pstdev(erratic_times) > statistics.pstdev(steady_times)
    assert statistics.pstdev(steady_times) < 0.05


def test_inconsistency_costs_average_pace_too(fast_track, car):
    """Variation is one-sided, so an erratic driver's median lap is slower as
    well as more scattered."""
    steady = LapSimulator(fast_track, car, _driver(consistency=0.99), rng=RngHub(8))
    erratic = LapSimulator(fast_track, car, _driver(consistency=0.70), rng=RngHub(8))
    steady_median = statistics.median(
        steady.simulate(lap=i).lap_time for i in range(1, 16)
    )
    erratic_median = statistics.median(
        erratic.simulate(lap=i).lap_time for i in range(1, 16)
    )
    assert erratic_median > steady_median


def test_a_mistake_costs_time_through_the_driving(fast_track, car):
    """Never by adding seconds to a result: a mistake lowers apex speed, and
    the profile propagates the loss down the following straight."""
    driver = _driver(consistency=0.5, risk_management=0.4)
    simulator = LapSimulator(fast_track, car, driver, rng=RngHub(20260812))
    laps = [simulator.simulate(lap=i) for i in range(1, 40)]
    with_mistakes = [lap for lap in laps if lap.had_mistake]
    clean = [lap for lap in laps if not lap.had_mistake]
    assert with_mistakes, "expected an erratic driver to make a mistake"
    assert clean
    assert statistics.median(l.lap_time for l in with_mistakes) > statistics.median(
        l.lap_time for l in clean
    )


def test_a_mistake_lowers_the_speed_at_its_own_corner(fast_track, car):
    driver = _driver(consistency=0.4, risk_management=0.3)
    simulator = LapSimulator(fast_track, car, driver, rng=RngHub(99))
    clean = simulator.simulate(lap=1)
    for lap in range(2, 60):
        result = simulator.simulate(lap=lap)
        if not result.had_mistake:
            continue
        mistake = result.mistakes[0]
        index = next(
            i for i, segment in enumerate(fast_track.segments)
            if segment.corner_id == mistake.corner_id
        )
        assert result.profile.corner_limit[index] < clean.profile.corner_limit[index]
        return
    pytest.fail("no mistake occurred in 60 laps")


# -- telemetry ---------------------------------------------------------------


def test_telemetry_covers_the_lap(fast_track, simulator):
    telemetry = simulator.simulate().telemetry
    assert len(telemetry) == len(fast_track)
    assert telemetry.samples[0].distance == 0.0
    assert telemetry.duration > 0.0


def test_telemetry_channels(simulator):
    telemetry = simulator.simulate().telemetry
    for channel in ("speed", "throttle", "brake", "lateral_g", "longitudinal_g"):
        values = telemetry.channel(channel)
        assert len(values) == len(telemetry)
    with pytest.raises(KeyError):
        telemetry.channel("horsepower")


def test_inputs_stay_in_range(simulator):
    telemetry = simulator.simulate().telemetry
    assert all(0.0 <= s.throttle <= 1.0 for s in telemetry)
    assert all(0.0 <= s.brake <= 1.0 for s in telemetry)
    assert all(-1.0 <= s.steering <= 1.0 for s in telemetry)


def test_throttle_and_brake_are_never_both_applied(simulator):
    telemetry = simulator.simulate().telemetry
    assert not any(s.throttle > 0.0 and s.brake > 0.0 for s in telemetry)


def test_full_throttle_fraction_is_realistic(simulator):
    """Time-weighted, as teams quote it, on the balanced reference circuit.

    Teams quote 55% at Monaco to 78% at Monza.  This reads a little under the
    circuit's real equivalent, and the reason is the driver rather than the
    road: the Phase 4 controller follows the speed profile exactly, so where
    the profile is flat it holds a maintenance throttle, while a real driver
    squirts and lifts.  Same lap time, different pedal trace.  The range below
    allows for that; tightening it would be testing the controller's shape.
    """
    telemetry = simulator.simulate().telemetry
    assert 0.45 < telemetry.full_throttle_fraction < 0.90
    assert 0.0 < telemetry.braking_fraction < 0.25


def test_a_twistier_circuit_spends_less_time_at_full_throttle(
    car, perfect_driver, coarse_build_config
):
    from f1_race_engine.track.builder import build_track
    from f1_race_engine.track.io import load_builtin_definition

    fractions = {}
    for name in ("synthetic_power_circuit", "synthetic_street_circuit"):
        track = build_track(load_builtin_definition(name), coarse_build_config)
        result = LapSimulator(track, car, perfect_driver, rng=RngHub(1)).simulate()
        fractions[name] = result.telemetry.full_throttle_fraction
    assert fractions["synthetic_power_circuit"] > fractions["synthetic_street_circuit"]


def test_telemetry_can_be_strided(simulator):
    dense = simulator.simulate(telemetry_stride=1).telemetry
    sparse = simulator.simulate(telemetry_stride=5).telemetry
    assert len(sparse) < len(dense)
    # The fractions are time-weighted, so striding does not distort them much.
    assert sparse.full_throttle_fraction == pytest.approx(
        dense.full_throttle_fraction, abs=0.06
    )


def test_telemetry_can_be_switched_off(simulator):
    assert simulator.simulate(record_telemetry=False).telemetry is None


def test_telemetry_exports_csv(simulator):
    csv = simulator.simulate().telemetry.to_csv()
    lines = csv.strip().split("\n")
    assert lines[0].startswith("distance,time,speed")
    assert len(lines) > 10


def test_export_is_json_serialisable(simulator):
    import json

    result = simulator.simulate()
    json.dumps(result.to_dict())
    json.dumps(result.to_dict(include_telemetry=True))


def test_convenience_wrapper(fast_track, car, perfect_driver):
    result = simulate_lap(fast_track, car, perfect_driver, rng=RngHub(1), lap=2)
    assert result.lap == 2
    assert result.lap_time > 0.0
