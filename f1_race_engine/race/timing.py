"""Timing: where everyone is, and how far apart (project rule 28).

    "포지션과 갭은 실제 거리와 시간에서 계산되어야 한다."

So a gap is never an index into a sorted list and never a running total of lap
time differences.  It is the answer to one question:

    *how long ago was the car ahead standing where this car is now?*

which needs two things -- a distance for every car at a moment in time, and a
time for every car at a point on the road -- and this module keeps exactly
that.  Every car's progress is stored as a strictly increasing table of
``(elapsed, distance)`` samples taken at each sector crossing, so both
questions are answered by interpolating the same table in opposite directions.

That definition gives the behaviour real timing has and a simpler one does not:

* a car that is lapped is not "60 seconds behind", it is a lap down, and the
  same query says so;
* the interval between two cars is not the difference of their lap times, it is
  the difference of the times they passed the same point;
* asking mid-lap works exactly as well as asking at the line.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from typing import Any

from ..core.units import Seconds, format_lap_time
from ..core.errors import RaceError

__all__ = ["Gap", "LapRecord", "Position", "TimingTower"]


@dataclass(frozen=True)
class LapRecord:
    """One car's completed lap, timed against the session clock."""

    car_number: int
    lap: int
    lap_time: Seconds
    elapsed: Seconds
    """Session time when the car crossed the line to complete this lap."""

    distance: float
    """Total distance covered at that moment, m."""

    sector_times: tuple[Seconds, ...] = ()
    compound: str = ""
    tyre_wear: float = 0.0
    fuel_mass: float = 0.0
    energy_remaining: float = 0.0
    mistakes: int = 0
    pitted: bool = False

    @property
    def formatted(self) -> str:
        return format_lap_time(self.lap_time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "car_number": self.car_number,
            "lap": self.lap,
            "lap_time": self.lap_time,
            "lap_time_formatted": self.formatted,
            "elapsed": self.elapsed,
            "distance": self.distance,
            "sector_times": list(self.sector_times),
            "compound": self.compound,
            "tyre_wear": self.tyre_wear,
            "fuel_mass": self.fuel_mass,
            "energy_remaining": self.energy_remaining,
            "mistakes": self.mistakes,
            "pitted": self.pitted,
        }


@dataclass(frozen=True)
class Gap:
    """The distance between two cars, expressed the way timing expresses it."""

    seconds: Seconds
    laps: int = 0
    """Whole laps down.  Non-zero means ``seconds`` is not the useful figure."""

    @property
    def is_lapped(self) -> bool:
        return self.laps > 0

    @property
    def formatted(self) -> str:
        if self.laps == 1:
            return "+1 lap"
        if self.laps > 1:
            return f"+{self.laps} laps"
        return f"+{self.seconds:.3f}"

    def __str__(self) -> str:  # pragma: no cover - display helper
        return self.formatted


@dataclass(frozen=True)
class Position:
    """One row of the timing screen."""

    position: int
    car_number: int
    distance: float
    laps_completed: int
    elapsed: Seconds
    gap_to_leader: Gap
    interval: Gap
    """To the car directly ahead."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "position": self.position,
            "car_number": self.car_number,
            "distance": self.distance,
            "laps_completed": self.laps_completed,
            "elapsed": self.elapsed,
            "gap_to_leader": self.gap_to_leader.formatted,
            "gap_to_leader_seconds": self.gap_to_leader.seconds,
            "gap_to_leader_laps": self.gap_to_leader.laps,
            "interval": self.interval.formatted,
        }


class TimingTower:
    """Every car's progress, and the questions you can ask of it."""

    __slots__ = ("lap_length", "_records", "_times", "_distances")

    def __init__(self, lap_length: float) -> None:
        if lap_length <= 0.0:
            raise RaceError("lap_length must be positive")
        self.lap_length = lap_length
        self._records: dict[int, list[LapRecord]] = {}
        # Progress tables, one per car: strictly increasing and index-aligned.
        self._times: dict[int, list[float]] = {}
        self._distances: dict[int, list[float]] = {}

    # -- filling it in -------------------------------------------------------

    def start(self, car_number: int, *, elapsed: float = 0.0) -> None:
        """Put a car on the track at the line."""
        self._records.setdefault(car_number, [])
        self._times[car_number] = [elapsed]
        self._distances[car_number] = [0.0]

    def record(self, record: LapRecord, *, sector_lengths: tuple[float, ...] = ()) -> None:
        """Log a completed lap.

        ``sector_lengths`` adds intermediate samples so gaps can be resolved
        mid-lap rather than only at the line.  Without them the table still
        works; it is just coarser.
        """
        car = record.car_number
        if car not in self._times:
            self.start(car)
        self._records[car].append(record)

        times, distances = self._times[car], self._distances[car]
        start_time = times[-1]
        start_distance = distances[-1]
        if record.sector_times and sector_lengths and len(sector_lengths) == len(
            record.sector_times
        ):
            elapsed = start_time
            covered = start_distance
            for duration, length in zip(record.sector_times[:-1], sector_lengths[:-1]):
                elapsed += duration
                covered += length
                times.append(elapsed)
                distances.append(covered)
        times.append(record.elapsed)
        distances.append(record.distance)

    # -- asking questions of it ----------------------------------------------

    def records(self, car_number: int) -> tuple[LapRecord, ...]:
        return tuple(self._records.get(car_number, ()))

    @property
    def cars(self) -> tuple[int, ...]:
        return tuple(sorted(self._times))

    def laps_completed(self, car_number: int) -> int:
        return len(self._records.get(car_number, ()))

    def laps_completed_at(self, car_number: int, time: Seconds) -> int:
        """Laps this car had finished by session time ``time``."""
        records = self._records.get(car_number, ())
        return sum(1 for record in records if record.elapsed <= time)

    def distance_at(self, car_number: int, time: Seconds) -> float:
        """How far this car had gone at session time ``time``, m."""
        times = self._times[car_number]
        distances = self._distances[car_number]
        if time <= times[0]:
            return distances[0]
        if time >= times[-1]:
            return distances[-1]
        index = bisect.bisect_right(times, time)
        return _interpolate(
            time, times[index - 1], times[index], distances[index - 1], distances[index]
        )

    def time_at(self, car_number: int, distance: float) -> float | None:
        """When this car reached ``distance``, or ``None`` if it never did.

        The other half of rule 28: a gap is a *time* difference measured at one
        *place*, so somebody has to be able to answer this.
        """
        times = self._times[car_number]
        distances = self._distances[car_number]
        if distance <= distances[0]:
            return times[0]
        if distance > distances[-1]:
            return None
        index = bisect.bisect_left(distances, distance)
        if index == 0:
            return times[0]
        return _interpolate(
            distance, distances[index - 1], distances[index], times[index - 1], times[index]
        )

    def gap(self, car_number: int, ahead: int, time: Seconds) -> Gap:
        """How far ``car_number`` is behind ``ahead`` at session time ``time``.

        Measured where the trailing car actually is: the time the car ahead
        passed that point, subtracted from now.  When that point is more than a
        lap back the answer is reported in laps, because seconds stop meaning
        anything once a car has been passed by the leader.
        """
        if car_number == ahead:
            return Gap(0.0)
        here = self.distance_at(car_number, time)
        there = self.distance_at(ahead, time)
        behind = there - here
        if behind <= 0.0:
            return Gap(0.0)

        laps_down = int(behind // self.lap_length)
        if laps_down >= 1:
            return Gap(seconds=0.0, laps=laps_down)

        passed = self.time_at(ahead, here)
        if passed is None:
            return Gap(seconds=0.0, laps=1)
        return Gap(seconds=max(time - passed, 0.0))

    def gap_at(self, car_number: int, ahead: int, distance: float) -> Gap:
        """How much later ``car_number`` reached ``distance`` than ``ahead``.

        The other way to measure a gap, and the one a classification uses: same
        place, two times, rather than same time, two places.  At the chequered
        flag it is the difference between two cars crossing the same line --
        which is what a result sheet prints -- and it is exact, because both
        times are recorded rather than interpolated.
        """
        if car_number == ahead:
            return Gap(0.0)
        theirs = self.time_at(ahead, distance)
        if theirs is None:
            return Gap(0.0)
        mine = self.time_at(car_number, distance)
        if mine is None:
            # Never got there: how far short, in laps.
            short = distance - self._distances[car_number][-1]
            laps = max(int(-(-short // self.lap_length)), 1)
            return Gap(seconds=0.0, laps=laps)
        return Gap(seconds=max(mine - theirs, 0.0))

    def order_at(self, time: Seconds) -> tuple[int, ...]:
        """Car numbers, leader first, by distance covered at ``time``."""
        return tuple(
            sorted(
                self._times,
                key=lambda car: (-self.distance_at(car, time), car),
            )
        )

    def snapshot_at(self, time: Seconds) -> tuple[Position, ...]:
        """The whole timing screen at one moment."""
        order = self.order_at(time)
        rows: list[Position] = []
        for index, car in enumerate(order):
            leader = order[0]
            ahead = order[index - 1] if index else car
            rows.append(
                Position(
                    position=index + 1,
                    car_number=car,
                    distance=self.distance_at(car, time),
                    laps_completed=self.laps_completed_at(car, time),
                    elapsed=time,
                    gap_to_leader=self.gap(car, leader, time),
                    interval=self.gap(car, ahead, time),
                )
            )
        return tuple(rows)

    def fastest_lap(self) -> LapRecord | None:
        best: LapRecord | None = None
        for records in self._records.values():
            for record in records:
                if best is None or record.lap_time < best.lap_time:
                    best = record
        return best

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"TimingTower({len(self._times)} cars, lap {self.lap_length:.0f} m)"


def _interpolate(x: float, x0: float, x1: float, y0: float, y1: float) -> float:
    span = x1 - x0
    if span <= 0.0:
        return y1
    return y0 + (y1 - y0) * (x - x0) / span
