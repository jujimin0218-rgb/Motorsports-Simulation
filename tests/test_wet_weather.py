"""Running in the wet (project rule 30).

Two separate things happen when it rains and the engine keeps them separate:
the asphalt gets slippery, which applies to every tyre, and the tyre has to
evacuate the standing water, which is entirely about tread pattern.  Every
behaviour a wet race has follows from the second one.
"""

from __future__ import annotations

import math

import pytest

from f1_race_engine.core.config import TrackEvolutionConfig, WetConfig
from f1_race_engine.core.rng import RngHub
from f1_race_engine.environment import AmbientConditions, TrackEvolution
from f1_race_engine.simulation import LapSimulator
from f1_race_engine.track.surface import TrackConditions
from f1_race_engine.tyres import TyreState
from f1_race_engine.tyres.wet import aquaplaning_speed, water_clearance, wet_grip_factor


@pytest.fixture
def slick(compounds):
    return compounds["M"]


@pytest.fixture
def inter(compounds):
    return compounds["I"]


@pytest.fixture
def full_wet(compounds):
    return compounds["W"]


# -- clearance ---------------------------------------------------------------


def test_a_slick_clears_nothing_at_any_speed(slick):
    assert slick.peak_water_depth == 0.0
    for speed in (5.0, 40.0, 90.0):
        assert water_clearance(slick, speed) == 0.0


def test_a_grooved_tyre_clears_less_the_faster_it_goes(full_wet):
    slow = water_clearance(full_wet, 20.0)
    reference = water_clearance(full_wet, 40.0)
    fast = water_clearance(full_wet, 90.0)
    assert slow == reference == pytest.approx(full_wet.peak_water_depth)
    assert fast < reference


def test_a_full_wet_clears_more_than_an_intermediate(inter, full_wet):
    assert water_clearance(full_wet, 60.0) > water_clearance(inter, 60.0)


# -- what unevacuated water does ---------------------------------------------


def test_a_dry_track_costs_nothing(slick, full_wet):
    for compound in (slick, full_wet):
        assert wet_grip_factor(compound, 0.0, 70.0) == 1.0


def test_a_slick_on_a_wet_track_is_in_trouble_immediately(slick):
    assert wet_grip_factor(slick, 0.0005, 40.0) < 0.6


def test_a_wet_tyre_in_its_element_loses_nothing_here(full_wet):
    """The surface penalty has already been charged; this is only the water the
    tread cannot get rid of, and a full wet in 2 mm gets rid of all of it."""
    assert wet_grip_factor(full_wet, 0.002, 50.0) == 1.0


def test_deeper_water_is_worse(inter):
    depths = (0.001, 0.003, 0.006, 0.010)
    factors = [wet_grip_factor(inter, d, 70.0) for d in depths]
    assert all(b <= a for a, b in zip(factors, factors[1:]))
    assert factors[-1] < factors[0]


def test_going_faster_in_standing_water_is_worse(inter):
    assert wet_grip_factor(inter, 0.004, 90.0) < wet_grip_factor(inter, 0.004, 30.0)


def test_grip_never_reaches_zero(slick):
    floor = WetConfig().min_wet_grip
    assert wet_grip_factor(slick, 1.0, 100.0) == pytest.approx(floor)


# -- aquaplaning as a speed limit --------------------------------------------


def test_aquaplaning_is_a_speed_not_a_coin_flip(inter):
    speed = aquaplaning_speed(inter, 0.002)
    assert math.isfinite(speed)
    assert wet_grip_factor(inter, 0.002, speed * 0.8) == 1.0
    assert wet_grip_factor(inter, 0.002, speed * 1.5) < 1.0


def test_deeper_water_lowers_the_speed_limit(full_wet):
    assert aquaplaning_speed(full_wet, 0.006) < aquaplaning_speed(full_wet, 0.002)


def test_a_wet_tyre_survives_water_that_floats_an_intermediate(inter, full_wet):
    assert aquaplaning_speed(full_wet, 0.004) > aquaplaning_speed(inter, 0.004)


def test_a_slick_has_no_safe_speed_in_standing_water(slick):
    assert aquaplaning_speed(slick, 0.001) == 0.0
    assert aquaplaning_speed(slick, 0.0) == float("inf")


# -- on the road -------------------------------------------------------------


def _wet_track(track, depth):
    conditions = TrackConditions(track.segments)
    for index in range(len(conditions)):
        conditions[index].water_depth = depth
    return conditions


def _lap(track, car, driver, compound, depth, seed=5):
    ambient = AmbientConditions(
        air_temperature=16.0, track_temperature=20.0,
        rain_intensity=min(depth / 0.004, 1.0),
    )
    simulator = LapSimulator(
        track, car, driver, rng=RngHub(seed), ambient=ambient,
        conditions=_wet_track(track, depth),
    )
    return simulator.simulate(
        tyre_state=TyreState(compound=compound), record_telemetry=False
    )


def test_the_right_tyre_changes_with_the_depth(
    fast_track, car, perfect_driver, slick, inter, full_wet
):
    """Nothing tells the engine what an intermediate is for.  Run all three on
    a dry track, a damp one and a flooded one, and the ordering falls out."""
    best = {}
    for depth in (0.0, 0.0004, 0.005):
        times = {
            compound.code: _lap(fast_track, car, perfect_driver, compound, depth).lap_time
            for compound in (slick, inter, full_wet)
        }
        best[depth] = min(times, key=times.get)
    assert best[0.0] == "M"
    assert best[0.0004] == "I"
    assert best[0.005] == "W"


def test_a_slick_on_a_flooded_track_is_barely_drivable(
    fast_track, car, perfect_driver, slick, full_wet
):
    slow = _lap(fast_track, car, perfect_driver, slick, 0.005)
    wet = _lap(fast_track, car, perfect_driver, full_wet, 0.005)
    assert slow.lap_time > wet.lap_time * 1.5
    assert slow.top_speed < wet.top_speed


def test_a_wet_race_is_slower_but_not_absurd(
    fast_track, car, perfect_driver, slick, full_wet
):
    dry = _lap(fast_track, car, perfect_driver, slick, 0.0)
    wet = _lap(fast_track, car, perfect_driver, full_wet, 0.002)
    assert 1.1 < wet.lap_time / dry.lap_time < 1.5


def test_standing_water_keeps_the_tyres_cool(
    fast_track, car, perfect_driver, full_wet
):
    """Which is the whole reason a wet-weather compound has a low working
    window, and the reason it destroys itself once the line dries."""
    wet = _lap(fast_track, car, perfect_driver, full_wet, 0.003)
    drying = _lap(fast_track, car, perfect_driver, full_wet, 0.0)
    assert wet.tyre_temperature < drying.tyre_temperature


def test_wet_weather_ability_is_worth_something_in_the_wet(
    fast_track, car, lineup, full_wet
):
    """A driver's wet skill acts through their commitment, so what it is worth
    is decided by the physics rather than by a bonus."""
    ranked = sorted(lineup, key=lambda d: d.attributes.wet_skill)
    poor, good = ranked[0], ranked[-1]
    dry_gap = (
        _lap(fast_track, car, poor, full_wet, 0.0).lap_time
        - _lap(fast_track, car, good, full_wet, 0.0).lap_time
    )
    wet_gap = (
        _lap(fast_track, car, poor, full_wet, 0.003).lap_time
        - _lap(fast_track, car, good, full_wet, 0.003).lap_time
    )
    assert wet_gap > dry_gap


# -- the track itself --------------------------------------------------------


def test_running_rubbers_a_track_in(proving_ground):
    conditions = TrackConditions(proving_ground.segments)
    evolution = TrackEvolution(conditions)
    green = conditions.grip_multiplier(0)
    evolution.run_laps(200.0)
    assert conditions.mean_rubber > 0.5
    assert conditions.grip_multiplier(0) > green


def test_rubbering_in_saturates(proving_ground):
    conditions = TrackConditions(proving_ground.segments)
    evolution = TrackEvolution(conditions)
    evolution.run_laps(2000.0)
    assert conditions.mean_rubber <= 1.0


def test_marbles_cost_nothing_on_the_racing_line(proving_ground):
    """They collect beside it, which is exactly why leaving the line is
    expensive and why a car on it gains grip through a session."""
    conditions = TrackConditions(proving_ground.segments)
    TrackEvolution(conditions).run_laps(400.0)
    assert conditions[0].marbles > 0.0
    assert conditions.grip_multiplier(0, off_line=True) < conditions.grip_multiplier(0)


def test_rain_puts_water_down_and_it_drains_away(proving_ground):
    conditions = TrackConditions(proving_ground.segments)
    evolution = TrackEvolution(conditions)
    from f1_race_engine.environment import WeatherState

    evolution.apply_weather(WeatherState(rain_intensity=0.8, raining=True), 600.0)
    flooded = evolution.mean_water_depth
    assert flooded > 0.001
    evolution.apply_weather(WeatherState(rain_intensity=0.0), 1800.0)
    assert evolution.mean_water_depth < flooded


def test_the_track_does_not_care_how_the_time_was_chunked(proving_ground):
    """Rule 12 applied to time: every process here is integrated in closed
    form, so an hour in one call and an hour in sixty give the same track."""
    from f1_race_engine.environment import WeatherState

    steady = WeatherState(rain_intensity=0.7, raining=True)

    one = TrackConditions(proving_ground.segments)
    coarse = TrackEvolution(one)
    coarse.apply_weather(steady, 3600.0)
    coarse.run_laps(300.0)

    many = TrackConditions(proving_ground.segments)
    fine = TrackEvolution(many)
    for _ in range(60):
        fine.apply_weather(steady, 60.0)
    for _ in range(60):
        fine.run_laps(5.0)

    assert coarse.mean_water_depth == pytest.approx(fine.mean_water_depth, rel=1e-9)
    assert one.mean_rubber == pytest.approx(many.mean_rubber, rel=1e-9)


def test_water_settles_at_a_depth_rather_than_rising_forever(proving_ground):
    conditions = TrackConditions(proving_ground.segments)
    evolution = TrackEvolution(conditions)
    from f1_race_engine.environment import WeatherState

    steady = WeatherState(rain_intensity=1.0, raining=True)
    evolution.apply_weather(steady, 1800.0)
    early = evolution.mean_water_depth
    evolution.apply_weather(steady, 1800.0)
    assert evolution.mean_water_depth == pytest.approx(early, rel=0.05)


def test_a_slope_drains_faster_than_a_dip(proving_ground):
    from f1_race_engine.environment import WeatherState

    conditions = TrackConditions(proving_ground.segments)
    evolution = TrackEvolution(conditions)
    evolution.apply_weather(WeatherState(rain_intensity=1.0, raining=True), 1200.0)
    depths = [(abs(conditions.segment_gradient(i)), conditions[i].water_depth)
              for i in range(len(conditions))]
    flattest = min(depths)[1]
    steepest = max(depths)[1]
    assert steepest < flattest


def test_cars_dry_the_racing_line(proving_ground):
    from f1_race_engine.environment import WeatherState

    conditions = TrackConditions(proving_ground.segments)
    evolution = TrackEvolution(conditions)
    evolution.apply_weather(WeatherState(rain_intensity=0.6, raining=True), 900.0)
    wet = evolution.mean_water_depth
    assert wet > 0.0
    evolution.run_laps(300.0)
    assert evolution.mean_water_depth < wet


def test_rain_washes_the_rubber_away(proving_ground):
    """Which is why a track that goes green in a shower is slow again
    afterwards, even once it is dry."""
    from f1_race_engine.environment import WeatherState

    conditions = TrackConditions(proving_ground.segments)
    evolution = TrackEvolution(conditions)
    evolution.run_laps(400.0)
    rubbered = conditions.mean_rubber
    evolution.apply_weather(WeatherState(rain_intensity=1.0, raining=True), 1800.0)
    assert conditions.mean_rubber < rubbered


def test_a_dry_session_never_becomes_wet(proving_ground):
    from f1_race_engine.environment import WeatherState

    conditions = TrackConditions(proving_ground.segments)
    evolution = TrackEvolution(conditions)
    evolution.apply_weather(WeatherState(rain_intensity=0.0), 3600.0)
    evolution.run_laps(500.0)
    assert evolution.wet_fraction == 0.0


def test_a_drained_segment_reads_as_dry(proving_ground):
    """Floating point never reaches zero, so a threshold decides when a damp
    patch stops being standing water."""
    from f1_race_engine.environment import WeatherState

    config = TrackEvolutionConfig()
    conditions = TrackConditions(proving_ground.segments)
    evolution = TrackEvolution(conditions, config)
    evolution.apply_weather(WeatherState(rain_intensity=0.5, raining=True), 600.0)
    evolution.apply_weather(WeatherState(rain_intensity=0.0), 7200.0)
    assert evolution.wet_fraction == 0.0
