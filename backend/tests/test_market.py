"""Contracts, sponsors and money -- the three things that can say no."""

from __future__ import annotations

import pytest

from app.game.contracts import Offer, evaluate, market_asking_price, sign
from app.game.errors import (
    ContractNotAvailable,
    InsufficientBudget,
    InvalidDriver,
)
from app.game.finance import (
    Ledger,
    LedgerLine,
    SponsorDeal,
    load_sponsors,
    round_costs,
    season_settlement,
)
from app.game.standings import RaceOutcome, Standings


# -- the transfer market -----------------------------------------------------


def test_a_driver_charges_a_slow_team_more(game):
    """The mechanism that stops a backmarker buying its way to the front
    cheaply, and what happens in reality."""
    star = max(game.drivers.values(), key=lambda d: d.overall)
    quick = market_asking_price(star, game.team("argent"))
    slow = market_asking_price(star, game.team("harrow"))
    assert slow > quick


def test_the_car_matters_more_than_the_money(game):
    """A driver wants to win.  Without this the richest team simply buys the
    best driver every year and the rest of the grid is scenery."""
    star = max(game.drivers.values(), key=lambda d: d.overall)
    backmarker = game.team("harrow")
    asking = market_asking_price(star, backmarker)

    fair = evaluate(
        Offer(backmarker.id, star.id, salary=asking, seasons=2), star, backmarker
    )
    assert not fair.accepted
    assert fair.reason == "not convinced by the car"

    # The same driver takes the same money from a quick team without blinking.
    top = game.team("argent")
    at_top = evaluate(
        Offer(top.id, star.id, salary=market_asking_price(star, top), seasons=2),
        star,
        top,
    )
    assert at_top.accepted


def test_a_lowball_is_refused_and_says_what_it_would_take(game):
    driver = game.free_agents[0]
    team = game.team("meridian")
    asking = market_asking_price(driver, team)
    result = evaluate(Offer(team.id, driver.id, salary=asking * 0.2), driver, team)
    assert not result.accepted
    assert result.asking_price == pytest.approx(asking)
    assert "wants about" in result.reason


def test_signing_puts_the_driver_in_the_car_and_charges_the_bonus(game):
    driver = game.free_agents[0]
    team = game.team("meridian")
    budget = team.budget
    offer = Offer(team.id, driver.id, salary=8.0, seasons=2, signing_bonus=3.0)
    sign(offer, driver, team)

    assert driver.team == team.id
    assert driver.id in team.drivers
    assert driver.contract is not None
    assert driver.contract.seasons_remaining == 2
    assert team.budget == pytest.approx(budget - 3.0)


def test_a_driver_under_contract_elsewhere_cannot_simply_be_signed(game):
    taken = next(d for d in game.drivers.values() if d.team == "argent")
    team = game.team("harrow")
    with pytest.raises(ContractNotAvailable):
        sign(Offer(team.id, taken.id, salary=50.0), taken, team)


def test_a_retired_driver_is_not_in_the_market(game):
    driver = game.free_agents[0]
    driver.retired = True
    with pytest.raises(InvalidDriver):
        evaluate(Offer("harrow", driver.id, salary=10.0), driver, game.team("harrow"))


def test_a_signing_bonus_that_cannot_be_paid_is_refused(game):
    driver = game.free_agents[0]
    team = game.team("harrow")
    team.budget = 1.0
    with pytest.raises(InsufficientBudget):
        sign(Offer(team.id, driver.id, salary=5.0, signing_bonus=40.0), driver, team)


# -- sponsors ----------------------------------------------------------------


def test_the_big_money_will_not_go_on_a_car_nobody_is_watching(game):
    """Which is what makes reputation worth building rather than a number on
    a screen."""
    sponsors = load_sponsors()
    biggest = max(sponsors.values(), key=lambda s: s.base_payment)
    assert not biggest.available_to(game.team("harrow").reputation)
    assert biggest.available_to(game.team("argent").reputation)


def test_a_sponsor_pays_out_on_its_target_and_charges_for_a_miss(game):
    sponsors = load_sponsors()
    sponsor = next(
        s for s in sponsors.values()
        if s.target_kind == "constructors_position" and s.penalty > 0
    )
    game.sponsor_deals.append(
        SponsorDeal(sponsor.id, "harrow", sponsor.seasons, game.season)
    )

    from dataclasses import replace

    hit = Standings.compute(
        [RaceOutcome(1, d, "harrow", 1) for d in game.team("harrow").drivers],
        game.rules,
        team_ids=["harrow"],
    )
    ledger = season_settlement(game, "harrow", hit, game.rules)
    assert any("bonus" in line.label for line in ledger.lines)

    # Everybody else actually scores, so finishing eighteenth puts the team
    # where finishing eighteenth should put it.
    others = [
        RaceOutcome(1, f"d{i}", f"other{i}", position)
        for i, position in enumerate(range(1, 13))
    ]
    missed = Standings.compute(
        others + [RaceOutcome(1, d, "harrow", 18) for d in game.team("harrow").drivers],
        game.rules,
    )
    ledger = season_settlement(game, "harrow", missed, game.rules)
    assert any("shortfall" in line.label for line in ledger.lines)


# -- money -------------------------------------------------------------------


def test_a_round_costs_what_the_team_actually_has(game):
    """Every line is a thing the team agreed to, not a tax pulled out of the
    air."""
    ledger = round_costs(game, "harrow", round_number=1)
    labels = " ".join(line.label for line in ledger.lines)
    assert "salary" in labels
    assert "operations" in labels
    assert "staff" in labels
    assert ledger.total < 0.0, "a round with no sponsors costs money"


def test_a_works_team_has_no_engine_line_and_a_customer_does(game):
    works = " ".join(
        line.label for line in round_costs(game, "argent", round_number=1).lines
    )
    customer = " ".join(
        line.label for line in round_costs(game, "aurora", round_number=1).lines
    )
    assert "supply" not in works
    assert "supply" in customer


def test_sponsorship_arrives_spread_across_the_season(game):
    sponsors = load_sponsors()
    affordable = next(
        s for s in sponsors.values()
        if s.available_to(game.team("harrow").reputation)
    )
    before = round_costs(game, "harrow", round_number=1).total
    game.sponsor_deals.append(
        SponsorDeal(affordable.id, "harrow", affordable.seasons, game.season)
    )
    after = round_costs(game, "harrow", round_number=1).total
    assert after > before
    per_round = affordable.base_payment / len(game.calendar)
    assert after - before == pytest.approx(per_round)


def test_prize_money_arrives_through_the_season_on_last_years_finish(game):
    """Which is how the real thing works, and is what keeps a team solvent
    between January and the first cheque.  Paid as a lump at the flag instead,
    every team on the grid is bankrupt by August and the economy says nothing
    about anybody -- which is what the first version did."""
    labels = " ".join(
        line.label for line in round_costs(game, "harrow", round_number=1).lines
    )
    assert "prize money" in labels

    rich, poor = game.team("argent"), game.team("harrow")
    assert rich.prize_position < poor.prize_position
    rich_line = next(
        line for line in round_costs(game, "argent", round_number=1).lines
        if "prize money" in line.label
    )
    poor_line = next(
        line for line in round_costs(game, "harrow", round_number=1).lines
        if "prize money" in line.label
    )
    assert rich_line.amount > poor_line.amount > 0.0


def test_the_season_settles_what_this_years_points_were_worth(game):
    """The position money was already paid; this is the part that depends on
    how the season actually went."""
    standings = Standings.compute(
        [RaceOutcome(1, d, "harrow", 1) for d in game.team("harrow").drivers],
        game.rules,
        team_ids=["harrow", "argent"],
    )
    ledger = season_settlement(game, "harrow", standings, game.rules)
    assert any("championship bonus" in line.label for line in ledger.lines)
    assert ledger.total > 0.0


def test_a_ledger_adds_up(game):
    ledger = Ledger("t", (LedgerLine("in", 10.0), LedgerLine("out", -4.0)))
    assert ledger.income == pytest.approx(10.0)
    assert ledger.spending == pytest.approx(4.0)
    assert ledger.total == pytest.approx(6.0)
