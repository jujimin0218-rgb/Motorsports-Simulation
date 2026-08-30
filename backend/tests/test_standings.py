"""The championship: computed from results, never accumulated."""

from __future__ import annotations

import pytest

from app.game.rules import Rules
from app.game.standings import RaceOutcome, Standings


@pytest.fixture
def rules() -> Rules:
    return Rules.load()


def win(round_number: int, driver: str, team: str, **kwargs) -> RaceOutcome:
    return RaceOutcome(round_number, driver, team, 1, **kwargs)


def test_a_win_is_worth_what_the_rules_say():
    rules = Rules.from_dict({"points": {"race": [50, 30], "fastest_lap": 0}})
    assert win(1, "a", "red").points(rules) == 50


def test_a_retirement_scores_nothing_however_it_is_classified(rules):
    """A car classified fifteenth because it stopped on lap 40 did not finish
    fifteenth in any sense the championship cares about."""
    assert RaceOutcome(1, "a", "red", 5, retired=True).points(rules) == 0
    assert RaceOutcome(1, "a", "red", 5).points(rules) > 0


def test_the_fastest_lap_point_follows_the_rules_clause(rules):
    near = RaceOutcome(1, "a", "red", 4, fastest_lap=True).points(rules)
    far = RaceOutcome(1, "a", "red", 15, fastest_lap=True).points(rules)
    assert near == rules.points.for_position(4) + 1
    assert far == 0


def test_a_team_scores_both_its_cars(rules):
    standings = Standings.compute(
        [RaceOutcome(1, "a", "red", 1), RaceOutcome(1, "b", "red", 3)], rules
    )
    assert standings.teams[0].points == rules.points.for_position(
        1
    ) + rules.points.for_position(3)


def test_points_decide_first(rules):
    """Before any countback, the table is the points."""
    outcomes = [
        RaceOutcome(1, "a", "red", 1),      # 25
        RaceOutcome(3, "a", "red", 4),      # 12  -> 37
        RaceOutcome(1, "b", "blue", 2),     # 18
        RaceOutcome(2, "b", "blue", 2),     # 18  -> 36
    ]
    standings = Standings.compute(outcomes, rules)
    assert [row.driver_id for row in standings.drivers] == ["a", "b"]
    assert standings.drivers[0].points == 37
    assert standings.drivers[1].points == 36


def test_a_tie_on_points_goes_to_the_one_with_more_wins(rules):
    """Countback rather than alphabetical, and wins come first -- a driver who
    won a race beats one who never did on the same total, which is how the
    sport settles it and, more usefully, is a rule a player can see."""
    outcomes = [
        # 'winner' takes one race and scores nothing else: 25.
        RaceOutcome(1, "winner", "red", 1),
        # 'steady' is second and sixth and ninth: 18 + 8 + 2 = 28... trim it to
        # land on exactly 25 with no win: 18 + 6 + 1 = 25.
        RaceOutcome(1, "steady", "blue", 2),
        RaceOutcome(2, "steady", "blue", 7),
        RaceOutcome(3, "steady", "blue", 10),
    ]
    standings = Standings.compute(outcomes, rules)
    by_id = {row.driver_id: row for row in standings.drivers}
    assert by_id["winner"].points == by_id["steady"].points == 25
    assert by_id["winner"].wins == 1 and by_id["steady"].wins == 0
    assert by_id["winner"].position < by_id["steady"].position


def test_level_on_points_and_wins_falls_through_to_the_best_result(rules):
    """Two drivers with the same total and no wins between them are separated
    by the best single afternoon either had."""
    outcomes = [
        RaceOutcome(1, "second", "blue", 2),    # 18
        RaceOutcome(2, "second", "blue", 8),    # 4
        RaceOutcome(3, "second", "blue", 9),    # 2  -> 24
        RaceOutcome(1, "third", "green", 3),    # 15
        RaceOutcome(2, "third", "green", 6),    # 8
        RaceOutcome(3, "third", "green", 10),   # 1  -> 24
    ]
    standings = Standings.compute(outcomes, rules)
    by_id = {row.driver_id: row for row in standings.drivers}
    assert by_id["second"].points == by_id["third"].points == 24
    assert by_id["second"].wins == by_id["third"].wins == 0
    assert by_id["second"].podiums == by_id["third"].podiums == 1
    assert by_id["second"].best_finish == 2 and by_id["third"].best_finish == 3
    assert by_id["second"].position < by_id["third"].position


def test_everybody_in_the_championship_appears_even_with_nothing(rules):
    """A driver who has not scored belongs at the bottom of the table, which
    is where the player will look for them -- not missing from it."""
    standings = Standings.compute(
        [RaceOutcome(1, "a", "red", 1)],
        rules,
        driver_ids=["a", "b", "c"],
        team_ids=["red", "blue"],
    )
    assert len(standings.drivers) == 3
    assert len(standings.teams) == 2
    assert standings.drivers[-1].points == 0


def test_the_table_is_a_function_of_the_results_and_nothing_else(rules):
    """No running total anywhere means no running total that can drift."""
    outcomes = [RaceOutcome(1, "a", "red", 1), RaceOutcome(2, "a", "red", 2)]
    full = Standings.compute(outcomes, rules)
    without_second = Standings.compute(outcomes[:1], rules)
    assert full.drivers[0].points > without_second.drivers[0].points
    # Recomputing the same input twice gives the same table.
    assert Standings.compute(outcomes, rules).to_dict() == full.to_dict()


def test_counts_are_kept_as_well_as_points(rules):
    outcomes = [
        RaceOutcome(1, "a", "red", 1, pole=True, fastest_lap=True),
        RaceOutcome(2, "a", "red", 3),
        RaceOutcome(3, "a", "red", 18, retired=True),
    ]
    row = Standings.compute(outcomes, rules).drivers[0]
    assert (row.wins, row.podiums, row.poles, row.fastest_laps, row.dnfs) == (
        1, 2, 1, 1, 1,
    )
    assert row.starts == 3
    assert row.best_finish == 1


def test_champions_are_the_top_of_each_table(rules):
    standings = Standings.compute(
        [RaceOutcome(1, "a", "red", 1), RaceOutcome(1, "b", "blue", 2)], rules
    )
    assert standings.driver_champion == "a"
    assert standings.constructor_champion == "red"
    assert standings.driver_position("b") == 2
    assert standings.team_position("blue") == 2


def test_an_empty_championship_has_no_champion(rules):
    empty = Standings.compute([], rules)
    assert empty.driver_champion is None
    assert empty.constructor_champion is None


def test_outcomes_round_trip():
    outcome = RaceOutcome(3, "a", "red", 2, started=5, laps_completed=57, pole=True)
    assert RaceOutcome.from_dict(outcome.to_dict()) == outcome
