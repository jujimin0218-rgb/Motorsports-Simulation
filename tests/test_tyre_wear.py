"""Tyre wear and degradation (project rule 22).

    "타이어 열화는 단순히 매 랩 일정한 시간을 더하는 방식으로 만들지 않는다."

Nothing in this module counts laps.  Wear is dissipated work, and every
behaviour a strategist cares about has to fall out of that.
"""

from __future__ import annotations

import pytest

from f1_race_engine.core.config import TyreWearConfig
from f1_race_engine.tyres import TyreCompound, TyreState
from f1_race_engine.tyres.degradation import thermal_damage_increment, wear_grip_factor
from f1_race_engine.tyres.wear import (
    management_factor,
    thermal_wear_factor,
    wear_increment,
)

MEDIUM = TyreCompound("Medium", "M")


def _wear(**overrides) -> float:
    kwargs = dict(
        friction_force=15_000.0,
        distance=100.0,
        surface_temperature=MEDIUM.optimal_temperature,
        tyre_management=0.85,
    )
    kwargs.update(overrides)
    compound = kwargs.pop("compound", MEDIUM)
    return wear_increment(compound, **kwargs)


# -- wear is work ------------------------------------------------------------


def test_wear_is_proportional_to_friction_work():
    base = _wear()
    assert _wear(friction_force=30_000.0) == pytest.approx(2.0 * base)
    assert _wear(distance=200.0) == pytest.approx(2.0 * base)


def test_a_tyre_doing_no_work_does_not_wear():
    assert _wear(friction_force=0.0) == 0.0
    assert _wear(distance=0.0) == 0.0


def test_pushing_wears_more_than_cruising():
    """Not because pushing is flagged as pushing, but because it takes more
    force to go faster round the same corner."""
    assert _wear(friction_force=25_000.0) > _wear(friction_force=18_000.0)


def test_a_softer_compound_wears_faster():
    soft = _wear(compound=TyreCompound("Soft", "S", wear_rate=1.35))
    hard = _wear(compound=TyreCompound("Hard", "H", wear_rate=0.72))
    assert soft > hard


# -- what makes it worse -----------------------------------------------------


def test_working_in_the_window_is_not_overheating():
    """A tyre run inside its window is doing its job, not being abused.

    It wears somewhat faster at the hot edge than at the optimum -- rubber does
    not wear at one flat rate up to a cliff -- but only somewhat.  Charging the
    whole excess from the optimum at the overheating exponent bills a compound
    for being in the range it was built for, and it falls hardest on the softer
    compounds because they naturally run nearest their own hot edge.
    """
    optimal = MEDIUM.optimal_temperature
    window = MEDIUM.temperature_window
    edge = _wear(surface_temperature=optimal + window) / _wear()
    assert 1.0 < edge < 2.0, f"the hot edge of the window costs {edge:.2f}x"


def test_overheating_accelerates_wear_sharply():
    """Superlinear *above the window*, which is what makes cooking a set a
    strategic disaster rather than a small inefficiency."""
    optimal = MEDIUM.optimal_temperature
    window = MEDIUM.temperature_window
    edge = _wear(surface_temperature=optimal + window) / _wear()
    mild = _wear(surface_temperature=optimal + window + 10.0) / _wear()
    severe = _wear(surface_temperature=optimal + window + 20.0) / _wear()
    assert edge < mild < severe
    # The second ten degrees past the window cost more than the first: that is
    # what "superlinear" has to mean for a strategist to care about it.
    assert severe - mild > mild - edge
    # And going over the window is in a different league from working in it.
    assert mild - edge > 2.0 * (edge - 1.0)


def test_a_cold_tyre_wears_at_the_reference_rate():
    assert thermal_wear_factor(MEDIUM, MEDIUM.optimal_temperature - 30.0) == 1.0
    assert thermal_wear_factor(MEDIUM, MEDIUM.optimal_temperature) == 1.0


def test_tyre_management_makes_a_set_last_longer():
    """Rule 25's driver ability, spending itself on the tyre rather than on the
    lap time directly."""
    assert _wear(tyre_management=0.95) < _wear(tyre_management=0.40)
    assert management_factor(1.0) < management_factor(0.0)


# -- what wear does ----------------------------------------------------------


def test_grip_falls_away_progressively():
    """A tyre holds its performance and then goes, rather than fading in a
    straight line -- the cliff a strategist plans around."""
    losses = [1.0 - wear_grip_factor(w) for w in (0.25, 0.5, 0.75, 1.0)]
    assert all(b > a for a, b in zip(losses, losses[1:]))
    increments = [b - a for a, b in zip(losses, losses[1:])]
    assert all(b > a for a, b in zip(increments, increments[1:]))


def test_a_new_tyre_loses_nothing():
    assert wear_grip_factor(0.0) == 1.0


def test_a_worn_out_tyre_still_drives():
    """Rule 39: falling off the cliff must not mean falling out of physics."""
    assert 0.5 < wear_grip_factor(1.0) < 1.0
    assert wear_grip_factor(4.0) == wear_grip_factor(1.0)


# -- permanent damage --------------------------------------------------------


def test_damage_needs_real_overheating():
    inside = thermal_damage_increment(
        MEDIUM.optimal_temperature + 10.0, MEDIUM.optimal_temperature,
        MEDIUM.temperature_window, 1.0,
    )
    outside = thermal_damage_increment(
        MEDIUM.optimal_temperature + 40.0, MEDIUM.optimal_temperature,
        MEDIUM.temperature_window, 1.0,
    )
    assert inside == 0.0
    assert outside > 0.0


def test_damage_does_not_come_back_when_the_tyre_cools():
    """The reason cooking a set early in a stint is expensive for the rest of
    it, and the one tyre effect that a cool-down lap cannot undo."""
    state = TyreState()
    for _ in range(400):
        state.update(
            friction_force=60_000.0, speed=80.0, distance=4.0, dt=0.05,
            air_temperature=45.0, track_temperature=60.0,
        )
    assert state.thermal_damage > 0.0

    # Cool it right down, well back inside its window.
    while state.surface_temperature > state.compound.optimal_temperature:
        state.update(
            friction_force=0.0, speed=60.0, distance=1.0, dt=0.05,
            air_temperature=15.0, track_temperature=20.0,
        )
    damage = state.thermal_damage
    for _ in range(2000):
        state.update(
            friction_force=0.0, speed=60.0, distance=1.0, dt=0.05,
            air_temperature=15.0, track_temperature=20.0,
        )
    assert state.thermal_damage == pytest.approx(damage)
    assert state.grip_multiplier() < 1.0


def test_damage_is_bounded():
    config = TyreWearConfig()
    state = TyreState()
    for _ in range(20_000):
        state.update(
            friction_force=90_000.0, speed=90.0, distance=5.0, dt=0.1,
            air_temperature=50.0, track_temperature=65.0,
        )
    assert state.thermal_damage <= config.max_thermal_damage


# -- the state as a whole ----------------------------------------------------


def test_a_set_wears_out_from_work_alone():
    state = TyreState()
    for _ in range(3000):
        state.update(
            friction_force=20_000.0, speed=60.0, distance=30.0, dt=0.5,
            air_temperature=25.0, track_temperature=35.0,
        )
    assert state.is_worn_out
    assert state.age_laps == 0.0, "wear must not be a lap counter"


def test_the_three_losses_multiply():
    """Temperature, wear and damage are independent and compose."""
    state = TyreState(surface_temperature=70.0, wear=0.5, thermal_damage=0.1)
    state.refresh()
    assert state.grip_multiplier() < wear_grip_factor(0.5)
    assert state.grip_multiplier() == pytest.approx(
        state.grip, abs=0.0
    )
