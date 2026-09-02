"""Research, and the property the whole season rests on.

Progress is **concave**: in the points spent, and in where the car already is.
Both together are what stops round three from deciding the championship, and
they are one number in ``rules.json`` rather than a special case anywhere.
"""

from __future__ import annotations

import pytest

from app.game.car import AREA_NAMES
from app.game.development import (
    COST_PER_POINT,
    UpgradeStatus,
    commission,
    development_gain,
    research_earned,
    resolve,
)
from app.game.errors import InsufficientBudget, UnknownEntity
from app.game.rules import Rules


@pytest.fixture
def rules():
    return Rules.load().development


# -- the curve ---------------------------------------------------------------


def test_the_tenth_upgrade_is_worth_less_than_the_first(game, rules):
    """Concave in the points spent: a team that pours everything into one box
    beats nobody."""
    team = game.player
    per_point = [
        development_gain(team, "aero", points, rules) / points
        for points in (50, 100, 200, 400, 800)
    ]
    assert per_point == sorted(per_point, reverse=True)
    assert per_point[-1] < 0.5 * per_point[0]


def test_a_car_near_the_ceiling_is_harder_to_improve(game, rules):
    """Concave in where the car already is, which is what makes a field
    converge rather than diverge."""
    team = game.player
    gains = []
    for level in (0.70, 0.85, 0.95):
        team.car.set_area("aero", level)
        gains.append(development_gain(team, "aero", 200, rules))
    assert gains == sorted(gains, reverse=True)


def test_a_season_closes_the_field_without_levelling_it(game, rules):
    """The balance the whole game rests on.  A backmarker gains more than a
    leader, so an early advantage does not decide the year -- but the leader is
    still the leader at the end, so it is not a reset either."""
    start = {t.id: t.car.overall for t in game.teams.values()}
    for _ in range(len(game.calendar)):
        for team in game.teams.values():
            share = research_earned(team, rules) / len(AREA_NAMES)
            for area in AREA_NAMES:
                team.car.improve(area, development_gain(team, area, share, rules))

    ordered = sorted(game.teams.values(), key=lambda t: -start[t.id])
    leader, backmarker = ordered[0], ordered[-1]
    assert (backmarker.car.overall - start[backmarker.id]) > (
        leader.car.overall - start[leader.id]
    )
    before = start[leader.id] - start[backmarker.id]
    after = leader.car.overall - backmarker.car.overall
    assert 0.05 < (1.0 - after / before) < 0.55, "the field should close, not level"
    assert leader.car.overall > backmarker.car.overall


def test_a_better_facility_develops_faster(game, rules):
    strong, weak = game.team("argent"), game.team("harrow")
    strong.car.set_area("aero", 0.80)
    weak.car.set_area("aero", 0.80)
    assert development_gain(strong, "aero", 200, rules) > development_gain(
        weak, "aero", 200, rules
    )


def test_research_earned_rewards_the_factory_and_the_head_count(game, rules):
    assert research_earned(game.team("argent"), rules) > research_earned(
        game.team("harrow"), rules
    )


# -- commissioning -----------------------------------------------------------


def test_a_project_takes_research_and_money_and_time(game, rules):
    team = game.player
    team.rd_points = 400.0
    budget = team.budget

    upgrade = commission(
        team, area="aero", points=300.0, current_round=3, rules=rules, upgrade_id="u1"
    )
    assert team.rd_points == pytest.approx(100.0)
    assert team.budget == pytest.approx(budget - 300.0 * COST_PER_POINT)
    assert upgrade.arrives_at_round > 3
    assert upgrade.in_development
    assert upgrade.expected_gain > 0.0


def test_you_cannot_commission_research_you_have_not_done(game, rules):
    game.player.rd_points = 50.0
    with pytest.raises(InsufficientBudget):
        commission(
            game.player, area="aero", points=300.0, current_round=1, rules=rules,
            upgrade_id="u1",
        )


def test_the_cost_cap_refuses_even_when_the_bank_does_not(game, rules):
    """Money and allowance are two different things to run out of, and that is
    the point of a cap."""
    team = game.player
    team.budget = 1000.0
    team.rd_points = 10_000.0
    team.season_spending = game.rules.budget.cap - 1.0
    with pytest.raises(InsufficientBudget, match="cost-cap"):
        commission(
            team, area="aero", points=500.0, current_round=1, rules=rules,
            upgrade_id="u1", cap=game.rules.budget.cap,
        )


def test_rushing_costs_money_and_reliability_of_development(game, rules):
    team = game.player
    team.rd_points = 2000.0
    steady = commission(
        team, area="aero", points=400.0, current_round=1, rules=rules,
        rushed=0.0, upgrade_id="a",
    )
    rushed = commission(
        team, area="aero", points=400.0, current_round=1, rules=rules,
        rushed=1.0, upgrade_id="b",
    )
    assert rushed.cost > steady.cost
    assert rushed.failure_chance > steady.failure_chance
    assert rushed.arrives_at_round <= steady.arrives_at_round


def test_an_unknown_area_is_refused(game, rules):
    game.player.rd_points = 500.0
    with pytest.raises(UnknownEntity):
        commission(
            game.player, area="engine_mode", points=100.0, current_round=1,
            rules=rules, upgrade_id="u1",
        )


# -- fitting -----------------------------------------------------------------


def test_a_part_that_works_goes_on_the_car(game, rules):
    team = game.player
    team.rd_points = 500.0
    before = team.car.aero
    upgrade = commission(
        team, area="aero", points=400.0, current_round=1, rules=rules, upgrade_id="u1"
    )
    upgrade.failure_chance = 0.0
    resolve(upgrade, team, game.round_rng(1).stream("t"))
    assert upgrade.status == UpgradeStatus.FITTED
    assert team.car.aero > before
    assert upgrade.actual_gain > 0.0


def test_a_project_that_fails_is_not_a_refund(game, rules):
    """The research and the money went either way, which is what makes
    commissioning one a decision rather than a formality."""
    team = game.player
    team.rd_points = 500.0
    before_car, before_budget = team.car.aero, team.budget
    upgrade = commission(
        team, area="aero", points=400.0, current_round=1, rules=rules, upgrade_id="u1"
    )
    upgrade.failure_chance = 1.0
    resolve(upgrade, team, game.round_rng(1).stream("t"))
    assert upgrade.status == UpgradeStatus.FAILED
    assert team.car.aero == pytest.approx(before_car)
    assert team.budget < before_budget
    assert team.rd_points == pytest.approx(100.0)


def test_a_new_part_is_fragile_and_stops_being_so(game, rules):
    """Which is why bringing an upgrade to a title decider is a real question
    rather than a gift."""
    team = game.player
    team.rd_points = 500.0
    upgrade = commission(
        team, area="aero", points=400.0, current_round=1, rules=rules, upgrade_id="u1"
    )
    upgrade.failure_chance = 0.0
    resolve(upgrade, team, game.round_rng(1).stream("t"))

    arrival = upgrade.arrives_at_round
    fresh = upgrade.fragility_at(arrival)
    later = upgrade.fragility_at(arrival + 2)
    assert fresh > later > 0.0
    assert upgrade.fragility_at(arrival + 10) == 0.0


def test_the_game_knows_how_fragile_a_whole_car_is(game, rules):
    team = game.player
    team.rd_points = 2000.0
    for index in range(3):
        upgrade = commission(
            team, area="aero", points=300.0, current_round=1, rules=rules,
            upgrade_id=f"u{index}",
        )
        upgrade.failure_chance = 0.0
        upgrade.arrives_at_round = 2
        resolve(upgrade, team, game.round_rng(1).stream(f"t{index}"))
        game.upgrades.append(upgrade)
    assert game.fragility_for(team.id, 2) > game.fragility_for(team.id, 3) > 0.0


# -- the sliding scale, which is what actually closes the field --------------


def test_the_team_at_the_back_is_allowed_more_development(game, rules):
    """Concavity alone was not enough, and the measurement said so: run whole
    seasons with the shipped grid and the field barely closed, because a big
    team earns far more research from its factory and head count than a small
    one.  So the game uses the sport's own answer to that -- the team leading
    the championship gets the least allowance and the team at the back the
    most."""
    from app.game.development import development_allowance

    allowances = [development_allowance(position) for position in range(1, 11)]
    assert allowances == sorted(allowances)
    assert allowances[0] < 1.0 < allowances[-1]


def test_position_changes_what_a_round_of_work_is_worth(game, rules):
    team = game.team("argent")
    leading = research_earned(team, rules, position=1)
    trailing = research_earned(team, rules, position=10)
    assert trailing > leading


def test_the_scale_narrows_the_factory_advantage_without_reversing_it(game, rules):
    """A correction, not a punishment -- and this is what the real regulation
    does too.  A big team leading the championship still out-develops a small
    team at the back; it just does so by much less, which is why a season
    closes the field by a few per cent rather than levelling it in one go.
    """
    big, small = game.team("argent"), game.team("harrow")

    unscaled = research_earned(big, rules) / research_earned(small, rules)
    scaled = research_earned(big, rules, position=1) / research_earned(
        small, rules, position=10
    )
    assert unscaled > scaled > 1.0, "narrowed, but the factory still counts"
    assert scaled < 0.75 * unscaled, "and narrowed by a lot"
