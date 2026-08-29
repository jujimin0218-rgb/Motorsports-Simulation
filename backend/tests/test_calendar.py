"""The calendar, the circuits, and the phase machine that guards a round."""

from __future__ import annotations

import pytest

from app.game.calendar import Calendar, Circuit, Round, RoundPhase
from app.game.car import AREA_NAMES, CarPerformance
from app.game.errors import InvalidGamePhase, UnknownEntity


# -- the calendar ------------------------------------------------------------


def test_the_shipped_calendar_is_a_full_season():
    calendar = Calendar.load()
    assert len(calendar) == 22
    assert [entry.number for entry in calendar] == list(range(1, 23))
    assert len({entry.circuit_id for entry in calendar}) == 22


def test_every_round_names_a_circuit_that_exists():
    calendar = Calendar.load()
    for entry in calendar:
        circuit = calendar.circuit(entry.circuit_id)
        assert circuit.race_laps > 0
        assert circuit.length_km > 0


def test_every_circuit_names_an_engine_track_the_race_can_be_run_on():
    """The bridge that has to hold for Phase 2: a round is worthless if the
    physics has nothing to run it on."""
    from f1_race_engine.track.io import builtin_track_names

    available = set(builtin_track_names())
    for circuit in Calendar.load().circuits.values():
        assert circuit.physics_track in available, circuit.id


def test_race_distances_are_grand_prix_length():
    """Every real grand prix is a bit over 300 km, except Monaco, which is the
    one race the rules let run short."""
    calendar = Calendar.load()
    for entry in calendar:
        circuit = calendar.circuit(entry.circuit_id)
        assert 250.0 < circuit.race_distance_km < 320.0, circuit.name


def test_an_unknown_round_or_circuit_is_refused():
    calendar = Calendar.load()
    with pytest.raises(UnknownEntity):
        calendar.round(99)
    with pytest.raises(UnknownEntity):
        calendar.circuit("nurburgring_nordschleife")


# -- what a circuit asks of a car --------------------------------------------


def test_a_circuit_weights_every_area_of_the_car():
    weights = Circuit(id="x", name="X").area_weights()
    assert set(weights) == set(AREA_NAMES)


def test_monza_and_monaco_ask_for_opposite_cars():
    """The single most important thing about the track model: if these two came
    out the same, every circuit would be the same circuit."""
    calendar = Calendar.load()
    monza = calendar.circuit("autodromo_nazionale_monza").area_weights()
    monaco = calendar.circuit("circuit_de_monaco").area_weights()

    assert monza["power_unit"] > 0.8 and monza["aero"] < 0.4
    assert monaco["aero"] > 0.8 and monaco["power_unit"] < 0.4

    powerful = CarPerformance(power_unit=0.98, aero=0.60, mechanical_grip=0.60)
    nimble = CarPerformance(power_unit=0.60, aero=0.98, mechanical_grip=0.98)
    assert powerful.rating_for(monza) > nimble.rating_for(monza)
    assert nimble.rating_for(monaco) > powerful.rating_for(monaco)


def test_mechanical_grip_is_the_complement_of_power():
    """A lap decided on the straights is not decided in the slow corners."""
    fast = Circuit(id="a", name="A", power_sensitivity=0.95).area_weights()
    slow = Circuit(id="b", name="B", power_sensitivity=0.20).area_weights()
    assert fast["mechanical_grip"] < slow["mechanical_grip"]


def test_reliability_always_counts_for_something():
    """A car that breaks scores nothing anywhere, so no circuit weights it at
    zero -- it just counts for more where the brakes are worked hardest."""
    gentle = Circuit(id="a", name="A", brake_stress=0.0).area_weights()
    brutal = Circuit(id="b", name="B", brake_stress=1.0).area_weights()
    assert gentle["reliability"] > 0.0
    assert brutal["reliability"] > gentle["reliability"]


# -- the phase machine -------------------------------------------------------


def test_a_round_walks_the_whole_weekend_in_order():
    entry = Round(number=1, circuit_id="x")
    order = [
        RoundPhase.PRACTICE,
        RoundPhase.QUALIFYING,
        RoundPhase.STRATEGY,
        RoundPhase.RACE,
        RoundPhase.RESULT,
        RoundPhase.DEVELOPMENT,
        RoundPhase.COMPLETE,
    ]
    assert entry.phase is RoundPhase.NOT_STARTED
    for expected in order:
        assert entry.advance() is expected
    assert entry.is_complete


def test_a_round_will_not_skip_a_phase():
    """Enforced here rather than in the UI: hiding a button is a convenience
    for the player, not a rule the game keeps."""
    entry = Round(number=1, circuit_id="x")
    with pytest.raises(InvalidGamePhase):
        entry.require(RoundPhase.RACE)
    entry.advance()  # practice
    with pytest.raises(InvalidGamePhase):
        entry.require(RoundPhase.RACE)


def test_a_completed_round_cannot_be_advanced_again():
    entry = Round(number=1, circuit_id="x", phase=RoundPhase.COMPLETE)
    with pytest.raises(InvalidGamePhase):
        entry.advance()


def test_advancing_guards_against_a_round_that_moved_underneath_you():
    """Two clients on one save must not both step the same round."""
    entry = Round(number=1, circuit_id="x", phase=RoundPhase.QUALIFYING)
    with pytest.raises(InvalidGamePhase):
        entry.advance(expected=RoundPhase.PRACTICE)
    assert entry.phase is RoundPhase.QUALIFYING


def test_the_calendar_knows_which_round_the_season_is_waiting_on():
    calendar = Calendar.load()
    assert calendar.next_incomplete.number == 1
    for entry in calendar.rounds[:3]:
        entry.phase = RoundPhase.COMPLETE
    assert calendar.next_incomplete.number == 4
    for entry in calendar.rounds:
        entry.phase = RoundPhase.COMPLETE
    assert calendar.next_incomplete is None


def test_the_calendar_round_trips():
    calendar = Calendar.load()
    calendar.round(3).phase = RoundPhase.RESULT
    assert Calendar.from_dict(calendar.to_dict()).to_dict() == calendar.to_dict()
