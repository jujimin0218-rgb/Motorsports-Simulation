"""The vehicle performance benchmark (project rule 41).

Every number here is integrated from the force balance, so the tests assert
that the figures land where a real Formula 1 car lands *and* that they respond
correctly when the car is changed.  A benchmark that does not move when the car
does is measuring nothing.
"""

from __future__ import annotations

import math

import pytest

from f1_race_engine.core.units import kph_to_ms, ms_to_kph
from f1_race_engine.environment import AmbientConditions
from f1_race_engine.physics.benchmark import (
    REFERENCE_F1,
    benchmark_vehicle,
    format_benchmark,
)


@pytest.fixture(scope="module")
def reference_benchmark():
    from f1_race_engine.vehicle import MEDIUM_DOWNFORCE, Vehicle
    from f1_race_engine.vehicle.io import load_builtin_vehicle

    return benchmark_vehicle(
        Vehicle(load_builtin_vehicle("reference_2024"), MEDIUM_DOWNFORCE)
    )


# -- against reality ---------------------------------------------------------


def test_top_speed_is_realistic(reference_benchmark):
    low, high = REFERENCE_F1["top_speed_kph"]
    assert low <= ms_to_kph(reference_benchmark.top_speed) <= high


@pytest.mark.parametrize("target", [100, 200])
def test_acceleration_times_are_realistic(reference_benchmark, target):
    low, high = REFERENCE_F1[f"zero_to_{target}_kph"]
    assert low <= reference_benchmark.acceleration_times[target] <= high


def test_braking_distance_is_realistic(reference_benchmark):
    low, high = REFERENCE_F1["braking_200_to_0_m"]
    assert low <= reference_benchmark.braking_distances[200] <= high


def test_peak_accelerations_are_realistic(reference_benchmark):
    for key, value in (
        ("peak_lateral_g", reference_benchmark.peak_lateral_g),
        ("peak_braking_g", reference_benchmark.peak_braking_g),
        ("standing_acceleration_g", reference_benchmark.standing_acceleration_g),
    ):
        low, high = REFERENCE_F1[key]
        assert low <= value <= high, f"{key} = {value}"


# -- internal consistency ----------------------------------------------------


def test_reaching_a_higher_speed_takes_longer(reference_benchmark):
    times = [reference_benchmark.acceleration_times[t] for t in (100, 200, 300)]
    assert all(b > a for a, b in zip(times, times[1:]))


def test_stopping_from_a_higher_speed_takes_further(reference_benchmark):
    distances = [reference_benchmark.braking_distances[s] for s in (100, 200, 300)]
    assert all(b > a for a, b in zip(distances, distances[1:]))


def test_braking_distance_grows_less_than_the_square_of_speed(reference_benchmark):
    """A road car needs 4x the distance from twice the speed.  An F1 car needs
    less, because downforce means it brakes harder at high speed."""
    from_100 = reference_benchmark.braking_distances[100]
    from_200 = reference_benchmark.braking_distances[200]
    assert from_200 < 4.0 * from_100


def test_peak_lateral_occurs_at_high_speed(reference_benchmark):
    assert reference_benchmark.peak_lateral_speed > kph_to_ms(200.0)


def test_lateral_grip_rises_monotonically_with_speed(reference_benchmark):
    values = [v for _, v in sorted(reference_benchmark.lateral_g_by_speed.items())]
    assert all(b >= a for a, b in zip(values, values[1:]))


def test_bigger_corners_are_faster(reference_benchmark):
    speeds = [reference_benchmark.corner_speeds[r] for r in (25, 50, 100, 200)]
    assert all(b > a for a, b in zip(speeds, speeds[1:]))


def test_corner_speeds_never_exceed_top_speed(reference_benchmark):
    assert all(
        speed <= reference_benchmark.top_speed + 1e-6
        for speed in reference_benchmark.corner_speeds.values()
    )


# -- responds to the car -----------------------------------------------------


def test_wing_level_trades_top_speed_for_cornering(car):
    low = benchmark_vehicle(car.with_wing(0.0), corner_radii=(100,))
    high = benchmark_vehicle(car.with_wing(1.0), corner_radii=(100,))
    assert high.top_speed < low.top_speed
    assert high.corner_speeds[100] > low.corner_speeds[100]


def test_the_shipped_concepts_are_genuinely_different():
    """The power car must win the straights and lose the corners, from geometry
    and physics alone -- there is no per-car correction anywhere."""
    from f1_race_engine.vehicle import MEDIUM_DOWNFORCE, Vehicle
    from f1_race_engine.vehicle.io import load_builtin_vehicle

    power = benchmark_vehicle(
        Vehicle(load_builtin_vehicle("power_biased"), MEDIUM_DOWNFORCE),
        corner_radii=(100,),
    )
    aero = benchmark_vehicle(
        Vehicle(load_builtin_vehicle("aero_biased"), MEDIUM_DOWNFORCE),
        corner_radii=(100,),
    )
    assert power.top_speed > aero.top_speed
    assert power.acceleration_times[200] < aero.acceleration_times[200]
    assert aero.corner_speeds[100] > power.corner_speeds[100]


def test_fuel_load_costs_performance(car):
    light = benchmark_vehicle(car, mass=car.mass.total_mass(10.0), corner_radii=(100,))
    heavy = benchmark_vehicle(car, mass=car.mass.total_mass(110.0), corner_radii=(100,))
    assert heavy.acceleration_times[200] > light.acceleration_times[200]
    assert heavy.corner_speeds[100] < light.corner_speeds[100]
    assert heavy.braking_distances[200] > light.braking_distances[200]


def test_thin_air_raises_top_speed_and_lowers_cornering(car):
    dense = benchmark_vehicle(
        car, AmbientConditions(air_temperature=5.0), corner_radii=(100,)
    )
    thin = benchmark_vehicle(
        car, AmbientConditions(air_temperature=40.0), corner_radii=(100,)
    )
    assert thin.top_speed > dense.top_speed
    assert thin.corner_speeds[100] < dense.corner_speeds[100]


def test_softer_tyres_improve_everything_but_top_speed(car, compounds):
    from f1_race_engine.tyres import TyreState

    soft = benchmark_vehicle(
        car, tyre_state=TyreState(compound=compounds["S"]), corner_radii=(100,)
    )
    hard = benchmark_vehicle(
        car, tyre_state=TyreState(compound=compounds["H"]), corner_radii=(100,)
    )
    assert soft.corner_speeds[100] > hard.corner_speeds[100]
    assert soft.braking_distances[200] < hard.braking_distances[200]
    assert soft.peak_lateral_g > hard.peak_lateral_g


# -- output ------------------------------------------------------------------


def test_benchmark_export_is_json_serialisable(reference_benchmark):
    import json

    json.dumps(reference_benchmark.to_dict())


def test_formatted_report_flags_against_reality(reference_benchmark):
    text = format_benchmark(reference_benchmark)
    assert "VEHICLE BENCHMARK" in text
    assert "top speed" in text
    assert "ok" in text  # at least one figure lands in the published range


def test_unreachable_targets_are_reported_as_infinite(car):
    """A slow car must report 'n/a' rather than an invented number."""
    from dataclasses import replace

    feeble = car.with_spec(
        replace(
            car.spec,
            power_unit=replace(
                car.spec.power_unit, max_power=60_000.0
            ),
        )
    )
    result = benchmark_vehicle(feeble, speed_targets=(300,), braking_speeds=(300,), corner_radii=())
    assert math.isinf(result.acceleration_times[300])
    assert "n/a" in format_benchmark(result)
