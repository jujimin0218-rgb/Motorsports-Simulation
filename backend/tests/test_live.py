"""A race shown while it is still running.

Two things here, and the first is why the second exists.  A grand prix is
minutes of simulation, so the client is shown something as it goes -- and what
it was shown before was a fraction that stopped moving at the first
retirement, because the car that stopped never reported another lap.
"""

from __future__ import annotations

from app.adapters.live import build_live, build_live_qualifying, field_lap


class _Tower:
    """The slice of the engine's timing tower a live screen asks for."""

    def __init__(self, laps: dict[int, int]) -> None:
        self._laps = laps
        self.asked_at: float | None = None
        """The moment the screen was read at, which is the thing worth checking."""

    @property
    def cars(self) -> tuple[int, ...]:
        return tuple(sorted(self._laps))

    def laps_completed(self, car: int) -> int:
        return self._laps[car]

    def recorded_until(self, car: int) -> float:
        return 90.0 * self._laps[car]

    def fastest_lap(self):
        return None

    def snapshot_at(self, time: float):
        self.asked_at = time
        return tuple(
            _Position(index + 1, car, self._laps[car])
            for index, car in enumerate(sorted(self._laps, key=lambda c: -self._laps[c]))
        )


class _Gap:
    def __init__(self, text: str) -> None:
        self.formatted = text


class _Position:
    def __init__(self, position: int, car: int, laps: int) -> None:
        self.position = position
        self.car_number = car
        self.laps_completed = laps
        self.gap_to_leader = _Gap("+1.204")
        self.interval = _Gap("+0.512")


class _Entry:
    def __init__(self, car: int, running: bool) -> None:
        self.car_number = car
        self.running = running


class _Session:
    def __init__(self, laps: dict[int, int], retired: set[int]) -> None:
        self.timing = _Tower(laps)
        self.entries = tuple(_Entry(car, car not in retired) for car in sorted(laps))


LABELS = {
    1: {"driver": "Ravi Tanaka", "team": "Argent Grand Prix", "is_player": True},
    2: {"driver": "Leon Salgado", "team": "Apex GP", "is_player": False},
    3: {"driver": "Kai Duarte", "team": "Scuderia Lucente", "is_player": False},
}


def test_a_retirement_does_not_stop_the_race_advancing():
    """The bug this file exists for: car 3 stopped on lap 2 and the race went
    on without it, so the race is on lap 9, not lap 2."""
    session = _Session({1: 10, 2: 9, 3: 2}, retired={3})

    assert field_lap(session) == 9


def test_the_lap_is_the_slowest_car_still_racing():
    session = _Session({1: 10, 2: 9, 3: 7}, retired=set())

    assert field_lap(session) == 7


def test_a_field_that_has_all_stopped_reports_nothing_rather_than_raising():
    session = _Session({1: 4, 2: 4}, retired={1, 2})

    assert field_lap(session) == 0


def test_the_screen_names_the_drivers_and_marks_the_player():
    live = build_live(_Session({1: 10, 2: 9, 3: 2}, retired={3}), LABELS, lap=9, laps=14)

    assert live["lap"] == 9 and live["laps"] == 14
    assert [row["driver"] for row in live["order"]][:2] == ["Ravi Tanaka", "Leon Salgado"]
    assert live["order"][0]["is_player"] is True
    assert live["order"][0]["gap"] and live["order"][0]["interval"]


def test_a_stopped_car_drops_out_of_the_order_rather_than_holding_a_place():
    live = build_live(_Session({1: 10, 2: 9, 3: 2}, retired={3}), LABELS, lap=9, laps=14)

    running = [row for row in live["order"] if not row["retired"]]
    stopped = [row for row in live["order"] if row["retired"]]

    assert [row["position"] for row in running] == [1, 2]
    assert [row["car_number"] for row in stopped] == [3]
    assert stopped[0]["position"] is None
    assert live["retired"] == 1
    assert live["order"][-1]["retired"], "a car that is out belongs at the bottom"


def test_an_unknown_car_still_gets_a_row():
    """A label that is missing is a naming problem, not a reason to lose a car."""
    live = build_live(_Session({1: 3, 9: 3}, retired=set()), LABELS, lap=3, laps=5)

    assert {row["car_number"] for row in live["order"]} == {1, 9}
    assert [row for row in live["order"] if row["car_number"] == 9][0]["driver"] == "9"


class _Lap:
    def __init__(self, car: int, segment: str, lap_time: float) -> None:
        self.car_number = car
        self.segment = segment
        self.lap_time = lap_time


class _Qualifying:
    """A qualifying session partway through: car 3 has not been out yet."""

    entries = (_Entry(1, True), _Entry(2, True), _Entry(3, True))
    laps = (
        _Lap(1, "Q1", 92.400),
        _Lap(2, "Q1", 91.800),
        _Lap(1, "Q1", 91.200),  # car 1 improves on its second run
    )
    format = ("Q1", "Q2", "Q3")


def test_the_board_ranks_on_each_cars_best_lap():
    board = build_live_qualifying(
        _Qualifying(), LABELS, segment="Q1", done=0, total=3, complete=False
    )

    assert [row["car_number"] for row in board["order"][:2]] == [1, 2]
    assert board["order"][0]["best"] == 91.2, "a car is ranked on its best, not its last"
    assert board["order"][0]["gap"] == 0.0
    assert board["order"][1]["gap"] == 0.6


def test_a_car_with_no_time_is_shown_as_having_none():
    board = build_live_qualifying(
        _Qualifying(), LABELS, segment="Q1", done=0, total=3, complete=False
    )

    waiting = [row for row in board["order"] if row["best"] is None]
    assert [row["car_number"] for row in waiting] == [3]
    assert waiting[0]["position"] is None
    assert waiting[0]["driver"] == "Kai Duarte", "it is still somebody"


def test_a_running_segment_is_not_a_result():
    running = build_live_qualifying(
        _Qualifying(), LABELS, segment="Q1", done=0, total=3, complete=False
    )
    settled = build_live_qualifying(
        _Qualifying(), LABELS, segment="Q1", done=1, total=3, complete=True
    )

    assert running["complete"] is False and settled["complete"] is True


def test_the_screen_is_read_at_the_leaders_time_not_a_stopped_cars():
    """The bug this caught: a car that retired on lap 2 still has its last
    record back on lap 2, so reading the tower at the earliest record showed
    the race as it stood when that car stopped -- and the leader appeared to
    change every lap for the rest of the grand prix."""
    session = _Session({1: 10, 2: 9, 3: 2}, retired={3})

    build_live(session, LABELS, lap=9, laps=14)

    # 90s a lap in the stub: car 2 is the slowest still running, on lap 9.
    assert session.timing.asked_at == 90.0 * 9
    assert session.timing.asked_at != 90.0 * 2, "that is where the retired car stopped"


def test_a_race_everybody_retired_from_still_shows_where_it_got_to():
    session = _Session({1: 6, 2: 4}, retired={1, 2})

    live = build_live(session, LABELS, lap=4, laps=14)

    assert session.timing.asked_at == 90.0 * 6
    assert len(live["order"]) == 2 and live["retired"] == 2
