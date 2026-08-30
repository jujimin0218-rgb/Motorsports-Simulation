"""The end of a season, and the winter after it.

Every management game gets this wrong in one of two directions: carry
everything over and the third season is decided before it starts, or reset
everything and none of the first two mattered.  The tests here are about which
side of that line each thing falls on.
"""

from __future__ import annotations

import pytest

from app.game.calendar import RoundPhase
from app.game.errors import InvalidGamePhase
from app.game.season import (
    REBASE_TO_LEVEL,
    RETIREMENT_AGE,
    close_season,
    start_next_season,
)
from app.game.standings import RaceOutcome


def finish_season(state, *, order=None) -> None:
    """Run every round on paper, finishing in car order unless told otherwise."""
    for number in range(1, len(state.calendar) + 1):
        entry = state.round(number)
        while not entry.is_complete:
            entry.advance()
        teams = order or sorted(state.teams.values(), key=lambda t: -t.car.overall)
        outcomes, position = [], 0
        for team in teams:
            for driver_id in team.drivers:
                position += 1
                outcomes.append(RaceOutcome(number, driver_id, team.id, position))
        state.record_outcomes(outcomes)


# -- closing it --------------------------------------------------------------


def test_a_season_cannot_be_settled_while_it_is_still_running(game):
    from app.services.game_service import GameService
    from app.services.jobs import JobRunner
    from app.services.storage import SaveStore

    service = GameService(store=SaveStore(":memory:"), jobs=JobRunner())
    try:
        service._state = game
        with pytest.raises(InvalidGamePhase):
            service.close_season()
    finally:
        service.close()


def test_closing_writes_the_year_into_the_history_book(game):
    finish_season(game)
    summary = close_season(game)

    assert len(game.history) == 1
    record = game.history[0]
    assert record.season == game.season
    assert record.driver_champion == summary.driver_champion
    assert record.constructor_champion
    assert record.player_team == game.player_team
    assert len(record.race_winners) == len(game.calendar)


def test_the_champions_are_the_top_of_the_tables(game):
    finish_season(game)
    summary = close_season(game)
    standings = game.standings()
    assert summary.driver_champion == standings.driver_champion
    assert summary.constructor_champion == standings.constructor_champion


def test_closing_pays_out(game):
    finish_season(game)
    before = {team.id: team.budget for team in game.teams.values()}
    close_season(game)
    # The champion is paid more than the last team, which is the point.
    winner = game.team(game.standings().constructor_champion)
    last = game.team(game.standings().teams[-1].team_id)
    assert winner.budget - before[winner.id] > last.budget - before[last.id]


# -- the winter --------------------------------------------------------------


def test_the_winter_gives_a_new_season_and_a_new_calendar(game):
    finish_season(game)
    close_season(game)
    year = game.season
    report = start_next_season(game)

    assert game.season == year + 1
    assert report["rounds"] == len(game.calendar)
    assert not game.season_complete
    assert game.current_round_number == 1
    assert all(entry.phase is RoundPhase.NOT_STARTED for entry in game.calendar)


def test_the_year_that_just_happened_is_cleared_but_not_forgotten(game):
    finish_season(game)
    close_season(game)
    start_next_season(game)

    assert game.outcomes == [], "last year's results are not this year's championship"
    assert game.standings().drivers[0].points == 0
    assert len(game.history) == 1, "but the year itself is kept"


def test_money_carries_and_research_does_not(game):
    """A good season pays for next year's car, which is the whole reason a
    season is worth winning.  A part designed for last year's car is worth
    nothing on this year's."""
    finish_season(game)
    for team in game.teams.values():
        team.rd_points = 500.0
    close_season(game)
    budgets = {team.id: team.budget for team in game.teams.values()}
    start_next_season(game)

    assert all(team.rd_points == 0.0 for team in game.teams.values())
    assert {t.id: t.budget for t in game.teams.values()} == budgets


def test_facilities_carry(game):
    """The slowest advantage in the game and the one that lasts."""
    finish_season(game)
    before = game.player.facilities.to_dict()
    close_season(game)
    start_next_season(game)
    assert game.player.facilities.to_dict() == before


def test_the_cost_cap_allowance_starts_again(game):
    finish_season(game)
    game.player.season_spending = 100.0
    close_season(game)
    start_next_season(game)
    assert game.player.season_spending == 0.0


# -- rebasing ----------------------------------------------------------------


def test_the_winter_removes_the_seasons_inflation_and_not_the_grid(game):
    """A season adds a few points to every car.  The winter is meant to take
    that back, not to hand the whole field a worse car than it started with."""
    finish_season(game)
    for team in game.teams.values():
        team.car.improve("aero", 0.05)
        team.car.improve("power_unit", 0.05)
    close_season(game)
    start_next_season(game)

    levels = [team.car.overall for team in game.teams.values()]
    mean = sum(levels) / len(levels)
    assert mean == pytest.approx(REBASE_TO_LEVEL, abs=0.01)


def test_the_spread_the_teams_earned_survives_the_winter(game):
    """A season of getting it right still decides who starts next season in
    front -- otherwise the development game is a treadmill."""
    finish_season(game)
    order_before = [
        t.id for t in sorted(game.teams.values(), key=lambda t: -t.car.overall)
    ]
    spread_before = max(t.car.overall for t in game.teams.values()) - min(
        t.car.overall for t in game.teams.values()
    )
    close_season(game)
    start_next_season(game)

    order_after = [
        t.id for t in sorted(game.teams.values(), key=lambda t: -t.car.overall)
    ]
    spread_after = max(t.car.overall for t in game.teams.values()) - min(
        t.car.overall for t in game.teams.values()
    )
    assert order_after == order_before
    assert 0.5 * spread_before < spread_after < spread_before


def test_five_seasons_do_not_run_the_grid_out_of_headroom(game):
    """The failure this exists to prevent: without a rebase every car reaches
    0.99 and development stops meaning anything."""
    for _ in range(5):
        finish_season(game)
        for team in game.teams.values():
            for area in ("aero", "power_unit", "chassis"):
                team.car.improve(area, 0.03)
        close_season(game)
        start_next_season(game)
    levels = [team.car.overall for team in game.teams.values()]
    assert max(levels) < 0.97, "somebody has run out of room to develop"
    assert sum(levels) / len(levels) == pytest.approx(REBASE_TO_LEVEL, abs=0.02)


# -- reputation --------------------------------------------------------------


def test_reputation_moves_toward_where_a_team_finished_not_to_it(game):
    """One good year does not make a big team and one bad year does not unmake
    one, and the fact that it takes seasons is what makes it worth building."""
    weak = game.team("harrow")
    before = weak.reputation
    # Win everything.
    finish_season(game, order=[weak] + [t for t in game.teams.values() if t is not weak])
    close_season(game)
    start_next_season(game)

    assert weak.reputation > before, "winning should count for something"
    assert weak.reputation < 0.95, "but not everything, in one year"


# -- drivers -----------------------------------------------------------------


def test_a_young_driver_improves_toward_their_potential(game):
    young = next(d for d in game.drivers.values() if d.age <= 23)
    young.potential = 0.99
    before = young.overall
    finish_season(game)
    close_season(game)
    start_next_season(game)
    assert young.overall > before
    assert young.overall <= young.potential + 1e-9


def test_an_old_driver_falls_away(game):
    old = next(d for d in game.drivers.values() if d.age >= 33)
    before = old.overall
    finish_season(game)
    close_season(game)
    start_next_season(game)
    if not old.retired:
        assert old.overall < before


def test_a_driver_who_has_fallen_far_enough_stops(game):
    """Which is what keeps the market from being the same twenty names for a
    decade."""
    veteran = next(d for d in game.drivers.values() if d.team is not None)
    veteran.age = RETIREMENT_AGE + 4
    for name in veteran.skills:
        veteran.skills[name] = 0.55

    finish_season(game)
    close_season(game)
    report = start_next_season(game)

    assert veteran.id in report["retired"]
    assert veteran.retired and veteran.team is None
    for team in game.teams.values():
        assert veteran.id not in team.drivers


def test_a_contract_that_ran_out_frees_the_driver(game):
    driver = game.driver(game.player.drivers[0])
    driver.contract.seasons_remaining = 1
    finish_season(game)
    close_season(game)
    report = start_next_season(game)

    assert driver.id in report["contracts_expired"]
    assert driver.team is None
    assert driver.id not in game.player.drivers


def test_everybody_still_has_a_seat_or_is_in_the_market(game):
    """Nobody is left in a team they have no contract with, and nobody is in
    two cars."""
    finish_season(game)
    close_season(game)
    start_next_season(game)

    seated = [d for team in game.teams.values() for d in team.drivers]
    assert len(seated) == len(set(seated))
    for driver_id in seated:
        assert game.driver(driver_id).team is not None
    for profile in game.drivers.values():
        if profile.team is not None:
            assert profile.id in game.team(profile.team).drivers


# -- persistence -------------------------------------------------------------


def test_a_game_with_history_round_trips(game):
    from app.game.state import GameState

    finish_season(game)
    close_season(game)
    start_next_season(game)
    assert GameState.from_dict(game.to_dict()).to_dict() == game.to_dict()
