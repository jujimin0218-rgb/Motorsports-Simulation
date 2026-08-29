"""Dirty air and the tow (project rule 29).

Two effects, opposite in sign, and both of them are the same hole in the air.
Neither is a lap-time penalty: they are multipliers on two aerodynamic
coefficients, and what they cost is worked out by the same model that decides
everything else.
"""

from __future__ import annotations

import pytest

from f1_race_engine.core.config import WakeConfig
from f1_race_engine.physics.lateral import corner_speed_limit
from f1_race_engine.race.wake import CLEAN_AIR, wake_effect


# -- the shape of it ---------------------------------------------------------


def test_clean_air_is_clean():
    assert wake_effect(float("inf")) is CLEAN_AIR
    assert CLEAN_AIR.downforce_factor == 1.0
    assert CLEAN_AIR.drag_factor == 1.0
    assert not CLEAN_AIR.in_traffic


def test_following_costs_downforce():
    assert wake_effect(1.0).downforce_factor < 1.0


def test_following_saves_drag():
    assert wake_effect(1.0).drag_factor < 1.0


def test_closer_is_worse_and_better_at_the_same_time():
    close, far = wake_effect(0.3), wake_effect(1.5)
    assert close.downforce_factor < far.downforce_factor
    assert close.drag_factor < far.drag_factor


def test_far_enough_back_is_clean_air():
    config = WakeConfig(range=2.0)
    assert not wake_effect(3.0, config).in_traffic


def test_the_downforce_loss_sits_between_the_two_figures_the_fia_published():
    """A 2022 car lost 18% of its downforce at ten metres and 4% at twenty.

    At racing speed those distances are roughly 0.15 s and 0.35 s of gap, and a
    2024 car belongs between the two: the teams recovered much of the wake
    performance the regulations took away, but not all of it.
    """
    assert 0.04 < wake_effect(0.15).downforce_loss < 0.18
    assert 0.04 < wake_effect(0.35).downforce_loss < 0.18


def test_following_costs_a_few_tenths_rather_than_a_few_seconds():
    """The check that matters, because it is the one racing performs weekly.

    Cars run in DRS trains: half a dozen of them nose to tail, lap after lap,
    for a whole stint.  That is only possible if the dirty air costs a few
    tenths a lap.  If it cost seconds the train would stretch out and break up
    on its own within two laps, and it does not.
    """
    close = wake_effect(0.5).downforce_loss
    train = wake_effect(1.0).downforce_loss

    # Losing one per cent of downforce is worth 0.09-0.13 s a lap on the
    # circuits here, measured; see docs/REALISM_REVIEW.md.
    seconds_per_percent = 0.11
    assert 0.3 < 100 * close * seconds_per_percent < 1.0
    assert 0.1 < 100 * train * seconds_per_percent < 0.5

    # And it has to fade: a car two seconds back is racing in clean air.
    assert 100 * wake_effect(2.0).downforce_loss * seconds_per_percent < 0.15


def test_the_tow_is_worth_a_tenth_or_so():
    assert 0.04 < wake_effect(0.5).drag_saving < 0.20


def test_grip_never_disappears_entirely():
    floor = WakeConfig().minimum_downforce
    assert wake_effect(0.0).downforce_factor >= floor


def test_a_negative_gap_is_treated_as_nose_to_tail():
    assert wake_effect(-1.0).downforce_factor == wake_effect(0.0).downforce_factor


def test_the_effect_serialises():
    payload = wake_effect(0.8).to_dict()
    assert payload["gap"] == pytest.approx(0.8)
    assert CLEAN_AIR.to_dict()["gap"] is None


# -- what it does to a car ---------------------------------------------------


def test_dirty_air_lowers_the_corner_speed(car):
    clean = corner_speed_limit(car, 1 / 100.0, 1.2)
    dirty = corner_speed_limit(
        car, 1 / 100.0, 1.2, downforce_factor=wake_effect(0.5).downforce_factor
    )
    assert dirty < clean


def test_it_costs_more_in_a_fast_corner_than_a_slow_one(car):
    """Downforce is what a fast corner is taken on and barely matters in a slow
    one, so losing it is not a flat penalty -- which is why following is much
    harder at some circuits than others."""
    factor = wake_effect(0.5).downforce_factor

    def loss(radius):
        clean = corner_speed_limit(car, 1 / radius, 1.2)
        dirty = corner_speed_limit(car, 1 / radius, 1.2, downforce_factor=factor)
        return (clean - dirty) / clean

    # Both radii have to be grip-limited: a corner the car takes flat out
    # is not a corner as far as downforce is concerned.
    assert loss(200.0) > loss(35.0)


def test_a_lap_in_dirty_air_alone_is_always_slower(
    fast_track, car, perfect_driver, monkeypatch
):
    from dataclasses import replace

    from f1_race_engine.core.rng import RngHub
    from f1_race_engine.simulation import LapSimulator
    from f1_race_engine.simulation.traffic import TrafficState

    class DirtyAir:
        """Turbulence with the tow taken out, to separate the two."""

        def __init__(self, gap):
            self.state = TrafficState(
                wake=replace(wake_effect(gap), drag_factor=1.0)
            )

        def preview(self, **_):
            return self.state

        def at(self, **_):
            return self.state

    simulator = LapSimulator(fast_track, car, perfect_driver, rng=RngHub(3))
    clean = simulator.simulate(record_telemetry=False).lap_time
    for gap in (1.5, 1.0, 0.5):
        assert simulator.simulate(
            traffic=DirtyAir(gap), record_telemetry=False
        ).lap_time > clean


def test_whether_following_is_worth_it_depends_on_the_circuit(
    car, perfect_driver, coarse_build_config
):
    """A tow is worth a lot where there are straights to use it on and nothing
    at all where there are not.  Nobody wrote that down."""
    from f1_race_engine.core.rng import RngHub
    from f1_race_engine.simulation import LapSimulator
    from f1_race_engine.simulation.traffic import TrafficState
    from f1_race_engine.track.builder import build_track
    from f1_race_engine.track.io import load_builtin_definition

    class Wake:
        def __init__(self, gap):
            self.state = TrafficState(wake=wake_effect(gap))

        def preview(self, **_):
            return self.state

        def at(self, **_):
            return self.state

    net = {}
    for name in ("synthetic_power_circuit", "synthetic_street_circuit"):
        track = build_track(load_builtin_definition(name), coarse_build_config)
        simulator = LapSimulator(track, car, perfect_driver, rng=RngHub(3))
        clean = simulator.simulate(record_telemetry=False).lap_time
        following = simulator.simulate(
            traffic=Wake(0.5), record_telemetry=False
        ).lap_time
        net[name] = (following - clean) / clean
    assert net["synthetic_power_circuit"] < net["synthetic_street_circuit"]
