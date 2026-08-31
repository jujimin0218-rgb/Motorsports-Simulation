"""A session shown while it is still running.

Three things are worth pinning here, and each one was a bug.

The race stopped advancing at the first retirement, because the car that
stopped never reported another lap.  The order was read off interpolated
positions, which the engine anchors at time zero for every car even though a
standing start releases them a second and a half apart -- so the opening laps
came out scrambled.  And qualifying arrived in three jumps rather than building
up as the laps were set.
"""

from __future__ import annotations

from app.adapters.live import build_live, build_live_qualifying, field_lap


class _Record:
    def __init__(self, elapsed: float) -> None:
        self.elapsed = elapsed


class _Tower:
    """The slice of the engine's timing tower a live screen asks for.

    ``pace`` is seconds a lap on top of ninety, which is how these tests say
    who is quicker without inventing a physics model.
    """

    def __init__(self, laps: dict[int, int], pace: dict[int, float] | None = None) -> None:
        self._laps = laps
        self._pace = pace or {}

    @property
    def cars(self) -> tuple[int, ...]:
        return tuple(sorted(self._laps))

    def laps_completed(self, car: int) -> int:
        return self._laps[car]

    def records(self, car: int) -> tuple[_Record, ...]:
        lap_time = 90.0 + self._pace.get(car, 0.0)
        return tuple(_Record((n + 1) * lap_time) for n in range(self._laps[car]))

    def fastest_lap(self):
        return None


class _Entry:
    def __init__(self, car: int, running: bool) -> None:
        self.car_number = car
        self.running = running


class _Session:
    def __init__(
        self,
        laps: dict[int, int],
        retired: set[int],
        pace: dict[int, float] | None = None,
    ) -> None:
        self.timing = _Tower(laps, pace)
        self.entries = tuple(_Entry(car, car not in retired) for car in sorted(laps))


LABELS = {
    1: {"driver": "Ravi Tanaka", "team": "Argent Grand Prix", "is_player": True},
    2: {"driver": "Leon Salgado", "team": "Apex GP", "is_player": False},
    3: {"driver": "Kai Duarte", "team": "Scuderia Lucente", "is_player": False},
}


# -- how far the race has got -------------------------------------------------


def test_a_retirement_does_not_stop_the_race_advancing():
    """Car 3 stopped on lap 2 and the race went on without it, so the race is
    on lap 9 -- not parked on lap 2 for the rest of the afternoon."""
    session = _Session({1: 10, 2: 9, 3: 2}, retired={3})

    assert field_lap(session) == 9


def test_the_lap_is_the_slowest_car_still_racing():
    session = _Session({1: 10, 2: 9, 3: 7}, retired=set())

    assert field_lap(session) == 7


def test_a_field_that_has_all_stopped_reports_nothing_rather_than_raising():
    session = _Session({1: 4, 2: 4}, retired={1, 2})

    assert field_lap(session) == 0


# -- the order ----------------------------------------------------------------


def test_the_order_is_laps_first_then_time_at_the_line():
    """Car 2 is quicker but a lap down, and a lap beats a second."""
    session = _Session({1: 10, 2: 9, 3: 10}, retired=set(), pace={2: -5.0, 3: 1.0})

    live = build_live(session, LABELS, lap=9, laps=14)

    assert [row["car_number"] for row in live["order"]] == [1, 3, 2]
    assert live["order"][2]["gap"] == "+1L"


def test_the_gap_is_the_time_the_lap_record_carries():
    """Not a distance interpolated between two lines -- which is the reading
    the standing start makes wrong."""
    session = _Session({1: 5, 2: 5}, retired=set(), pace={2: 0.4})

    live = build_live(session, LABELS, lap=5, laps=14)

    assert live["order"][0]["gap"] == "+0.000"
    assert live["order"][1]["gap"] == "+2.000", "0.4s a lap over five laps"
    assert live["order"][1]["interval"] == "+2.000"
    assert live["leader_elapsed"] == 450.0


def test_the_interval_is_to_the_car_ahead_not_to_the_leader():
    session = _Session({1: 4, 2: 4, 3: 4}, retired=set(), pace={2: 0.5, 3: 1.0})

    live = build_live(session, LABELS, lap=4, laps=14)

    assert [row["gap"] for row in live["order"]] == ["+0.000", "+2.000", "+4.000"]
    assert [row["interval"] for row in live["order"]] == ["—", "+2.000", "+2.000"]


def test_the_screen_names_the_drivers_and_marks_the_player():
    live = build_live(_Session({1: 10, 2: 9, 3: 2}, retired={3}), LABELS, lap=9, laps=14)

    assert live["lap"] == 9 and live["laps"] == 14
    assert [row["driver"] for row in live["order"]][:2] == ["Ravi Tanaka", "Leon Salgado"]
    assert live["order"][0]["is_player"] is True


def test_a_stopped_car_drops_out_of_the_order_rather_than_holding_a_place():
    live = build_live(_Session({1: 10, 2: 9, 3: 2}, retired={3}), LABELS, lap=9, laps=14)

    running = [row for row in live["order"] if not row["retired"]]
    stopped = [row for row in live["order"] if row["retired"]]

    assert [row["position"] for row in running] == [1, 2]
    assert [row["car_number"] for row in stopped] == [3]
    assert stopped[0]["position"] is None
    assert live["retired"] == 1
    assert live["order"][-1]["retired"], "a car that is out belongs at the bottom"


def test_a_stopped_car_does_not_become_the_car_a_gap_is_measured_to():
    """Car 3 parked on lap 2 with the shortest elapsed time of anybody.  It is
    not leading, and nobody's interval is to it."""
    session = _Session({1: 10, 2: 10, 3: 2}, retired={3})

    live = build_live(session, LABELS, lap=10, laps=14)

    assert live["order"][0]["car_number"] == 1
    assert live["order"][1]["interval"] == "+0.000", "measured to car 1, not to car 3"


def test_a_race_everybody_retired_from_still_shows_where_it_got_to():
    live = build_live(_Session({1: 6, 2: 4}, retired={1, 2}), LABELS, lap=4, laps=14)

    assert len(live["order"]) == 2 and live["retired"] == 2
    assert all(row["position"] is None for row in live["order"])


def test_an_unknown_car_still_gets_a_row():
    """A label that is missing is a naming problem, not a reason to lose a car."""
    live = build_live(_Session({1: 3, 9: 3}, retired=set()), LABELS, lap=3, laps=5)

    assert {row["car_number"] for row in live["order"]} == {1, 9}
    assert [row for row in live["order"] if row["car_number"] == 9][0]["driver"] == "9"


# -- qualifying ---------------------------------------------------------------


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
