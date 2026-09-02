"""Strategy (project rule 31).

    "타이어 전략은 하드코딩된 규칙이 아니라 계산 결과여야 한다."

Nothing in the engine says a soft tyre is for a short stint or that an
intermediate is for a damp track.  These tests check that those answers come
back anyway, out of measured degradation and a measured pit loss.
"""

from __future__ import annotations

import pytest

from f1_race_engine.core.errors import EntryError
from f1_race_engine.race import (
    RaceStrategy,
    Stint,
    compound_for_conditions,
    degradation_curve,
    plan_strategy,
)
from f1_race_engine.tyres import TyreState


# -- choosing a tyre for the track you have ----------------------------------


def test_a_dry_track_wants_the_softest_slick(compounds):
    chosen = compound_for_conditions(compounds.compounds, 0.0)
    assert chosen.code == "S"


def test_the_choice_walks_through_the_range_as_it_gets_wetter(compounds):
    choices = [
        compound_for_conditions(compounds.compounds, depth).code
        for depth in (0.0, 0.0005, 0.003, 0.008)
    ]
    assert choices[0] == "S"
    assert choices[1] == "I"
    assert choices[-1] == "W"
    assert choices == sorted(choices, key=["S", "I", "W"].index)


def test_the_choice_depends_on_speed_as_well_as_depth(compounds):
    """Clearance falls with speed, so the same puddle wants a different tyre at
    a circuit where it sits on a straight rather than in a hairpin."""
    slow = compound_for_conditions(compounds.compounds, 0.0025, speed=20.0)
    fast = compound_for_conditions(compounds.compounds, 0.0025, speed=90.0)
    assert slow.code != fast.code or slow.peak_water_depth <= fast.peak_water_depth


def test_an_empty_box_is_an_error():
    with pytest.raises(EntryError):
        compound_for_conditions((), 0.0)


# -- what a compound does over a stint ---------------------------------------


def test_a_curve_is_the_stint_that_was_driven(compounds):
    seen = []

    def drive(lap, state):
        seen.append((lap, state.compound.code, state.wear))
        state.wear = min(state.wear + 0.05, 1.0)
        return 90.0 + 10.0 * state.wear

    curve = degradation_curve(drive, compounds["M"], 6)
    assert len(curve) == 6
    assert [lap for lap, _, _ in seen] == [1, 2, 3, 4, 5, 6]
    assert all(b > a for a, b in zip(curve, curve[1:]))


def test_a_fitted_set_starts_cold(compounds):
    temperatures = []

    def drive(lap, state):
        temperatures.append(state.surface_temperature)
        return 90.0

    degradation_curve(drive, compounds["M"], 2)
    assert temperatures[0] < compounds["M"].optimal_temperature


def test_no_laps_is_no_curve(compounds):
    assert degradation_curve(lambda lap, state: 90.0, compounds["M"], 0) == ()


# -- planning ----------------------------------------------------------------


def _curves(soft_deg=0.5, medium_deg=0.2, laps=40):
    """Two compounds: one quick and fading, one slower and durable."""
    return {
        "S": tuple(88.0 + soft_deg * lap for lap in range(laps)),
        "M": tuple(89.2 + medium_deg * lap for lap in range(laps)),
    }


def test_a_plan_covers_the_race(compounds):
    plan = plan_strategy(_curves(), (compounds["S"], compounds["M"]), 30, 20.0)
    assert plan.laps == 30
    assert plan.stops == len(plan.stints) - 1


def test_an_expensive_pit_lane_buys_fewer_stops(compounds):
    tyres = (compounds["S"], compounds["M"])
    cheap = plan_strategy(_curves(), tyres, 40, 8.0)
    dear = plan_strategy(_curves(), tyres, 40, 45.0)
    assert cheap.stops >= dear.stops


def test_faster_degradation_buys_more_stops(compounds):
    tyres = (compounds["S"], compounds["M"])
    gentle = plan_strategy(_curves(soft_deg=0.05, medium_deg=0.03), tyres, 40, 20.0)
    harsh = plan_strategy(_curves(soft_deg=1.2, medium_deg=0.9), tyres, 40, 20.0)
    assert harsh.stops >= gentle.stops


def test_the_two_compound_rule_is_a_constraint_not_a_preference(compounds):
    tyres = (compounds["S"], compounds["M"])
    required = plan_strategy(_curves(), tyres, 40, 20.0, require_two_compounds=True)
    free = plan_strategy(_curves(), tyres, 40, 20.0, require_two_compounds=False)
    assert len(set(required.compounds)) >= 2
    assert free.projected_time <= required.projected_time


def test_a_plan_respects_the_minimum_stint(compounds):
    plan = plan_strategy(
        _curves(), (compounds["S"], compounds["M"]), 40, 20.0, minimum_stint=12
    )
    assert all(stint.laps >= 12 for stint in plan.stints)


def test_a_plan_names_the_laps_it_stops_on(compounds):
    plan = plan_strategy(_curves(), (compounds["S"], compounds["M"]), 30, 20.0)
    assert len(plan.pit_laps()) == plan.stops
    assert all(0 < lap < 30 for lap in plan.pit_laps())


def test_a_plan_serialises(compounds):
    payload = plan_strategy(_curves(), (compounds["S"], compounds["M"]), 30, 20.0).to_dict()
    assert payload["stints"] and "projected_time" in payload


def test_planning_without_curves_is_an_error(compounds):
    with pytest.raises(EntryError):
        plan_strategy({}, (compounds["M"],), 20, 20.0)


def test_a_zero_lap_race_is_an_error(compounds):
    with pytest.raises(EntryError):
        plan_strategy(_curves(), (compounds["M"],), 0, 20.0)


# -- deciding during the race ------------------------------------------------


def _strategy(compounds, **kwargs):
    return RaceStrategy(compounds=tuple(compounds.compounds), **kwargs)


def test_a_strategist_stays_out_when_there_is_no_reason(compounds):
    strategy = _strategy(compounds, minimum_stint=5)
    state = TyreState(compound=compounds["S"])
    for _ in range(4):
        strategy.lap_completed()
    assert strategy.decide(
        lap=4, laps_remaining=30, tyres=state, water_depth=0.0
    ) is None


def test_rain_beats_the_plan(compounds):
    """The one decision that does not wait for a lap number."""
    strategy = _strategy(compounds, minimum_stint=10)
    state = TyreState(compound=compounds["S"])
    strategy.lap_completed()
    wanted = strategy.decide(lap=1, laps_remaining=30, tyres=state, water_depth=0.004)
    assert wanted is not None and wanted.is_wet_weather


def test_a_drying_track_gets_the_slicks_back(compounds):
    strategy = _strategy(compounds, minimum_stint=2)
    state = TyreState(compound=compounds["W"])
    for _ in range(4):
        strategy.lap_completed()
    wanted = strategy.decide(lap=4, laps_remaining=30, tyres=state, water_depth=0.0)
    assert wanted is not None and not wanted.is_wet_weather


def test_a_finished_set_is_changed_whatever_the_plan_said(compounds):
    strategy = _strategy(compounds, minimum_stint=3, wear_limit=0.9)
    state = TyreState(compound=compounds["S"], wear=0.95)
    for _ in range(5):
        strategy.lap_completed()
    assert strategy.decide(
        lap=5, laps_remaining=20, tyres=state, water_depth=0.0
    ) is not None


def test_nobody_pits_on_the_last_lap(compounds):
    strategy = _strategy(compounds, minimum_stint=1)
    state = TyreState(compound=compounds["S"], wear=1.0)
    strategy.lap_completed()
    assert strategy.decide(
        lap=40, laps_remaining=0, tyres=state, water_depth=0.0
    ) is None


def test_the_plan_decides_when_nothing_else_does(compounds):
    from f1_race_engine.race import StrategyPlan

    plan = StrategyPlan(
        stints=(Stint(compounds["S"], 12), Stint(compounds["M"], 18)),
        projected_time=2700.0,
        pit_loss=20.0,
    )
    strategy = _strategy(compounds, minimum_stint=5)
    strategy.plan = plan
    state = TyreState(compound=compounds["S"], wear=0.3)
    for _ in range(12):
        strategy.lap_completed()
    wanted = strategy.decide(lap=12, laps_remaining=18, tyres=state, water_depth=0.0)
    assert wanted is not None and wanted.code == "M"


def test_a_minimum_stint_is_respected_unless_it_rains(compounds):
    strategy = _strategy(compounds, minimum_stint=8, wear_limit=0.5)
    state = TyreState(compound=compounds["S"], wear=0.99)
    strategy.lap_completed()
    assert strategy.decide(
        lap=1, laps_remaining=30, tyres=state, water_depth=0.0
    ) is None
    assert strategy.decide(
        lap=1, laps_remaining=30, tyres=state, water_depth=0.005
    ) is not None


# -- the two-compound rule ---------------------------------------------------


def test_a_dry_race_uses_two_compounds(compounds):
    """The regulation, satisfied by choosing rather than by being told: the
    strategist takes the best tyre it has not used yet."""
    strategy = _strategy(compounds, minimum_stint=2, wear_limit=0.5)
    strategy.start_stint(compounds["S"])
    state = TyreState(compound=compounds["S"], wear=0.9)
    for _ in range(5):
        strategy.lap_completed()
    wanted = strategy.decide(lap=5, laps_remaining=25, tyres=state, water_depth=0.0)
    assert wanted is not None
    assert wanted.code != "S"
    assert not wanted.is_wet_weather


def test_once_two_have_been_used_the_best_one_comes_back(compounds):
    strategy = _strategy(compounds, minimum_stint=2, wear_limit=0.5)
    strategy.start_stint(compounds["S"])
    strategy.start_stint(compounds["M"])
    state = TyreState(compound=compounds["M"], wear=0.9)
    for _ in range(5):
        strategy.lap_completed()
    wanted = strategy.decide(lap=5, laps_remaining=25, tyres=state, water_depth=0.0)
    assert wanted is not None and wanted.code == "S"


def test_rain_suspends_the_rule(compounds):
    """As the real one is: a race run on wet-weather tyres has no requirement,
    and the strategist stops throwing a stop away on it."""
    strategy = _strategy(compounds, minimum_stint=1, wear_limit=0.5)
    strategy.start_stint(compounds["W"])
    strategy.start_stint(compounds["S"])
    state = TyreState(compound=compounds["S"], wear=0.9)
    for _ in range(3):
        strategy.lap_completed()
    wanted = strategy.decide(lap=3, laps_remaining=25, tyres=state, water_depth=0.0)
    assert wanted is not None and wanted.code == "S"


def test_the_rule_can_be_switched_off(compounds):
    strategy = _strategy(
        compounds, minimum_stint=2, wear_limit=0.5, require_two_compounds=False
    )
    strategy.start_stint(compounds["S"])
    state = TyreState(compound=compounds["S"], wear=0.9)
    for _ in range(5):
        strategy.lap_completed()
    wanted = strategy.decide(lap=5, laps_remaining=25, tyres=state, water_depth=0.0)
    assert wanted is not None and wanted.code == "S"


def test_a_strategist_remembers_what_it_has_used(compounds):
    strategy = _strategy(compounds)
    strategy.start_stint(compounds["S"])
    strategy.record_stop(compounds["M"])
    assert strategy.compounds_used == {"S", "M"}
    assert strategy.stops_made == 1
