"""The pit lane and what a stop costs (project rule 32).

    "피트스탑 시간 손실은 상수로 두지 않는다."

There is no constant.  A stop is priced as the difference between two journeys
between the same two points on the circuit, and every behaviour a strategist
needs comes out of that subtraction.
"""

from __future__ import annotations

import pytest

from f1_race_engine.core.errors import ConfigError
from f1_race_engine.physics import compute_speed_profile
from f1_race_engine.race import PitLane, pit_loss


@pytest.fixture
def lane(fast_track):
    return PitLane.for_track(fast_track.length)


@pytest.fixture
def profile(fast_track, car):
    return compute_speed_profile(fast_track, car)


def _loss(car, lane, profile, **overrides):
    from dataclasses import replace

    return pit_loss(car, replace(lane, **overrides), profile).total


# -- the price is real -------------------------------------------------------


def test_a_stop_costs_a_plausible_amount(car, lane, profile):
    loss = pit_loss(car, lane, profile)
    assert 10.0 < loss.total < 35.0
    assert loss.lane_time > loss.track_time


def test_the_pieces_add_up(car, lane, profile):
    loss = pit_loss(car, lane, profile)
    assert loss.total >= loss.lane_time - loss.track_time
    assert loss.stationary == pytest.approx(lane.stationary_time)


def test_a_longer_pit_lane_costs_more(car, lane, profile):
    assert _loss(car, lane, profile, length=650.0) > _loss(
        car, lane, profile, length=350.0
    )


def test_a_higher_speed_limit_costs_less(car, lane, profile):
    assert _loss(car, lane, profile, speed_limit=27.8) < _loss(
        car, lane, profile, speed_limit=16.7
    )


def test_a_quicker_crew_costs_less(car, lane, profile):
    quick = _loss(car, lane, profile, stationary_time=1.9)
    slow = _loss(car, lane, profile, stationary_time=3.5)
    assert slow - quick == pytest.approx(1.6, abs=1e-6)


def test_the_crew_and_the_lane_are_separate_things(car, lane, profile):
    """Changing one must not move the other, or they are not separable."""
    from dataclasses import replace

    base = replace(lane, stationary_time=2.0, length=400.0)
    longer = pit_loss(car, replace(base, length=600.0), profile).total - pit_loss(
        car, base, profile
    ).total
    with_slow_crew = replace(base, stationary_time=4.0)
    longer_again = pit_loss(
        car, replace(with_slow_crew, length=600.0), profile
    ).total - pit_loss(car, with_slow_crew, profile).total
    assert longer == pytest.approx(longer_again, rel=1e-9)


def test_the_price_differs_between_circuits(car, coarse_build_config):
    """Rule 2.3 at the level of strategy: the same pit lane costs different
    amounts at different circuits, because the road it replaces differs."""
    from f1_race_engine.track.builder import build_track
    from f1_race_engine.track.io import load_builtin_definition

    losses = {}
    for name in ("synthetic_power_circuit", "synthetic_street_circuit"):
        track = build_track(load_builtin_definition(name), coarse_build_config)
        lane = PitLane(
            entry_distance=track.length * 0.9,
            exit_distance=track.length * 0.97,
            length=400.0,
        )
        losses[name] = pit_loss(
            car, lane, compute_speed_profile(track, car)
        ).total
    assert losses["synthetic_power_circuit"] != losses["synthetic_street_circuit"]


def test_a_car_that_accelerates_better_loses_less(lane, profile, reference_spec):
    from f1_race_engine.vehicle import MEDIUM_DOWNFORCE, Vehicle
    from f1_race_engine.vehicle.io import load_builtin_vehicle

    reference = Vehicle(reference_spec, MEDIUM_DOWNFORCE)
    powerful = Vehicle(load_builtin_vehicle("power_biased"), MEDIUM_DOWNFORCE)
    assert pit_loss(powerful, lane, profile).total < pit_loss(
        reference, lane, profile
    ).total


# -- the geometry ------------------------------------------------------------


def test_an_impossible_pit_lane_is_rejected():
    with pytest.raises(ConfigError):
        PitLane(entry_distance=0.0, exit_distance=100.0, length=0.0)
    with pytest.raises(ConfigError):
        PitLane(entry_distance=0.0, exit_distance=100.0, length=200.0, speed_limit=0.0)


def test_a_pit_lane_round_trips():
    lane = PitLane(entry_distance=100.0, exit_distance=400.0, length=350.0)
    assert PitLane.from_dict(lane.to_dict()) == lane


def test_an_unknown_key_is_rejected():
    with pytest.raises(ConfigError):
        PitLane.from_dict({"length": 300.0, "colour": "red"})


def test_a_default_lane_fits_the_circuit(fast_track):
    lane = PitLane.for_track(fast_track.length)
    assert 0.0 <= lane.entry_distance < lane.exit_distance <= fast_track.length
    assert lane.length > 0.0


# -- the profile can price the road it replaces ------------------------------


def test_the_pieces_of_a_lap_add_up_to_the_lap(fast_track, car):
    profile = compute_speed_profile(fast_track, car)
    whole = profile.time_between(0.0, fast_track.length)
    halves = profile.time_between(0.0, fast_track.length / 2) + profile.time_between(
        fast_track.length / 2, fast_track.length
    )
    assert whole == pytest.approx(halves, rel=1e-9)


def test_a_journey_past_the_line_continues_on_the_next_lap(fast_track, car):
    profile = compute_speed_profile(fast_track, car)
    wrapped = profile.time_between(fast_track.length - 100.0, fast_track.length + 200.0)
    direct = profile.time_between(fast_track.length - 100.0, fast_track.length)
    direct += profile.time_between(0.0, 200.0)
    assert wrapped == pytest.approx(direct, rel=1e-12)
