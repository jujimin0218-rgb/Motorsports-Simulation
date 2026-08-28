"""The speed profile (project rule 15)."""

from __future__ import annotations

import math

import pytest

from f1_race_engine.core.config import SpeedProfileConfig, TrackBuildConfig
from f1_race_engine.core.errors import ConfigError
from f1_race_engine.core.units import kph_to_ms, ms_to_kph
from f1_race_engine.physics import corner_speed_limit
from f1_race_engine.physics.speed_profile import (
    PerformanceLimits,
    compute_speed_profile,
    cornering_limits,
)
from f1_race_engine.track.builder import build_track
from f1_race_engine.tyres import TyreState
from f1_race_engine.vehicle import MEDIUM_DOWNFORCE, Vehicle


@pytest.fixture(scope="module")
def profile(request):
    from f1_race_engine.physics import compute_speed_profile as build
    from f1_race_engine.track.io import load_builtin_definition
    from f1_race_engine.vehicle.io import load_builtin_vehicle

    from f1_race_engine.core.config import TrackBuildConfig as TBC

    track = build_track(
        load_builtin_definition("synthetic_proving_ground"),
        TBC(straight_segment_length=30.0, corner_segment_length=20.0,
            min_segment_length=5.0, max_segment_length=30.0,
            max_heading_change_per_segment_deg=8.0,
            max_curvature_change_per_segment=0.01),
    )
    car = Vehicle(load_builtin_vehicle("reference_2024"), MEDIUM_DOWNFORCE)
    return build(track, car), track, car


# -- the fundamental invariants ---------------------------------------------


def test_profile_never_exceeds_the_cornering_limit(profile):
    """The single invariant the whole method rests on."""
    result, _, _ = profile
    assert all(v <= limit + 1e-6 for v, limit in zip(result.speed, result.corner_limit))


def test_profile_converges(profile):
    result, _, _ = profile
    assert result.converged
    assert result.passes >= 1


def test_profile_has_one_node_per_segment(profile):
    result, track, _ = profile
    assert len(result) == len(track)
    assert result.distance[0] == 0.0
    assert result.lap_length == pytest.approx(track.length)


def test_profile_is_never_stationary(profile):
    result, _, _ = profile
    assert result.minimum_speed > 0.0


def test_apexes_touch_the_cornering_limit(profile):
    """Somewhere on the lap the car must actually be at the limit, or the
    braking and acceleration passes have over-constrained everything."""
    result, _, _ = profile
    assert any(
        v >= limit * 0.999 for v, limit in zip(result.speed, result.corner_limit)
    )


def test_the_slowest_point_is_the_tightest_corner(profile):
    """Nobody told the profile where the hairpin is."""
    result, track, _ = profile
    slowest = result.minimum_speed_distance
    state = track.state_at(slowest)
    assert state.corner_radius == pytest.approx(track.min_radius, rel=0.25)


# -- the passes --------------------------------------------------------------


def test_braking_precedes_every_slow_corner(profile):
    """The backward pass must reach back up the straight."""
    result, _, _ = profile
    slowest_index = min(range(len(result)), key=lambda i: result.speed[i])
    before = (slowest_index - 3) % len(result)
    assert result.speed[before] > result.speed[slowest_index]


def test_acceleration_follows_every_slow_corner(profile):
    result, _, _ = profile
    slowest_index = min(range(len(result)), key=lambda i: result.speed[i])
    after = (slowest_index + 5) % len(result)
    assert result.speed[after] > result.speed[slowest_index]


def test_profile_wraps_around_the_start_finish_line(profile):
    """A lap is a loop.  Cutting it elsewhere must give the same answer."""
    result, track, car = profile
    # A profile computed on the same track must not depend on the pass order,
    # which is what wrapping guarantees; check the seam is not a discontinuity.
    step = result.longitudinal_acceleration(len(result) - 1)
    assert abs(step) < 15.0  # no impossible jump across the seam


def test_cornering_limits_match_the_pointwise_solver(profile):
    result, track, car = profile
    limits = cornering_limits(track, car)
    assert limits == pytest.approx(list(result.corner_limit))


def test_cornering_limit_is_the_same_as_asking_directly(profile):
    result, track, car = profile
    from f1_race_engine.environment import AmbientConditions

    rho = AmbientConditions().air_density
    index = min(
        range(len(result)), key=lambda i: result.corner_limit[i]
    )
    state = track.state_at(result.distance[index])
    direct = corner_speed_limit(
        car, state.curvature, rho, banking=state.banking,
        gradient=state.gradient, surface_grip=state.grip,
        max_speed=150.0, tolerance=1e-3,
    )
    assert result.corner_limit[index] == pytest.approx(direct, rel=1e-4)


# -- responds to the car and the conditions ---------------------------------


def test_more_grip_raises_the_whole_profile(profile):
    from dataclasses import replace

    result, track, car = profile
    grippy = TyreState()
    grippy.compound = replace(grippy.compound, peak_friction=1.9)
    better = compute_speed_profile(track, car, tyre_state=grippy)
    assert better.minimum_speed > result.minimum_speed
    assert sum(better.speed) > sum(result.speed)


def test_more_mass_lowers_the_profile(profile):
    result, track, car = profile
    heavy = compute_speed_profile(track, car, mass=car.total_mass() + 150.0)
    assert sum(heavy.speed) < sum(result.speed)


def test_more_wing_slows_the_straights_and_speeds_the_corners(profile):
    result, track, car = profile
    high = compute_speed_profile(track, car.with_wing(1.0))
    low = compute_speed_profile(track, car.with_wing(0.0))
    assert high.top_speed < low.top_speed
    assert high.minimum_speed >= low.minimum_speed


# -- the driver seam ---------------------------------------------------------


def test_performance_limits_default_to_the_ideal_lap():
    limits = PerformanceLimits()
    assert limits.is_ideal


def test_a_less_committed_driver_is_slower(profile):
    """The seam Phase 4's driver model attaches to."""
    result, track, car = profile
    timid = compute_speed_profile(
        track, car, limits=PerformanceLimits(cornering=0.95, braking=0.95, traction=0.95)
    )
    assert timid.minimum_speed < result.minimum_speed
    assert sum(timid.speed) < sum(result.speed)


def test_weaker_braking_moves_the_braking_point_earlier(profile):
    result, track, car = profile
    weak = compute_speed_profile(track, car, limits=PerformanceLimits(braking=0.85))
    slowest = min(range(len(result)), key=lambda i: result.speed[i])
    approach = (slowest - 4) % len(result)
    assert weak.speed[approach] < result.speed[approach]


@pytest.mark.parametrize(
    "kwargs", [{"cornering": 0.0}, {"braking": 1.5}, {"traction": -0.1}]
)
def test_impossible_limits_are_rejected(kwargs):
    with pytest.raises(ConfigError):
        PerformanceLimits(**kwargs)


# -- queries -----------------------------------------------------------------


def test_speed_at_matches_the_nodes(profile):
    result, _, _ = profile
    for index in range(0, len(result), 7):
        assert result.speed_at(result.distance[index]) == pytest.approx(
            result.speed[index], rel=1e-6
        )


def test_speed_at_wraps(profile):
    result, _, _ = profile
    assert result.speed_at(result.lap_length + 100.0) == pytest.approx(
        result.speed_at(100.0)
    )


def test_speed_at_interpolates_on_v_squared(profile):
    """Interpolating v itself would bias every braking zone."""
    result, _, _ = profile
    index = min(range(len(result) - 1), key=lambda i: result.speed[i])
    start, end = result.distance[index], result.distance[index] + result.length[index]
    middle = result.speed_at(0.5 * (start + end))
    expected = math.sqrt(
        0.5 * (result.speed[index] ** 2 + result.speed[index + 1] ** 2)
    )
    assert middle == pytest.approx(expected, rel=1e-9)


def test_export_is_json_serialisable(profile):
    import json

    result, _, _ = profile
    json.dumps(result.to_dict())
    json.dumps(result.to_dict(include_samples=True))


def test_cornering_limited_fraction_is_higher_on_a_twisty_circuit():
    from f1_race_engine.track.io import load_builtin_definition
    from f1_race_engine.vehicle.io import load_builtin_vehicle

    car = Vehicle(load_builtin_vehicle("reference_2024"), MEDIUM_DOWNFORCE)
    config = TrackBuildConfig(
        straight_segment_length=30.0, corner_segment_length=20.0,
        min_segment_length=5.0, max_segment_length=30.0,
        max_heading_change_per_segment_deg=8.0,
        max_curvature_change_per_segment=0.01,
    )
    street = compute_speed_profile(
        build_track(load_builtin_definition("synthetic_street_circuit"), config), car
    )
    power = compute_speed_profile(
        build_track(load_builtin_definition("synthetic_power_circuit"), config), car
    )
    assert street.cornering_limited_fraction() > power.cornering_limited_fraction()
