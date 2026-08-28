"""Timing (project rule 28).

    "포지션과 갭은 실제 거리와 시간에서 계산되어야 한다."

These tests drive the tower directly with made-up laps, so what is under test
is the timing definition itself rather than anything the physics produced.
"""

from __future__ import annotations

import pytest

from f1_race_engine.core.errors import RaceError
from f1_race_engine.race import Gap, LapRecord, TimingTower

LAP = 5000.0
SECTORS = (1500.0, 2000.0, 1500.0)


def _tower(*laps_per_car: tuple[int, list[float]]) -> TimingTower:
    """Build a tower from ``(car_number, [lap times])`` pairs."""
    tower = TimingTower(LAP)
    for car, times in laps_per_car:
        tower.start(car)
        elapsed = 0.0
        for lap, lap_time in enumerate(times, start=1):
            elapsed += lap_time
            share = tuple(lap_time * length / LAP for length in SECTORS)
            tower.record(
                LapRecord(
                    car_number=car, lap=lap, lap_time=lap_time,
                    elapsed=elapsed, distance=lap * LAP, sector_times=share,
                ),
                sector_lengths=SECTORS,
            )
    return tower


# -- the progress table ------------------------------------------------------


def test_distance_and_time_invert_each_other():
    tower = _tower((1, [90.0, 90.0, 90.0]))
    for distance in (0.0, 1200.0, 5000.0, 7777.0, 15000.0):
        time = tower.time_at(1, distance)
        assert tower.distance_at(1, time) == pytest.approx(distance, rel=1e-9, abs=1e-6)


def test_a_car_that_never_got_there_has_no_time():
    tower = _tower((1, [90.0]))
    assert tower.time_at(1, 4000.0) is not None
    assert tower.time_at(1, 6000.0) is None


def test_distance_is_clamped_outside_the_race():
    tower = _tower((1, [90.0, 90.0]))
    assert tower.distance_at(1, -10.0) == 0.0
    assert tower.distance_at(1, 10_000.0) == pytest.approx(2 * LAP)


def test_a_lap_length_must_be_real():
    with pytest.raises(RaceError):
        TimingTower(0.0)


# -- gaps --------------------------------------------------------------------


def test_a_gap_is_when_the_car_ahead_passed_this_point():
    """The definition, tested against a case with an arithmetic answer: two
    cars at constant speed, one 5 s a lap quicker."""
    tower = _tower((1, [90.0] * 3), (2, [95.0] * 3))
    # At t=190 the chaser has just finished its second lap.  The leader passed
    # that same point at t=180, so the gap is ten seconds -- and it is derived
    # from where the chaser is, not from the difference of two lap times.
    gap = tower.gap(2, 1, time=190.0)
    assert gap.seconds == pytest.approx(10.0, rel=1e-6)
    assert not gap.is_lapped


def test_a_gap_at_the_line_is_the_difference_of_two_crossings():
    tower = _tower((1, [90.0, 90.0]), (2, [95.0, 95.0]))
    assert tower.gap_at(2, 1, 2 * LAP).seconds == pytest.approx(10.0)


def test_the_leader_has_no_gap():
    tower = _tower((1, [90.0]), (2, [95.0]))
    assert tower.gap(1, 1, time=90.0).seconds == 0.0
    assert tower.gap(1, 2, time=90.0).seconds == 0.0


def test_a_lapped_car_is_reported_in_laps_not_seconds():
    """Seconds stop meaning anything once a car has been passed by the
    leader, and the tower says so rather than printing a large number."""
    tower = _tower((1, [60.0] * 12), (2, [80.0] * 12))
    # At t=480 the leader has done eight laps and the chaser six.
    gap = tower.gap(2, 1, time=480.0)
    assert gap.is_lapped
    assert gap.laps == 2
    assert gap.formatted == "+2 laps"


def test_exactly_one_lap_down_says_one_lap():
    tower = _tower((1, [60.0] * 12), (2, [80.0] * 12))
    # At t=240 the leader has done four laps and the chaser three.
    gap = tower.gap(2, 1, time=240.0)
    assert gap.laps == 1
    assert gap.formatted == "+1 lap"


def test_a_car_short_of_the_line_is_laps_down_there_too():
    tower = _tower((1, [60.0] * 4), (2, [90.0] * 2))
    assert tower.gap_at(2, 1, 4 * LAP).laps == 2


def test_gap_formatting():
    assert Gap(1.234).formatted == "+1.234"
    assert Gap(0.0, laps=1).formatted == "+1 lap"
    assert Gap(0.0, laps=3).formatted == "+3 laps"


# -- the timing screen -------------------------------------------------------


def test_the_order_is_by_distance_covered():
    tower = _tower((1, [90.0, 90.0]), (2, [88.0, 88.0]), (3, [95.0, 95.0]))
    assert tower.order_at(176.0)[0] == 2
    assert tower.order_at(176.0)[-1] == 3


def test_the_order_can_change_during_the_race():
    """Car 2 starts slowly and finishes quickly; nothing sorts by total time."""
    tower = _tower((1, [90.0, 90.0, 90.0]), (2, [100.0, 85.0, 80.0]))
    assert tower.order_at(100.0)[0] == 1
    assert tower.order_at(265.0)[0] == 2


def test_gaps_measured_at_one_point_telescope_exactly():
    """Three cars, one line: whatever the third is behind the second, plus
    whatever the second is behind the first, is what the third is behind the
    first.  Exact, because all three crossed the same place."""
    tower = _tower((1, [88.0] * 3), (2, [90.0] * 3), (3, [92.0] * 3))
    line = 3 * LAP
    assert tower.gap_at(3, 1, line).seconds == pytest.approx(
        tower.gap_at(3, 2, line).seconds + tower.gap_at(2, 1, line).seconds
    )


def test_the_screen_orders_gaps_the_way_it_orders_cars():
    """Intervals measured live are each taken where their own car is, so they
    do not telescope to the last decimal -- but the field is still in order,
    and each interval is close to the difference of the two gaps."""
    tower = _tower((1, [88.0] * 3), (2, [90.0] * 3), (3, [92.0] * 3))
    rows = tower.snapshot_at(264.0)
    gaps = [row.gap_to_leader.seconds for row in rows]
    assert gaps == sorted(gaps)
    running = 0.0
    for row in rows[1:]:
        running += row.interval.seconds
        assert row.gap_to_leader.seconds == pytest.approx(running, rel=0.05)


def test_a_snapshot_positions_everybody():
    tower = _tower((1, [88.0] * 3), (2, [90.0] * 3), (7, [92.0] * 3))
    rows = tower.snapshot_at(264.0)
    assert [row.position for row in rows] == [1, 2, 3]
    assert [row.car_number for row in rows] == [1, 2, 7]
    assert rows[0].gap_to_leader.seconds == 0.0


def test_the_fastest_lap_is_the_fastest_lap():
    tower = _tower((1, [90.0, 89.0]), (2, [88.5, 91.0]))
    best = tower.fastest_lap()
    assert best.car_number == 2 and best.lap == 1


def test_records_are_kept_per_car():
    tower = _tower((1, [90.0, 90.0]), (2, [95.0]))
    assert tower.laps_completed(1) == 2
    assert tower.laps_completed(2) == 1
    assert tower.cars == (1, 2)


def test_a_record_serialises():
    tower = _tower((1, [90.0]))
    payload = tower.records(1)[0].to_dict()
    assert payload["lap"] == 1
    assert payload["lap_time_formatted"].endswith("30.000")


def test_coarse_recording_still_works():
    """Sector samples are an accuracy improvement, not a requirement."""
    tower = TimingTower(LAP)
    tower.start(1)
    tower.record(LapRecord(car_number=1, lap=1, lap_time=90.0, elapsed=90.0,
                           distance=LAP))
    assert tower.distance_at(1, 45.0) == pytest.approx(0.5 * LAP)
