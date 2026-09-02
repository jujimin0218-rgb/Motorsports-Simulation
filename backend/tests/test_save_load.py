"""Saving and loading, and the thing that makes it worth having: exactness.

A save that comes back nearly the same is not a save.  The tests here check
that what goes in comes out -- including the seed, which is what makes a round
replayed after a load the same round.
"""

from __future__ import annotations

import pytest

from app.game.calendar import RoundPhase
from app.game.errors import SaveNotFound
from app.game.newgame import new_game
from app.game.standings import RaceOutcome
from app.game.state import GameState, SAVE_VERSION
from app.services.storage import AUTOSAVE_SLOT, SaveStore


def test_a_fresh_game_round_trips(game):
    assert GameState.from_dict(game.to_dict()).to_dict() == game.to_dict()


def test_a_game_in_progress_round_trips(game, store):
    """The one that matters: an empty save is easy."""
    game.player.spend(18.5, what="an upgrade")
    game.player.car.improve("aero", 0.03)
    game.player.facilities.upgrade("simulator")
    game.driver(game.player.drivers[0]).form = -0.4
    game.round(1).phase = RoundPhase.RESULT
    game.record_outcomes(
        [
            RaceOutcome(1, d, game.team_of(d) or "", position, pole=(position == 1))
            for position, d in enumerate(sorted(game.drivers)[:20], start=1)
        ]
    )
    game.race_archive["r1"] = {"track": "somewhere", "laps": 57}

    summary = store.save(game)
    restored = store.load(summary.id)
    assert restored.to_dict() == game.to_dict()


def test_the_things_a_save_exists_to_preserve(game, store):
    game.player.spend(30.0)
    game.record_outcomes([RaceOutcome(1, game.player.drivers[0], game.player_team, 1)])
    restored = store.load(store.save(game).id)

    assert restored.seed == game.seed
    assert restored.player.budget == pytest.approx(game.player.budget)
    assert restored.standings().to_dict() == game.standings().to_dict()
    assert restored.round(1).phase is game.round(1).phase


def test_the_seed_survives_so_the_next_race_is_the_same_race(game, store):
    """The point of storing the seed rather than a random-number generator's
    internal position: a loaded save is in exactly the position the original
    was, whatever was drawn in between."""
    before = game.round_rng(5).stream("race").random()
    game.rng.stream("noise").random()  # churn, which must not matter
    restored = store.load(store.save(game).id)
    assert restored.round_rng(5).stream("race").random() == pytest.approx(before)


def test_a_save_can_be_overwritten_in_place(game, store):
    summary = store.save(game)
    game.player.earn(50.0)
    again = store.save(game, save_id=summary.id)
    assert again.id == summary.id
    assert again.created_at == summary.created_at
    assert store.load(summary.id).player.budget == pytest.approx(game.player.budget)
    assert len(store.list()) == 1


def test_the_autosave_has_its_own_slot(game, store):
    """So that the game writing to it can never quietly overwrite a save the
    player made deliberately."""
    manual = store.save(game)
    game.player.earn(10.0)
    auto = store.autosave(game)
    assert auto.id != manual.id
    assert auto.slot == AUTOSAVE_SLOT

    game.player.earn(10.0)
    again = store.autosave(game)
    assert again.id == auto.id, "the autosave replaces itself"
    assert len(store.list()) == 2
    assert store.load_slot(AUTOSAVE_SLOT).player.budget == pytest.approx(
        game.player.budget
    )


def test_saves_are_listed_newest_first_without_opening_them(game, store):
    first = store.save(game)
    game.name = "Second"
    second = store.save(game)
    listed = store.list()
    assert [row.id for row in listed] == [second.id, first.id]
    assert listed[0].name == "Second"
    assert listed[0].season == game.season
    assert listed[0].round == game.current_round_number


def test_the_listed_round_follows_the_season(game, store):
    for entry in game.calendar.rounds[:4]:
        entry.phase = RoundPhase.COMPLETE
    assert store.save(game).round == 5


def test_deleting_a_save_removes_it(game, store):
    summary = store.save(game)
    store.delete(summary.id)
    assert store.list() == []
    with pytest.raises(SaveNotFound):
        store.load(summary.id)
    with pytest.raises(SaveNotFound):
        store.delete(summary.id)


def test_loading_something_that_is_not_there_says_so(store):
    with pytest.raises(SaveNotFound):
        store.load("nope")
    with pytest.raises(SaveNotFound):
        store.load_slot(AUTOSAVE_SLOT)


def test_a_save_from_a_future_build_is_refused_rather_than_guessed_at(game):
    from app.game.errors import UnknownEntity

    payload = game.to_dict()
    payload["version"] = SAVE_VERSION + 1
    with pytest.raises(UnknownEntity):
        GameState.from_dict(payload)


def test_a_save_survives_a_store_being_closed_and_reopened(game, tmp_path):
    path = tmp_path / "career.db"
    with SaveStore(path) as store:
        summary = store.save(game)
    with SaveStore(path) as reopened:
        assert reopened.load(summary.id).to_dict() == game.to_dict()


def test_recording_a_round_twice_replaces_rather_than_scores_twice(game):
    """Which is what makes a round re-runnable: replaying a race must not
    double the points it paid out."""
    driver = game.player.drivers[0]
    game.record_outcomes([RaceOutcome(1, driver, game.player_team, 1)])
    first = game.standings().drivers[0].points
    game.record_outcomes([RaceOutcome(1, driver, game.player_team, 1)])
    assert game.standings().drivers[0].points == first
    assert len(game.outcomes_for_round(1)) == 1

    game.record_outcomes([RaceOutcome(1, driver, game.player_team, 5)])
    assert game.standings().driver_position(driver) is not None
    assert len(game.outcomes_for_round(1)) == 1
    assert game.outcomes_for_round(1)[0].position == 5


def test_a_deliberate_save_does_not_land_in_the_autosave_slot(game):
    """The autosave is rewritten after every phase of a weekend.

    A player who carries on from it and then saves on purpose -- before a
    gamble, say -- is making a checkpoint.  Writing that back into the slot the
    autosave owns means the next phase quietly overwrites it, so the one save
    they made deliberately is the one they cannot keep.
    """
    from app.services.game_service import GameService
    from app.services.jobs import JobRunner

    service = GameService(store=SaveStore(":memory:"), jobs=JobRunner(max_workers=1))
    try:
        service.start(player_team="harrow", seed=20260101, rounds=1)
        service._touch()
        autosave = next(s for s in service.saves() if s.slot == AUTOSAVE_SLOT)

        service.load(save_id=autosave.id)
        checkpoint = service.save(name="before the gamble")

        assert checkpoint.slot is None, "a deliberate save owns no slot"
        assert checkpoint.id != autosave.id

        service._touch()
        kept = {s.id for s in service.saves()}
        assert checkpoint.id in kept, "the next autosave took the checkpoint with it"
        assert autosave.id in kept

        # Saving again writes back to the same checkpoint rather than piling up.
        again = service.save(name="before the gamble")
        assert again.id == checkpoint.id
        assert len(service.saves()) == 2
    finally:
        service.close()
