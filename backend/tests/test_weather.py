"""The weather — which the engine had all along and the game was not using.

Phase 6's rule is not to reimplement anything the engine already has, so there
is nothing here that decides what the sky does.  What is tested is the thing
the game *does* own: continuity across a weekend, and the fact that it is
deterministic in both directions that matter.
"""

from __future__ import annotations

import pytest

from app.adapters.conditions import (
    OVERNIGHT_SECONDS,
    SESSIONS,
    SESSION_SECONDS,
    build_conditions,
)
from app.adapters.session_runner import track_for
from app.game.newgame import new_game


@pytest.fixture(scope="module")
def track():
    from f1_race_engine.track.io import load_track

    return load_track("synthetic_proving_ground")


def test_every_circuit_carries_the_climate_of_its_month(game):
    """A desert night race is not a Belgian afternoon, and that difference is
    what makes a wet-weather driver worth signing."""
    spa = game.calendar.circuit("circuit_de_spa_francorchamps")
    bahrain = game.calendar.circuit("bahrain_international_circuit")
    assert spa.rain_probability > bahrain.rain_probability * 5
    assert bahrain.air_temperature > spa.air_temperature


def test_the_climate_becomes_the_engines_own_forecast(game):
    circuit = game.calendar.circuit("circuit_de_spa_francorchamps")
    forecast = circuit.forecast()
    assert forecast.rain_probability == pytest.approx(circuit.rain_probability)
    assert forecast.air_temperature == pytest.approx(circuit.air_temperature)


def test_a_weekend_has_one_sky_running_through_it(game, track):
    """Practice, qualifying and the race are separate calls because the player
    acts between them, so the conditions have to be rebuilt and fast-forwarded
    rather than shared."""
    seen = [
        build_conditions(game, 1, track, session=session).summary()
        for session in SESSIONS
    ]
    # The sky moves.  It does not sit at the forecast all weekend.
    assert len({round(row["air_temperature"], 1) for row in seen}) > 1


def test_the_track_rubbers_in_as_the_weekend_goes(game, track):
    """Qualifying starts on the track Friday left behind, which is the whole
    reason practice is a session rather than a button."""
    friday = build_conditions(game, 1, track, session="practice").summary()
    saturday = build_conditions(game, 1, track, session="qualifying").summary()
    assert friday["rubber"] == pytest.approx(0.0, abs=1e-6)
    assert saturday["rubber"] > 0.3


def test_the_same_round_gets_the_same_weekend_however_often_it_is_asked(game, track):
    """The property the save system rests on: reload and re-run and it is the
    same afternoon."""
    first = build_conditions(game, 7, track, session="race").summary()
    again = build_conditions(game, 7, track, session="race").summary()
    assert first == again


def test_two_rounds_do_not_share_a_sky(game, track):
    assert (
        build_conditions(game, 3, track, session="race").summary()
        != build_conditions(game, 9, track, session="race").summary()
    )


def test_a_wet_venue_produces_wet_sessions_and_a_dry_one_does_not(game):
    """Not that any given session is wet -- it is a probability, and the engine
    decides.  Over a season the wettest venue on the calendar has to see more
    water than the driest, or the climate data is doing nothing."""
    from f1_race_engine.track.io import load_track

    def water_over_a_season(circuit_id: str) -> float:
        circuit = game.calendar.circuit(circuit_id)
        surface = load_track(circuit.physics_track)
        total = 0.0
        for round_number in range(1, len(game.calendar) + 1):
            # Hold the venue fixed and vary only the round, so what is being
            # compared is the climate rather than the calendar slot.
            game.calendar.round(round_number).circuit_id = circuit_id
            for session in SESSIONS:
                conditions = build_conditions(
                    game, round_number, surface, session=session
                )
                total += conditions.evolution.mean_water_depth
        return total

    original = [entry.circuit_id for entry in game.calendar]
    try:
        wet = water_over_a_season("circuit_de_spa_francorchamps")
        dry = water_over_a_season("bahrain_international_circuit")
    finally:
        for entry, circuit_id in zip(game.calendar.rounds, original):
            entry.circuit_id = circuit_id
    assert wet > dry


def test_the_fast_forward_is_the_clock_and_the_laps(game, track):
    """Re-driving a Friday to find out what the sky did would cost minutes to
    answer a question worth milliseconds, so the weekend is walked on the clock
    instead.  These are the numbers it walks."""
    assert SESSION_SECONDS == pytest.approx(3600.0)
    assert OVERNIGHT_SECONDS > SESSION_SECONDS


def test_an_unknown_session_is_refused(game, track):
    with pytest.raises(ValueError):
        build_conditions(game, 1, track, session="warmup")
