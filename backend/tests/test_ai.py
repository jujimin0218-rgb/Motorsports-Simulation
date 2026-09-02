"""The AI teams, and the rule they are written to.

**The AI does not cheat** (project rule 27).  It reads the same numbers the
player can read, spends the same money under the same cap, and its cars are
built by the same adapter.  Difficulty changes how well it decides and never
how fast it goes -- and that is the thing worth testing, because it is the
thing that is easy to get wrong.
"""

from __future__ import annotations

import pytest

from app.game.ai import remaining_demand, run_ai_development, run_ai_transfers
from app.game.car import AREA_NAMES
from app.game.settings import Difficulty


# -- what it can see ---------------------------------------------------------


def test_it_reads_the_calendar_rather_than_being_told(game):
    """A team with power circuits left should develop an engine.  Nobody tells
    it that; it looks at the rounds that have not been run."""
    demand = remaining_demand(game, 1)
    assert set(demand) == set(AREA_NAMES)
    assert all(0.0 <= value <= 1.0 for value in demand.values())


def test_the_demand_changes_as_the_season_goes(game):
    """A team looking at eight power circuits and a team looking at two are
    not facing the same question."""
    whole_season = remaining_demand(game, 1)
    for entry in game.calendar.rounds[:15]:
        entry.phase = entry.phase.__class__.COMPLETE
    late = remaining_demand(game, 16)
    assert late != whole_season


def test_a_finished_season_asks_for_nothing_more(game):
    for entry in game.calendar.rounds:
        entry.phase = entry.phase.__class__.COMPLETE
    assert all(value == 0.0 for value in remaining_demand(game, 1).values())


# -- what it does ------------------------------------------------------------


def test_it_spends_on_something_and_leaves_the_player_alone(game):
    for team in game.teams.values():
        team.rd_points = 400.0
    decisions = run_ai_development(game)

    assert len(decisions) == len(game.teams) - 1
    assert game.player_team not in {d.team_id for d in decisions}
    commissioned = [d for d in decisions if d.action == "commission"]
    assert commissioned, "somebody should have found something worth building"
    for decision in commissioned:
        assert decision.detail["area"] in AREA_NAMES
        assert decision.detail["arrives_at_round"] > game.current_round_number


def test_it_will_not_start_a_project_that_arrives_after_the_flag(game):
    """Research spent on a part that turns up in December is worse than
    research not spent."""
    for entry in game.calendar.rounds[:-1]:
        entry.phase = entry.phase.__class__.COMPLETE
    for team in game.teams.values():
        team.rd_points = 800.0

    decisions = run_ai_development(game)
    assert all(d.action == "hold" for d in decisions)
    assert all("no rounds left" in d.detail["reason"] for d in decisions)


def test_it_holds_when_it_has_nothing_to_spend(game):
    for team in game.teams.values():
        team.rd_points = 5.0
    decisions = run_ai_development(game)
    assert all(d.action == "hold" for d in decisions)


def test_it_respects_the_cost_cap_like_everybody_else(game):
    """The cap is not something the player alone is subject to."""
    cap = game.rules.budget.cap
    for team in game.teams.values():
        team.rd_points = 5000.0
        team.budget = 900.0
        team.season_spending = cap - 0.5
    decisions = run_ai_development(game)
    assert all(d.action == "hold" for d in decisions)
    for team in game.teams.values():
        assert team.season_spending <= cap + 1e-9


def test_it_cannot_spend_money_it_does_not_have(game):
    for team in game.teams.values():
        team.rd_points = 5000.0
        team.budget = 8.0
    run_ai_development(game)
    for team in game.teams.values():
        assert team.budget >= 0.0


def test_difficulty_changes_the_decision_and_not_the_car(game):
    """The property that matters most.  A harder AI must not have a faster
    car -- it must make better use of the one it has."""
    from copy import deepcopy

    def run(level: Difficulty):
        state = deepcopy(game)
        state.settings.difficulty = level
        for team in state.teams.values():
            team.rd_points = 500.0
        before = {t.id: t.car.to_dict() for t in state.teams.values()}
        decisions = run_ai_development(state)
        after = {t.id: t.car.to_dict() for t in state.teams.values()}
        return decisions, before, after

    for level in (Difficulty.EASY, Difficulty.HARD):
        decisions, before, after = run(level)
        # Commissioning changes nothing on the car today; the part has to be
        # built first.  If this ever fails, the AI is being handed performance.
        assert before == after, f"{level} altered a car by deciding"

    easy, _, _ = run(Difficulty.EASY)
    hard, _, _ = run(Difficulty.HARD)
    assert [d.detail.get("area") for d in easy] != [
        d.detail.get("area") for d in hard
    ], "difficulty should change what the AI picks"


def test_the_same_seed_gives_the_same_ai(game):
    from copy import deepcopy

    def run():
        state = deepcopy(game)
        for team in state.teams.values():
            team.rd_points = 400.0
        return [d.to_dict() for d in run_ai_development(state)]

    assert run() == run()


# -- the transfer market -----------------------------------------------------


def test_it_only_signs_a_driver_who_would_actually_come(game):
    """Not "who is the best free agent" but "who would improve one of my cars
    and would sign for me", which is a different and much better question for
    a team at the back."""
    for profile in game.drivers.values():
        if profile.contract is not None:
            profile.contract.seasons_remaining = 1

    decisions = run_ai_transfers(game)
    for decision in decisions:
        team = game.team(decision.team_id)
        signed = game.driver(decision.detail["driver"])
        replaced = game.driver(decision.detail["replaced"])
        assert signed.team == team.id
        assert signed.id in team.drivers
        assert replaced.team is None
        assert signed.overall > replaced.overall
        assert len(team.drivers) == 2, "a team must not end up with three drivers"


def test_it_leaves_drivers_who_are_still_under_contract_alone(game):
    for profile in game.drivers.values():
        if profile.contract is not None:
            profile.contract.seasons_remaining = 3
    assert run_ai_transfers(game) == []


def test_it_does_not_touch_the_players_team(game):
    for profile in game.drivers.values():
        if profile.contract is not None:
            profile.contract.seasons_remaining = 1
    before = list(game.player.drivers)
    run_ai_transfers(game)
    assert game.player.drivers == before
