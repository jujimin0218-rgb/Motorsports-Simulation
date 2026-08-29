"""The regulations, and the fact that they are data (project rule 30)."""

from __future__ import annotations

import pytest

from app.game.rules import PointsRules, Rules


def test_the_shipped_rules_load():
    rules = Rules.load()
    assert rules.season_length == 22
    assert rules.cars_per_team == 2
    assert rules.points.race[0] > rules.points.race[-1]


def test_points_are_read_from_the_rules_not_written_into_the_code():
    """A different era is a different file and nothing else."""
    rules = Rules.from_dict({"points": {"race": [10, 6, 4, 3, 2, 1]}})
    assert rules.points.for_position(1) == 10
    assert rules.points.for_position(6) == 1
    assert rules.points.for_position(7) == 0


def test_no_points_outside_the_scoring_positions():
    points = PointsRules()
    assert points.for_position(len(points.race)) > 0
    assert points.for_position(len(points.race) + 1) == 0
    assert points.for_position(0) == 0


def test_the_fastest_lap_only_pays_near_the_front():
    """A car three laps down pitting for softs must not take a point off the
    fight at the front, which is exactly why the real rule has this clause."""
    points = PointsRules(fastest_lap=1, fastest_lap_within_position=10)
    assert points.fastest_lap_points(1) == 1
    assert points.fastest_lap_points(10) == 1
    assert points.fastest_lap_points(11) == 0


def test_prize_money_rewards_both_position_and_points():
    rules = Rules.load()
    first = rules.prize_money.payout(1, 400)
    fifth = rules.prize_money.payout(5, 120)
    assert first > fifth > 0.0
    # And two teams on the same position are separated by what they scored.
    assert rules.prize_money.payout(3, 200) > rules.prize_money.payout(3, 100)


def test_rules_round_trip():
    rules = Rules.load()
    assert Rules.from_dict(rules.to_dict()) == rules


def test_development_returns_diminish():
    """The exponent below one is the balance of the whole R&D game."""
    rules = Rules.load()
    assert 0.0 < rules.development.diminishing_returns_exponent < 1.0
