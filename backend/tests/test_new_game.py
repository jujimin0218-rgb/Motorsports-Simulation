"""Starting a game: everything comes out of the data files."""

from __future__ import annotations

import pytest

from app.game.errors import UnknownEntity
from app.game.newgame import available_teams, load_static_data, new_game
from app.game.rng import GameRng


def test_the_grid_is_complete_and_consistent():
    teams, drivers, engines = load_static_data()
    assert len(teams) == 10
    assert len(engines) >= 3

    # Two cars per team, and every seat filled by a driver who agrees they are
    # in it.  The two directions are stored separately, so this is worth a test.
    for team in teams.values():
        assert len(team.drivers) == 2, team.id
        for driver_id in team.drivers:
            assert drivers[driver_id].team == team.id

    # And no driver is in two cars at once.
    seated = [d for team in teams.values() for d in team.drivers]
    assert len(seated) == len(set(seated)) == 20


def test_there_are_drivers_outside_the_twenty_seats():
    """A transfer market with nobody in it is not a market."""
    _, drivers, _ = load_static_data()
    free = [d for d in drivers.values() if d.is_free_agent]
    assert len(free) >= 5


def test_every_team_runs_an_engine_that_exists():
    teams, _, engines = load_static_data()
    for team in teams.values():
        assert team.engine in engines, team.id


def test_a_works_team_gets_its_engine_free():
    _, _, engines = load_static_data()
    works = [e for e in engines.values() if e.works_team]
    assert works, "somebody has to be a works team"
    for supplier in works:
        assert supplier.cost_for(supplier.works_team) == 0.0
        assert supplier.cost_for("somebody_else") > 0.0


def test_the_team_list_is_offered_best_first_with_enough_to_choose_on():
    rows = available_teams()
    assert len(rows) == 10
    ratings = [row["car_rating"] for row in rows]
    assert ratings == sorted(ratings, reverse=True)
    for row in rows:
        assert row["drivers"] and row["budget"] > 0
    # Taking the quickest car should not also be taking the biggest budget in
    # every case, or there is no decision to make.
    assert rows[0]["name"] != min(rows, key=lambda r: r["budget"])["name"]


def test_a_new_game_is_a_whole_season_ready_to_run():
    game = new_game(player_team="meridian", seed=1234)
    assert game.season == 2026
    assert len(game.calendar) == 22
    assert game.player.id == "meridian"
    assert len(game.player.drivers) == 2
    assert game.current_round_number == 1
    assert not game.season_complete
    assert game.standings().drivers, "everybody starts in the table on zero"
    assert all(row.points == 0 for row in game.standings().drivers)


def test_you_cannot_start_as_a_team_that_does_not_exist():
    with pytest.raises(UnknownEntity):
        new_game(player_team="mclaren", seed=1)


def test_the_seed_is_stored_so_a_game_is_reproducible_from_its_first_moment():
    """Left out, the seed is drawn from the clock -- but it is then kept, so
    the game is reproducible from the start rather than from the first save."""
    game = new_game(player_team="cobalt")
    assert isinstance(game.seed, int)
    assert GameRng(game.seed).path == "game"


def test_two_games_on_one_seed_are_the_same_game():
    a = new_game(player_team="aurora", seed=777)
    b = new_game(player_team="aurora", seed=777)
    # created_at and name are wall-clock and cosmetic; everything else must match.
    left, right = a.to_dict(), b.to_dict()
    for payload in (left, right):
        payload.pop("created_at")
    assert left == right


def test_the_randomness_of_two_rounds_does_not_collide(game):
    """Addressed by round, so nothing depends on which one was run first."""
    seventh = game.round_rng(7).stream("weather").random()
    third = game.round_rng(3).stream("weather").random()
    seventh_again = game.round_rng(7).stream("weather").random()
    assert seventh != third
    assert seventh == pytest.approx(seventh_again, abs=1e-15)
