"""Setup search -- the positive statement of project rule 2.3.

No per-track corrections means the circuit has to decide the setup on its own.
These tests assert that it does, and that different circuits decide
differently.
"""

from __future__ import annotations

import pytest

from f1_race_engine.physics.setup_search import (
    optimal_wing_level,
    wing_level_sweep,
)
from f1_race_engine.track.builder import build_track
from f1_race_engine.track.io import load_builtin_definition
from f1_race_engine.vehicle import Vehicle


@pytest.fixture(scope="module")
def circuits():
    from f1_race_engine.core.config import TrackBuildConfig

    config = TrackBuildConfig(
        straight_segment_length=30.0, corner_segment_length=20.0,
        min_segment_length=5.0, max_segment_length=30.0,
        max_heading_change_per_segment_deg=8.0,
        max_curvature_change_per_segment=0.01,
    )
    return {
        name: build_track(load_builtin_definition(name), config)
        for name in (
            "synthetic_power_circuit",
            "synthetic_proving_ground",
            "synthetic_street_circuit",
        )
    }


@pytest.fixture(scope="module")
def sweeps(circuits):
    from f1_race_engine.vehicle.io import load_builtin_vehicle

    spec = load_builtin_vehicle("reference_2024")
    return {
        name: wing_level_sweep(
            track, Vehicle(spec), levels=(0.0, 0.25, 0.5, 0.75, 1.0)
        )
        for name, track in circuits.items()
    }


def test_a_power_circuit_wants_less_wing_than_a_street_circuit(sweeps):
    """The whole point of project rule 2.3, measured.

    Nothing in the engine branches on a track name; the answer comes from
    corner radii and straight lengths meeting induced drag.
    """
    power = sweeps["synthetic_power_circuit"].best.wing_level
    street = sweeps["synthetic_street_circuit"].best.wing_level
    assert power < street


def test_the_optimum_spans_the_range(sweeps):
    optima = {name: sweep.best.wing_level for name, sweep in sweeps.items()}
    assert min(optima.values()) <= 0.05
    assert max(optima.values()) >= 0.95


def test_setup_choice_is_worth_real_lap_time(sweeps):
    for name, sweep in sweeps.items():
        assert sweep.spread > 1.0, f"{name}: wing level barely matters"


def test_more_wing_always_lowers_top_speed(sweeps):
    for sweep in sweeps.values():
        speeds = [point.top_speed for point in sweep.points]
        assert all(b < a for a, b in zip(speeds, speeds[1:]))


def test_more_wing_never_lowers_the_slowest_corner(sweeps):
    for sweep in sweeps.values():
        speeds = [point.minimum_speed for point in sweep.points]
        assert all(b >= a - 1e-6 for a, b in zip(speeds, speeds[1:]))


def test_a_balanced_circuit_has_an_interior_optimum(circuits):
    """The clearest evidence the trade-off is real: the circuit wants some
    downforce, but not all of it."""
    from f1_race_engine.vehicle.io import load_builtin_vehicle

    # Levels spread evenly across the range: a sweep bunched at one end cannot
    # tell an interior optimum from an endpoint, whatever the circuit does.
    sweep = wing_level_sweep(
        circuits["synthetic_proving_ground"],
        Vehicle(load_builtin_vehicle("reference_2024")),
        levels=(0.0, 0.2, 0.4, 0.6, 0.8, 1.0),
    )
    assert sweep.is_interior_optimum
    assert 0.0 < sweep.best.wing_level < 1.0


def test_optimal_wing_level_refines_the_coarse_answer(circuits):
    from f1_race_engine.vehicle.io import load_builtin_vehicle

    car = Vehicle(load_builtin_vehicle("reference_2024"))
    best = optimal_wing_level(
        circuits["synthetic_proving_ground"], car, coarse_steps=6
    )
    assert 0.0 <= best <= 1.0
    coarse = optimal_wing_level(
        circuits["synthetic_proving_ground"], car, coarse_steps=6, refine=False
    )
    assert abs(best - coarse) <= 0.25


def test_sweep_export_is_json_serialisable(sweeps):
    import json

    json.dumps(sweeps["synthetic_proving_ground"].to_dict())


def test_the_right_car_wins_the_right_circuit(circuits):
    """The strongest single test of rule 2.3: swapping circuits flips which
    car is quicker, with no per-track number anywhere."""
    from f1_race_engine.physics import compute_lap_time
    from f1_race_engine.vehicle import VehicleSetup
    from f1_race_engine.vehicle.io import load_builtin_vehicle

    setup = VehicleSetup(wing_level=0.5)
    power_car = Vehicle(load_builtin_vehicle("power_biased"), setup)
    aero_car = Vehicle(load_builtin_vehicle("aero_biased"), setup)

    on_power_circuit = (
        compute_lap_time(
            circuits["synthetic_power_circuit"], power_car, analyse_zones=False
        ).lap_time,
        compute_lap_time(
            circuits["synthetic_power_circuit"], aero_car, analyse_zones=False
        ).lap_time,
    )
    on_street_circuit = (
        compute_lap_time(
            circuits["synthetic_street_circuit"], power_car, analyse_zones=False
        ).lap_time,
        compute_lap_time(
            circuits["synthetic_street_circuit"], aero_car, analyse_zones=False
        ).lap_time,
    )
    assert on_power_circuit[0] < on_power_circuit[1], "power car must win the power circuit"
    assert on_street_circuit[1] < on_street_circuit[0], "aero car must win the street circuit"
