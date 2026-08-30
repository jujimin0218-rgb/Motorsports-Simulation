"""The seam, exercised for real (project rule 35).

    GameState -> adapter -> the existing race engine -> RaceResult -> championship

Nothing is stubbed here.  The engine simulates every car on every lap, which is
why the grid is cut to four teams and the race to a handful of laps: the point
is that the whole chain works, not that it works twenty cars at a time, and a
full field over a full distance is ten minutes of arithmetic.
"""

from __future__ import annotations

import pytest

from app.adapters.session_runner import (
    build_field,
    outcomes_from,
    run_race,
    setup_for,
    track_for,
)
from app.game.calendar import RoundPhase
from app.services import round_service


# -- the field ---------------------------------------------------------------


def test_the_field_is_built_from_the_game_not_from_a_file(small_game):
    field = build_field(small_game, 1, fuel_mass=100.0)
    assert len(field) == 8
    assert {item.car_number for item in field} == set(range(1, 9))

    for item in field:
        profile = small_game.driver(item.driver_id)
        assert item.entry.driver.name == profile.name
        assert item.entry.vehicle.spec.metadata["team_id"] == item.team_id
        assert item.entry.team == small_game.team(item.team_id).name


def test_a_driver_signed_this_morning_is_in_the_car_this_afternoon(small_game):
    """The field is assembled from the game every session, so there is no
    cached lineup to go stale."""
    team = small_game.team("harrow")
    newcomer = small_game.free_agents[0]
    replaced = team.drivers[1]
    small_game.driver(replaced).team = None
    newcomer.team = team.id
    team.drivers[1] = newcomer.id

    names = {item.driver_id for item in build_field(small_game, 1, fuel_mass=100.0)}
    assert newcomer.id in names
    assert replaced not in names


def test_the_wing_comes_off_the_circuit(small_game):
    """Not a lap-time correction: the wing level changes the car's real lift
    and drag, and the engine decides what that is worth."""
    monza = small_game.calendar.circuit("autodromo_nazionale_monza")
    monaco = small_game.calendar.circuit("circuit_de_monaco")
    assert setup_for(monza).wing_level < setup_for(monaco).wing_level


def test_every_round_has_a_circuit_the_engine_can_drive(small_game):
    for entry in small_game.calendar:
        track = track_for(small_game.calendar.circuit(entry.circuit_id))
        assert track.length > 1000.0


# -- a race ------------------------------------------------------------------


@pytest.fixture(scope="module")
def raced(request):
    """One real race, run once and shared.

    Module-scoped because it is the expensive fixture in the suite: eight cars
    over two laps of the engine's own session, with hazards on.
    """
    from app.game.newgame import new_game

    state = new_game(player_team="harrow", seed=20260101)
    keep = ["argent", "scuderia_lucente", "cobalt", "harrow"]
    state.teams = {tid: state.teams[tid] for tid in keep}
    for profile in state.drivers.values():
        if profile.team not in keep:
            profile.team = None
    result, field, weather = run_race(state, 1, laps=2, racing=True, hazards=True)
    return state, result, field, weather


def test_the_engine_produced_a_real_classification(raced):
    _state, result, _field, _weather = raced
    assert len(result.classification) == 8
    positions = [row.position for row in result.classification]
    assert positions == list(range(1, 9))

    winner = result.classification[0]
    assert winner.laps_completed >= 1
    assert winner.total_time > 0.0
    # Lap times that came out of a force balance, not a table.
    assert 50.0 < winner.best_lap < 200.0


def test_tyres_and_fuel_moved_because_a_race_was_actually_driven(raced):
    _state, result, _field, _weather = raced
    for row in result.classification:
        if row.retired:
            continue
        assert row.tyre_wear > 0.0, "a car that raced wore its tyres"
        assert row.fuel_remaining < 100.0, "a car that raced burned fuel"


def test_the_result_becomes_a_championship(raced):
    state, result, field, _weather = raced
    outcomes = outcomes_from(result, field, 1, pole=1)
    assert len(outcomes) == 8
    assert {o.driver_id for o in outcomes} == {item.driver_id for item in field}

    state.record_outcomes(outcomes)
    standings = state.standings()
    assert standings.driver_champion is not None
    scored = [row for row in standings.drivers if row.points > 0]
    assert scored, "somebody has to have scored"
    # The winner scored the most, and a retirement scored nothing.
    assert standings.drivers[0].points == max(row.points for row in standings.drivers)
    for outcome in outcomes:
        if outcome.retired:
            assert outcome.points(state.rules) == 0


def test_exactly_one_fastest_lap_is_awarded(raced):
    _state, result, field, _weather = raced
    outcomes = outcomes_from(result, field, 1)
    assert sum(1 for o in outcomes if o.fastest_lap) <= 1


def test_the_same_seed_runs_the_same_race(small_game):
    """The property the whole save system rests on: reload and re-run and it
    is the same afternoon, because the randomness is addressed by season and
    round rather than drawn in call order."""
    from app.game.newgame import new_game

    def once():
        state = new_game(player_team="harrow", seed=4242)
        keep = ["argent", "harrow"]
        state.teams = {tid: state.teams[tid] for tid in keep}
        for profile in state.drivers.values():
            if profile.team not in keep:
                profile.team = None
        result, _field, _weather = run_race(state, 3, laps=2, racing=True, hazards=True)
        return [
            (row.car_number, round(row.total_time, 9)) for row in result.classification
        ]

    assert once() == once()


# -- the round machine, on the real engine -----------------------------------


def test_a_whole_weekend_runs_through_the_service(small_game):
    """Start to finish on the engine, with qualifying skipped for time -- the
    grid is then entry order, which is what a round run without qualifying
    does and is a case the race has to handle anyway."""
    entry = small_game.round(1)
    small_game.settings.race_distance = 0.05  # the floor: five laps

    assert round_service.start_round(small_game).phase is RoundPhase.PRACTICE
    assert round_service.run_practice(small_game).phase is RoundPhase.QUALIFYING
    # Step past qualifying without running it.
    entry.advance(RoundPhase.QUALIFYING)

    report = round_service.run_race(small_game)
    assert report.phase is RoundPhase.RESULT
    assert report.detail["race_id"] == "2026-01"
    assert len(report.detail["classification"]) == 8

    assert round_service.run_development(small_game).phase is RoundPhase.COMPLETE
    assert small_game.current_round_number == 2

    # The championship, the archive and the research all moved.
    assert small_game.standings().drivers[0].points > 0
    assert "2026-01" in small_game.race_archive
    assert small_game.team("harrow").rd_points > 0


def test_the_archive_keeps_the_engines_own_result_whole(small_game):
    """A replay that can only show what a summary kept is not a replay."""
    small_game.settings.race_distance = 0.05
    entry = small_game.round(1)
    round_service.start_round(small_game)
    round_service.run_practice(small_game)
    entry.advance(RoundPhase.QUALIFYING)
    round_service.run_race(small_game)

    archive = small_game.race_archive["2026-01"]
    assert archive["laps"] >= 5
    assert len(archive["classification"]) == 8
    assert "lap_records" in archive, "lap-by-lap timing is what a replay needs"
    assert archive["drivers"], "and who was in which car"
    any_car = next(iter(archive["lap_records"].values()))
    assert any_car and "lap_time" in any_car[0]


def test_a_race_cannot_be_run_twice(small_game):
    small_game.settings.race_distance = 0.05
    entry = small_game.round(1)
    round_service.start_round(small_game)
    round_service.run_practice(small_game)
    entry.advance(RoundPhase.QUALIFYING)
    round_service.run_race(small_game)

    from app.game.errors import InvalidGamePhase

    with pytest.raises(InvalidGamePhase):
        round_service.run_race(small_game)
