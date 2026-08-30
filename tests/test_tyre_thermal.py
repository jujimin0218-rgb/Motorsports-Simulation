"""Tyre temperature (project rule 21).

Warm-up and overheating are not two switches -- they are the two ends of one
heat balance, and these tests pin down that the balance behaves.
"""

from __future__ import annotations

import pytest

from f1_race_engine.core.config import TyreThermalConfig
from f1_race_engine.tyres import TyreCompound, TyreState
from f1_race_engine.tyres.temperature import thermal_grip_factor, update_temperatures


def _step(**overrides):
    kwargs = dict(
        surface_temperature=80.0,
        carcass_temperature=70.0,
        friction_force=12_000.0,
        speed=60.0,
        air_temperature=25.0,
        track_temperature=35.0,
        dt=0.05,
    )
    kwargs.update(overrides)
    return update_temperatures(**kwargs)


# -- heat in -----------------------------------------------------------------


def test_working_the_tyre_heats_it():
    assert _step(friction_force=30_000.0).surface_temperature > 80.0


def test_a_coasting_tyre_cools():
    """No friction, no heat: the tread falls back towards the air and track."""
    assert _step(friction_force=0.0).surface_temperature < 80.0


def test_heat_is_proportional_to_friction_work():
    """The heat that enters the tread is work, so doubling either the force or
    the speed doubles it.  Nothing here counts laps or corners."""
    single = _step(friction_force=10_000.0, speed=50.0).heat_in
    force = _step(friction_force=20_000.0, speed=50.0).heat_in
    speed = _step(friction_force=10_000.0, speed=100.0).heat_in
    assert force == pytest.approx(2.0 * single)
    assert speed == pytest.approx(2.0 * single)


def test_a_softer_compound_heats_faster():
    """Rule 21's compound character, from hysteresis rather than a table."""
    soft = _step(hysteresis=1.35**0.5).surface_temperature
    hard = _step(hysteresis=0.72**0.5).surface_temperature
    assert soft > hard


# -- heat out ----------------------------------------------------------------


def test_speed_cools_the_tread():
    """Which is why a car stuck in slow corners struggles to keep temperature
    down and one on a long straight struggles to keep it up."""
    fast = _step(surface_temperature=120.0, friction_force=0.0, speed=90.0)
    slow = _step(surface_temperature=120.0, friction_force=0.0, speed=10.0)
    assert fast.surface_temperature < slow.surface_temperature


def test_a_hotter_track_keeps_the_tyre_hotter():
    hot = _step(friction_force=0.0, track_temperature=50.0).surface_temperature
    cold = _step(friction_force=0.0, track_temperature=15.0).surface_temperature
    assert hot > cold


def test_the_carcass_lags_the_surface():
    """Two masses, not one: the tread responds in seconds and the carcass in
    laps, which is the whole reason for modelling them separately."""
    step = _step(friction_force=40_000.0, dt=1.0)
    surface_change = step.surface_temperature - 80.0
    carcass_change = step.carcass_temperature - 70.0
    assert surface_change > 0.0
    assert 0.0 < carcass_change < surface_change


def test_a_hot_surface_warms_the_carcass_through():
    """Given long enough the carcass catches up -- that is warm-up finishing."""
    surface, carcass = 110.0, 60.0
    for _ in range(4000):
        step = update_temperatures(
            surface_temperature=surface, carcass_temperature=carcass,
            friction_force=14_000.0, speed=55.0,
            air_temperature=25.0, track_temperature=35.0, dt=0.05,
        )
        surface, carcass = step.surface_temperature, step.carcass_temperature
    assert carcass > 80.0
    assert abs(surface - carcass) < 30.0


def test_temperature_settles_rather_than_running_away():
    """Rule 39: a system that cannot reach equilibrium is wrong, not exciting."""
    surface, carcass = 80.0, 70.0
    history = []
    for _ in range(30_000):
        step = update_temperatures(
            surface_temperature=surface, carcass_temperature=carcass,
            friction_force=16_000.0, speed=60.0,
            air_temperature=25.0, track_temperature=35.0, dt=0.02,
        )
        surface, carcass = step.surface_temperature, step.carcass_temperature
        history.append(surface)
    assert abs(history[-1] - history[-2]) < 1e-3
    assert 40.0 < history[-1] < 200.0


def test_a_pathological_step_cannot_explode():
    """The clamp exists so a bad ``dt`` degrades the answer instead of the run."""
    step = _step(friction_force=1e7, dt=1000.0)
    assert step.surface_temperature <= 260.0


# -- what temperature does to grip -------------------------------------------


def test_grip_peaks_at_the_optimum():
    compound = TyreCompound("Medium", "M")
    peak = thermal_grip_factor(compound, compound.optimal_temperature)
    assert peak == pytest.approx(1.0)
    for offset in (-30.0, -10.0, 10.0, 30.0):
        assert thermal_grip_factor(compound, compound.optimal_temperature + offset) < peak


def test_the_well_is_symmetric():
    compound = TyreCompound("Medium", "M")
    cold = thermal_grip_factor(compound, compound.optimal_temperature - 20.0)
    hot = thermal_grip_factor(compound, compound.optimal_temperature + 20.0)
    assert cold == pytest.approx(hot)


def test_a_wider_window_is_more_forgiving():
    """The property that makes a hard tyre easier to drive."""
    narrow = TyreCompound("Narrow", "N", temperature_window=15.0)
    wide = TyreCompound("Wide", "W", temperature_window=35.0)
    offset = narrow.optimal_temperature + 15.0
    assert thermal_grip_factor(wide, offset) > thermal_grip_factor(narrow, offset)


def test_a_stone_cold_tyre_still_has_some_grip():
    compound = TyreCompound("Medium", "M")
    floor = TyreThermalConfig().min_thermal_grip
    assert thermal_grip_factor(compound, -10.0) == pytest.approx(floor)


# -- the state ---------------------------------------------------------------


def test_a_new_state_starts_in_its_window():
    state = TyreState(compound=TyreCompound("Soft", "S", optimal_temperature=105.0))
    assert state.surface_temperature == pytest.approx(105.0)
    assert state.in_working_window


def test_a_fitted_set_starts_below_its_window():
    """Out of the blankets, not up to temperature: the reason an out-lap is
    slow and the reason warm-up is worth simulating at all."""
    state = TyreState()
    state.fit(TyreCompound("Medium", "M"))
    assert state.surface_temperature < state.compound.optimal_temperature
    assert state.grip_multiplier() < 1.0


def test_driving_warms_a_cold_set_into_its_window():
    state = TyreState()
    state.fit(TyreCompound("Medium", "M"))
    cold = state.grip_multiplier()
    for _ in range(2000):
        state.update(
            friction_force=15_000.0, speed=60.0, distance=3.0, dt=0.05,
            air_temperature=25.0, track_temperature=35.0,
        )
    assert state.surface_temperature > cold
    assert state.grip_multiplier() > cold
    assert state.in_working_window


def test_the_peak_temperature_is_remembered():
    state = TyreState()
    for force in (30_000.0, 0.0, 0.0, 0.0):
        state.update(
            friction_force=force, speed=70.0, distance=3.0, dt=0.5,
            air_temperature=25.0, track_temperature=35.0,
        )
    assert state.peak_surface_temperature > state.surface_temperature
