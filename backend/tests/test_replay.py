"""The seam between the engine's race result and something playable.

The engine names the two cars in a move `attacker` and `defender`.  A replay
reads them as "who made the move" and "who was passed", and the translation
between those two vocabularies is the only interesting thing this adapter does
with an overtake -- so it is what these tests are about.  Reading a key the
engine does not emit costs nothing at import time and produces a race log of
empty rows at play time, which is the failure worth a test.
"""

from __future__ import annotations

from app.adapters.replay import build_replay
from f1_race_engine.race.traffic import OvertakeAttempt


class _Timing:
    """The slice of the engine's timing tower a replay actually asks for."""

    cars = (7, 44)

    def recorded_until(self, car: int) -> float:
        return 10.0

    def distance_at(self, car: int, moment: float) -> float:
        return moment * 50.0

    def offset_at(self, car: int, moment: float) -> float:
        """Car 44 runs a metre off the line, car 7 on it."""
        return 1.0 if car == 44 else 0.0


class _Result:
    timing = _Timing()
    classification = ()
    incidents = ()
    flags = ()
    track_name = "bahrain"
    laps = 5
    overtakes = (
        OvertakeAttempt(lap=3, distance=1200.0, attacker=7, defender=44, overlap=1.2, drs=True),
        OvertakeAttempt(lap=4, distance=800.0, attacker=44, defender=7, overlap=0.4, drs=False),
    )


def _replay():
    return build_replay(
        _Result(),
        race_id="2026-01",
        lap_length=5412.0,
        labels={
            7: {"driver": "a", "team": "t", "driver_name": "A", "team_name": "T"},
            44: {"driver": "b", "team": "u", "driver_name": "B", "team_name": "U"},
        },
    )


def test_an_overtake_names_both_cars():
    moves = [event for event in _replay().events if event["kind"] == "overtake"]

    assert len(moves) == 2
    first, second = moves
    assert (first["car_number"], first["passed"]) == (7, 44)
    assert (second["car_number"], second["passed"]) == (44, 7)


def test_an_overtake_says_something():
    """An event with nothing in it is a row the player learns nothing from."""
    moves = [event for event in _replay().events if event["kind"] == "overtake"]

    assert all(move["detail"] for move in moves)
    assert "44" in moves[0]["detail"], "the car that was passed belongs in the detail"


def test_drs_is_carried_through_and_not_invented():
    moves = [event for event in _replay().events if event["kind"] == "overtake"]

    assert "DRS" in moves[0]["detail"]
    assert "DRS" not in moves[1]["detail"]


def test_a_replay_says_where_across_the_road_each_car_was():
    """Two cars at the same distance are not in the same place.  Without this
    the map draws a race as a single file of dots, whatever the cars did."""
    replay = _replay()

    by_car = {car["car_number"]: car for car in replay.cars}
    assert by_car[7]["offsets"] == [0.0] * len(by_car[7]["distances"])
    assert by_car[44]["offsets"] == [1.0] * len(by_car[44]["distances"])


def test_the_offsets_line_up_with_the_distances():
    """They are read together, one sample at a time, so a short list would put
    a car somewhere it never was."""
    for car in _replay().cars:
        assert len(car["offsets"]) == len(car["distances"])
