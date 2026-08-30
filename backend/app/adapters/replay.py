"""A finished race, as something that can be played back.

Built from the engine's own timing tower rather than from a summary of it.  The
tower can answer "how far had car 7 covered at 412 seconds", so the replay is
that question asked at regular intervals -- which means the car on the screen is
where the simulation actually had it, not where an interpolation between lap
times guesses it was.

Sampled once, when the race finishes, and stored with the result.  The
alternative is keeping the tower alive and querying it per frame, which would
tie a replay to the process that ran the race and make a saved game unable to
show its own history.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from f1_race_engine.race import RaceResult

__all__ = ["Replay", "build_replay"]

#: Seconds of race time between samples.
#:
#: At two seconds a car covers sixty to a hundred and fifty metres, which on a
#: five-kilometre lap is under three per cent of it -- fine enough that a car
#: moves smoothly round a plan view, coarse enough that a two-hour race is a
#: few thousand numbers rather than a few hundred thousand.
SAMPLE_SECONDS = 2.0


@dataclass(frozen=True, slots=True)
class Replay:
    """Where every car was, every couple of seconds."""

    race_id: str
    track: str
    lap_length: float
    laps: int
    duration: float
    interval: float
    cars: tuple[dict[str, Any], ...]
    events: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "race_id": self.race_id,
            "track": self.track,
            "lap_length": round(self.lap_length, 2),
            "laps": self.laps,
            "duration": round(self.duration, 2),
            "interval": self.interval,
            "cars": list(self.cars),
            "events": list(self.events),
        }


def build_replay(
    result: RaceResult,
    *,
    race_id: str,
    lap_length: float,
    labels: dict[int, dict[str, str]],
    interval: float = SAMPLE_SECONDS,
) -> Replay:
    """Sample the race into a track that can be played back.

    ``labels`` maps a car number to its driver and team ids, because the engine
    knows car numbers and the game knows who was in them.
    """
    timing = result.timing
    numbers = list(timing.cars)
    if not numbers:
        return Replay(
            race_id=race_id,
            track=result.track_name,
            lap_length=lap_length,
            laps=result.laps,
            duration=0.0,
            interval=interval,
            cars=(),
            events=(),
        )

    duration = max(timing.recorded_until(car) for car in numbers)
    steps = int(duration // interval) + 1

    retired_at = {
        row.car_number: row for row in result.classification if row.retired
    }

    cars: list[dict[str, Any]] = []
    for car in numbers:
        until = timing.recorded_until(car)
        distances: list[float] = []
        for step in range(steps):
            moment = step * interval
            # Past the point a car stopped, it stays where it stopped -- which
            # is the truth about a retirement and is also what a viewer expects
            # to see rather than a car that vanishes.
            distances.append(round(timing.distance_at(car, min(moment, until)), 1))
        label = labels.get(car, {})
        cars.append(
            {
                "car_number": car,
                "driver": label.get("driver", str(car)),
                "team": label.get("team", ""),
                "driver_name": label.get("driver_name", str(car)),
                "team_name": label.get("team_name", ""),
                "distances": distances,
                "stopped_at": round(until, 2) if car in retired_at else None,
                "retired": car in retired_at,
            }
        )

    events: list[dict[str, Any]] = []
    for incident in result.incidents:
        payload = incident.to_dict()
        events.append(
            {
                "kind": "incident",
                "lap": payload.get("lap"),
                "car_number": payload.get("car_number"),
                "detail": payload.get("description") or payload.get("kind"),
            }
        )
    for lap, flag, reason in result.flags:
        events.append({"kind": "flag", "lap": lap, "flag": flag, "detail": reason})
    for move in result.overtakes:
        payload = move.to_dict()
        events.append(
            {
                "kind": "overtake",
                "lap": payload.get("lap"),
                "car_number": payload.get("car_number"),
                "passed": payload.get("passed"),
                "detail": payload.get("where") or "",
            }
        )
    events.sort(key=lambda item: (item.get("lap") or 0))

    return Replay(
        race_id=race_id,
        track=result.track_name,
        lap_length=lap_length,
        laps=result.laps,
        duration=duration,
        interval=interval,
        cars=tuple(cars),
        events=tuple(events),
    )


def positions_at(replay_cars: Sequence[dict[str, Any]], step: int) -> list[dict[str, Any]]:
    """The running order at one sample, for a client that wants it computed here.

    Kept because "who is leading" is a question about total distance covered,
    and getting it wrong -- sorting on distance round the lap rather than
    distance overall -- puts a car that has just crossed the line last.
    """
    rows = []
    for car in replay_cars:
        distances = car["distances"]
        if step >= len(distances):
            continue
        rows.append({"car_number": car["car_number"], "distance": distances[step]})
    rows.sort(key=lambda row: -row["distance"])
    for index, row in enumerate(rows, start=1):
        row["position"] = index
    return rows
