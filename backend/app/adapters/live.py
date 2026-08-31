"""A race, while it is still running.

The companion to :mod:`replay`, which is a race after it has finished.  Both
read the engine's own timing tower rather than a summary of it; the difference
is only that this one is asked mid-session, so the tower it reads is still
being written to.

A grand prix is minutes of simulation and the interesting part is the middle.
A progress bar can say how far through it is and nothing else, which is the
same picture whether the player's car is leading or three laps down.  This is
what turns that wait into the race itself: the order, the gaps, and the lap
they are on, taken straight off the tower every time the field completes a lap.

Nothing here changes the session.  It reads.
"""

from __future__ import annotations

from typing import Any

__all__ = ["build_live", "build_live_qualifying", "field_lap"]


def build_live_qualifying(
    session: Any,
    labels: dict[int, dict[str, Any]],
    *,
    segment: str,
    done: int,
    total: int,
    complete: bool,
) -> dict[str, Any]:
    """The qualifying board as it stands.

    Built from the laps the session has actually recorded, so it can be asked
    for in the middle of a segment as well as at the end of one -- a car that
    has not been out yet is shown as having no time rather than as slowest.
    ``complete`` is the difference between "Q1 is running" and "Q1 is over",
    which is the difference between a board that will change and a result.
    """
    best: dict[int, Any] = {}
    for lap in session.laps:
        if lap.car_number not in best or lap.lap_time < best[lap.car_number].lap_time:
            best[lap.car_number] = lap

    ranked = sorted(best.values(), key=lambda lap: lap.lap_time)
    pole = ranked[0].lap_time if ranked else None

    order: list[dict[str, Any]] = []
    for position, lap in enumerate(ranked, start=1):
        label = labels.get(lap.car_number, {})
        order.append(
            {
                "position": position,
                "car_number": lap.car_number,
                "driver": label.get("driver") or str(lap.car_number),
                "team": label.get("team") or "",
                "is_player": bool(label.get("is_player")),
                "best": round(lap.lap_time, 3),
                "gap": 0.0 if pole is None else round(lap.lap_time - pole, 3),
                "segment": lap.segment,
            }
        )

    waiting = [
        {
            "car_number": entry.car_number,
            "driver": (labels.get(entry.car_number) or {}).get("driver")
            or str(entry.car_number),
            "team": (labels.get(entry.car_number) or {}).get("team") or "",
            "is_player": bool((labels.get(entry.car_number) or {}).get("is_player")),
            "best": None,
            "gap": None,
            "segment": None,
            "position": None,
        }
        for entry in session.entries
        if entry.car_number not in best
    ]

    return {
        "segment": segment,
        "done": done,
        "total": total,
        "complete": complete,
        "order": order + waiting,
    }


def field_lap(session: Any) -> int:
    """How far the race has got: the lap the slowest car still in it is on.

    Only cars that are *still running* count.  A car that retires never reports
    another lap, so counting everything that started means the number stops
    moving at the first retirement and stays there for the rest of the grand
    prix -- a progress bar parked at 14% for four minutes.
    """
    running = [entry.car_number for entry in session.entries if entry.running]
    return min((session.timing.laps_completed(car) for car in running), default=0)


def build_live(
    session: Any,
    labels: dict[int, dict[str, Any]],
    *,
    lap: int,
    laps: int,
) -> dict[str, Any]:
    """The timing screen as it stands, for a client that is watching.

    ``labels`` maps a car number to its driver and team names, because the
    engine knows car numbers and the game knows who is in them -- the same
    split the replay adapter works either side of.
    """
    tower = session.timing
    running = {entry.car_number for entry in session.entries if entry.running}

    # Read the tower at the moment the leader completed this lap.  Only cars
    # still circulating can say when that was: a car that stopped on lap two
    # has its last record back there, and taking the earliest of *those* would
    # show the race as it stood when it retired rather than as it stands now.
    started = [car for car in tower.cars if tower.laps_completed(car) > 0]
    if not started:
        return {"lap": lap, "laps": laps, "order": [], "retired": 0}
    circulating = [car for car in started if car in running]
    at = (
        min(tower.recorded_until(car) for car in circulating)
        if circulating
        # Nobody left running: show where the race got to, not where it began.
        else max(tower.recorded_until(car) for car in started)
    )

    order: list[dict[str, Any]] = []
    out: list[dict[str, Any]] = []
    for row in tower.snapshot_at(at):
        label = labels.get(row.car_number, {})
        entry = {
            "car_number": row.car_number,
            "driver": label.get("driver") or str(row.car_number),
            "team": label.get("team") or "",
            "is_player": bool(label.get("is_player")),
            "laps_completed": row.laps_completed,
            "gap": row.gap_to_leader.formatted,
            "interval": row.interval.formatted,
            "retired": row.car_number not in running,
        }
        # A car that has stopped is not racing anybody, so it drops out of the
        # order rather than holding a position on the road it is parked beside.
        (out if entry["retired"] else order).append(entry)

    for position, entry in enumerate(order, start=1):
        entry["position"] = position
    for entry in out:
        entry["position"] = None

    fastest = tower.fastest_lap()
    return {
        "lap": lap,
        "laps": laps,
        "order": order + out,
        "retired": len(out),
        "leader_elapsed": round(at, 2),
        "fastest_lap": None
        if fastest is None
        else {
            "car_number": fastest.car_number,
            "driver": (labels.get(fastest.car_number) or {}).get("driver")
            or str(fastest.car_number),
            "lap_time": round(fastest.lap_time, 3),
            "lap": fastest.lap,
        },
    }
