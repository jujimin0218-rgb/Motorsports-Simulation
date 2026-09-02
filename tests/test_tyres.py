"""Tyre compounds and the grip model."""

from __future__ import annotations

import pytest

from f1_race_engine.core.errors import ConfigError
from f1_race_engine.tyres import CompoundSet, GripLimit, TyreCompound, TyreModel, TyreState
from f1_race_engine.tyres.compound import CompoundFamily
from f1_race_engine.tyres.io import builtin_compound_sets, load_builtin_compounds


# -- load sensitivity --------------------------------------------------------


def test_friction_coefficient_falls_with_load():
    """The single most important tyre behaviour: grip is not proportional to
    load.  Without it, downforce would buy cornering ability linearly."""
    compound = TyreCompound("Medium", "M")
    loads = (2000.0, 4000.0, 8000.0, 16000.0, 32000.0)
    coefficients = [compound.friction_coefficient(load) for load in loads]
    assert all(b < a for a, b in zip(coefficients, coefficients[1:]))


def test_total_grip_force_still_rises_with_load():
    """Falling coefficient must not mean falling force -- that would be absurd."""
    compound = TyreCompound("Medium", "M")
    loads = (2000.0, 4000.0, 8000.0, 16000.0, 32000.0)
    forces = [compound.friction_coefficient(load) * load for load in loads]
    assert all(b > a for a, b in zip(forces, forces[1:]))


def test_peak_friction_applies_at_the_reference_load():
    compound = TyreCompound("Medium", "M", peak_friction=1.68, reference_load=8000.0)
    assert compound.friction_coefficient(8000.0) == pytest.approx(1.68)


def test_zero_load_sensitivity_is_coulomb_friction():
    compound = TyreCompound("Ideal", "X", load_sensitivity=0.0)
    assert compound.friction_coefficient(1.0) == compound.peak_friction
    assert compound.friction_coefficient(1e6) == compound.peak_friction


def test_zero_load_does_not_diverge():
    compound = TyreCompound("Medium", "M")
    assert compound.friction_coefficient(0.0) == compound.peak_friction
    assert compound.friction_coefficient(-5.0) == compound.peak_friction


# -- the friction ellipse ----------------------------------------------------


def test_friction_ellipse_trades_lateral_for_longitudinal():
    limit = GripLimit(normal_load=8000.0, friction_coefficient=1.0, capacity=1000.0)
    assert limit.available_lateral(0.0) == pytest.approx(1000.0)
    assert limit.available_lateral(1000.0) == pytest.approx(0.0)
    # The 3-4-5 triangle: 600 longitudinal leaves 800 lateral.
    assert limit.available_lateral(600.0) == pytest.approx(800.0)
    assert limit.available_longitudinal(800.0) == pytest.approx(600.0)


def test_friction_ellipse_is_monotone():
    limit = GripLimit(8000.0, 1.0, 1000.0)
    values = [limit.available_lateral(x) for x in (0.0, 200.0, 500.0, 800.0, 1000.0)]
    assert all(b < a for a, b in zip(values, values[1:]))


def test_utilisation_reaches_one_at_the_limit():
    limit = GripLimit(8000.0, 1.0, 1000.0)
    assert limit.utilisation(600.0, 800.0) == pytest.approx(1.0)
    assert limit.utilisation(0.0, 0.0) == pytest.approx(0.0)
    assert limit.utilisation(1000.0, 1000.0) > 1.0


def test_over_saturated_input_is_clamped_not_imaginary():
    limit = GripLimit(8000.0, 1.0, 1000.0)
    assert limit.available_lateral(5000.0) == 0.0


def test_zero_capacity_offers_nothing():
    limit = GripLimit(0.0, 1.0, 0.0)
    assert limit.available_lateral(0.0) == 0.0


# -- the model ---------------------------------------------------------------


def test_surface_grip_scales_the_coefficient():
    model = TyreModel()
    compound = TyreCompound("Medium", "M")
    full = model.friction_coefficient(compound, 8000.0)
    reduced = model.friction_coefficient(compound, 8000.0, surface_grip=0.9)
    assert reduced == pytest.approx(full * 0.9)


def test_grip_limit_capacity_is_coefficient_times_load():
    model = TyreModel()
    limit = model.grip_limit(TyreCompound("Medium", "M"), 12000.0)
    assert limit.capacity == pytest.approx(limit.friction_coefficient * 12000.0)


def test_rolling_resistance_is_proportional_to_load():
    model = TyreModel()
    compound = TyreCompound("Medium", "M", rolling_resistance=0.012)
    assert model.rolling_resistance_force(compound, 10_000.0) == pytest.approx(120.0)
    assert model.rolling_resistance_force(compound, -5.0) == 0.0


# -- state -------------------------------------------------------------------


def test_a_fresh_tyre_in_its_window_is_neutral():
    """Phase 2 promised the physics would keep reading one number from the
    tyre and that Phase 5 would fill it in.  A new set at its working
    temperature still answers 1.0 -- the compound alone decides."""
    assert TyreState().grip_multiplier() == 1.0


def test_fitting_a_fresh_set_resets_age():
    state = TyreState()
    state.age_laps = 12.0
    state.age_distance = 60_000.0
    state.wear = 0.6
    state.fit(TyreCompound("Soft", "S"))
    assert state.compound.code == "S"
    assert state.age_laps == 0.0 and state.age_distance == 0.0 and state.wear == 0.0


def test_state_snapshot_is_plain_data():
    payload = TyreState().snapshot()
    assert payload["compound"] == "M"
    assert isinstance(payload["wear"], float)


# -- compound sets and data --------------------------------------------------


def test_shipped_compound_set_loads():
    assert builtin_compound_sets() == ["reference_2024"]
    compounds = load_builtin_compounds()
    assert {c.code for c in compounds} == {"S", "M", "H", "I", "W"}


def test_softer_compounds_grip_more(compounds):
    soft, medium, hard = compounds["S"], compounds["M"], compounds["H"]
    assert soft.peak_friction > medium.peak_friction > hard.peak_friction


def test_softer_compounds_wear_faster(compounds):
    assert compounds["S"].wear_rate > compounds["M"].wear_rate > compounds["H"].wear_rate


def test_wet_compounds_grip_less_but_clear_water(compounds):
    for code in ("I", "W"):
        assert compounds[code].peak_friction < compounds["H"].peak_friction
        assert compounds[code].peak_water_depth > 0.0
        assert compounds[code].is_wet_weather
    assert not compounds["M"].is_wet_weather
    assert compounds["W"].peak_water_depth > compounds["I"].peak_water_depth


def test_compound_set_lookup_is_case_insensitive(compounds):
    assert compounds["s"] is compounds["S"]
    assert "M" in compounds
    with pytest.raises(KeyError, match="available"):
        compounds["Z"]


def test_compound_set_partitions_slicks_and_wets(compounds):
    assert len(compounds.slicks) == 3
    assert len(compounds.wets) == 2


def test_compound_round_trip(compounds):
    assert CompoundSet.from_dict(compounds.to_dict()).to_dict() == compounds.to_dict()


def test_duplicate_codes_are_rejected():
    with pytest.raises(ConfigError):
        CompoundSet([TyreCompound("A", "S"), TyreCompound("B", "S")])


def test_empty_compound_set_is_rejected():
    with pytest.raises(ConfigError):
        CompoundSet([])


@pytest.mark.parametrize(
    "kwargs",
    [
        {"peak_friction": 0.0},
        {"reference_load": -1.0},
        {"load_sensitivity": 1.5},
        {"load_sensitivity": -0.1},
        {"rolling_resistance": -0.01},
        {"temperature_window": 0.0},
    ],
)
def test_impossible_compounds_are_rejected(kwargs):
    with pytest.raises(ConfigError):
        TyreCompound("Bad", "B", **kwargs)


def test_unknown_compound_key_is_rejected():
    with pytest.raises(ConfigError, match="unknown"):
        TyreCompound.from_dict({"name": "X", "code": "X", "grippiness": 2.0})
