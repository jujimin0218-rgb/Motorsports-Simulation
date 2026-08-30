"""The stewards.

A penalty is the one thing on Phase 6's list the race engine genuinely does not
have, and it is right that it does not: the engine's job is to say what
happened on the road, and whether what happened was somebody's *fault* is a
regulation rather than a force balance.  So the engine reports the contact and
this decides what it costs.

Three things earn one here, and each is derived from something the engine
actually produced rather than invented on top of it:

**Causing a collision.**  The engine records a collision with the car at fault
and the cars involved.  Contact that damaged somebody else is a penalty;
contact that damaged nobody is a racing incident.  That is a rule a player can
learn, which is worth more than a coin toss that is occasionally "realistic".

**Track limits.**  The engine counts a driver's mistakes over a race.  Past a
threshold those are warnings, and past the warnings they are five seconds --
which is the real regulation and, more to the point, gives the commitment model
underneath a consequence it did not have.

Two things about that threshold, and both were got wrong first.  It is a
**rate**, not a count, because this game runs races at anything from a quarter
distance to a full one and the same driving has to earn the same penalty at
either.  And only a *share* of a driver's mistakes are track-limits offences:
the engine counts every error -- a lock-up, a snap, a moment -- and most of them
do not put the car beyond the white line.  Both numbers come from measuring
what the engine actually produces (0.146 mistakes per driver per lap across a
field), set so that one or two drivers in a race are penalised and a couple more
are warned, which is what a real Sunday looks like.

**Power-unit changes.**  A season allows a car so many engines.  The engine
model already retires cars with power-unit failures; counting them across the
season and charging a grid drop for the ones beyond the allowance is what makes
reliability a season-long resource rather than a bad afternoon.

Nothing here is random.  A steward who is unpredictable is a steward the player
cannot plan around, and the point of a rule is that it can be planned around.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Sequence

__all__ = [
    "ENGINE_ALLOWANCE",
    "REFERENCE_LAPS",
    "Penalty",
    "PenaltyKind",
    "apply_time_penalties",
    "grid_drop_for",
    "steward",
    "track_limit_offences",
]


class PenaltyKind(str, Enum):
    TIME = "time"
    """Seconds added at the flag.  Can change a result and often does."""

    GRID = "grid"
    """Places dropped at the start of the next round."""

    REPRIMAND = "reprimand"
    """No cost today.  Kept because the next one is not free."""


#: Seconds for causing contact, by what it cost the other car.
COLLISION_SECONDS = {"damage": 5.0, "retirement": 10.0}

#: A full grand prix, in laps.  Mistakes are normalised to it so that the same
#: driving earns the same penalty whether the game is running quarter-distance
#: races or full ones.
REFERENCE_LAPS = 57

#: What share of a driver's errors put the car beyond the white line.  The
#: engine counts every moment; most of them are a lock-up or a snap and stay on
#: the road.
TRACK_LIMITS_SHARE = 0.25

#: Three warnings, then five seconds, then five more for every three after
#: that.  The real rule, applied to the normalised count above.
TRACK_LIMITS_FREE = 3
TRACK_LIMITS_PER_PENALTY = 3
TRACK_LIMITS_SECONDS = 5.0

#: Power units a car may use in a season before the grid drops start.
ENGINE_ALLOWANCE = 4

#: Places dropped for the first power unit over the allowance, and for each
#: one after that.  The real regulation escalates and so does this.
FIRST_ENGINE_DROP = 10
FURTHER_ENGINE_DROP = 5


@dataclass(frozen=True, slots=True)
class Penalty:
    """One stewards' decision."""

    round_number: int
    driver_id: str
    team_id: str
    kind: PenaltyKind
    reason: str
    seconds: float = 0.0
    places: int = 0
    lap: int | None = None
    served: bool = False
    """Grid penalties are carried to the next round and marked when taken."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "round": self.round_number,
            "driver": self.driver_id,
            "team": self.team_id,
            "kind": self.kind.value,
            "reason": self.reason,
            "seconds": self.seconds,
            "places": self.places,
            "lap": self.lap,
            "served": self.served,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Penalty:
        return cls(
            round_number=int(data["round"]),
            driver_id=str(data["driver"]),
            team_id=str(data["team"]),
            kind=PenaltyKind(data["kind"]),
            reason=str(data.get("reason", "")),
            seconds=float(data.get("seconds", 0.0)),
            places=int(data.get("places", 0)),
            lap=data.get("lap"),
            served=bool(data.get("served", False)),
        )

    @property
    def headline(self) -> str:
        if self.kind is PenaltyKind.TIME:
            return f"{self.seconds:.0f}s penalty"
        if self.kind is PenaltyKind.GRID:
            return f"{self.places}-place grid drop"
        return "reprimand"


def track_limit_offences(mistakes: int, laps: int) -> float:
    """A driver's mistakes as track-limits offences over a full grand prix.

    Normalised by distance and reduced to the share that actually put the car
    off the road -- see the module docstring for why both.
    """
    if laps <= 0:
        return 0.0
    return mistakes * (REFERENCE_LAPS / laps) * TRACK_LIMITS_SHARE


def steward(
    *,
    round_number: int,
    incidents: Iterable[Any],
    classification: Iterable[Any],
    labels: dict[int, tuple[str, str]],
    engines_used: dict[str, int],
    laps: int = REFERENCE_LAPS,
) -> list[Penalty]:
    """Look at what happened and decide what it costs.

    ``labels`` maps a car number to ``(driver id, team id)``; the engine knows
    car numbers and the game knows who was in them.  ``engines_used`` is how
    many power units each car has been through this season *including* this
    race, so the allowance can be checked.  ``laps`` is how long the race
    actually was, so track limits are judged on a rate rather than a count.
    """
    penalties: list[Penalty] = []

    for incident in incidents:
        payload = incident.to_dict() if hasattr(incident, "to_dict") else dict(incident)
        who = labels.get(payload.get("car_number"))
        if who is None:
            continue
        driver_id, team_id = who

        if payload.get("kind") == "collision" and payload.get("involved"):
            severity = payload.get("severity", "")
            seconds = COLLISION_SECONDS.get(severity)
            if seconds is None:
                # Contact that cost the other car nothing is a racing incident,
                # which is the correct answer far more often than a penalty is.
                continue
            others = ", ".join(f"car {n}" for n in payload["involved"])
            penalties.append(
                Penalty(
                    round_number=round_number,
                    driver_id=driver_id,
                    team_id=team_id,
                    kind=PenaltyKind.TIME,
                    seconds=seconds,
                    reason=f"causing a collision with {others}",
                    lap=payload.get("lap"),
                )
            )

    for row in classification:
        who = labels.get(row.car_number)
        if who is None:
            continue
        driver_id, team_id = who
        offences = track_limit_offences(row.mistakes, laps)
        beyond = offences - TRACK_LIMITS_FREE
        if beyond >= TRACK_LIMITS_PER_PENALTY:
            times = int(beyond // TRACK_LIMITS_PER_PENALTY)
            penalties.append(
                Penalty(
                    round_number=round_number,
                    driver_id=driver_id,
                    team_id=team_id,
                    kind=PenaltyKind.TIME,
                    seconds=TRACK_LIMITS_SECONDS * times,
                    reason=f"track limits ({offences:.0f} offences)",
                )
            )
        elif beyond > 0:
            penalties.append(
                Penalty(
                    round_number=round_number,
                    driver_id=driver_id,
                    team_id=team_id,
                    kind=PenaltyKind.REPRIMAND,
                    reason=f"track limits warning ({offences:.0f} offences)",
                )
            )

    for driver_id, used in engines_used.items():
        drop = grid_drop_for(used)
        if drop:
            team_id = next(
                (t for (d, t) in labels.values() if d == driver_id),
                "",
            )
            penalties.append(
                Penalty(
                    round_number=round_number,
                    driver_id=driver_id,
                    team_id=team_id,
                    kind=PenaltyKind.GRID,
                    places=drop,
                    reason=f"power unit {used} of a {ENGINE_ALLOWANCE}-unit allowance",
                )
            )

    return penalties


def grid_drop_for(engines_used: int) -> int:
    """Places lost for having used this many power units.

    Zero inside the allowance; the first one over is expensive and the ones
    after it are merely painful, which is what the real escalation does.
    """
    over = engines_used - ENGINE_ALLOWANCE
    if over <= 0:
        return 0
    return FIRST_ENGINE_DROP + FURTHER_ENGINE_DROP * (over - 1)


def apply_time_penalties(
    classification: Sequence[Any],
    penalties: Iterable[Penalty],
    labels: dict[int, tuple[str, str]],
) -> list[tuple[int, int]]:
    """Re-order a classification for time penalties, and say what moved.

    Returns ``(car number, new position)`` pairs.

    Two things this is careful about, and both are the regulation rather than
    convenience.  A penalty is added to a car's race time and the order is then
    re-taken -- so five seconds only costs a place if somebody was within five
    seconds, which is the whole reason a penalised driver spends the last laps
    trying to build a gap.  And a car that retired is not re-ordered by it: it
    is classified where it stopped, and adding seconds to a car that is not
    running means nothing.
    """
    seconds_for: dict[str, float] = {}
    for penalty in penalties:
        if penalty.kind is PenaltyKind.TIME:
            seconds_for[penalty.driver_id] = (
                seconds_for.get(penalty.driver_id, 0.0) + penalty.seconds
            )
    if not seconds_for:
        return [(row.car_number, row.position) for row in classification]

    running = []
    retired = []
    for row in classification:
        who = labels.get(row.car_number)
        driver_id = who[0] if who else None
        if row.retired:
            retired.append(row)
        else:
            running.append(
                (
                    row.laps_completed,
                    row.total_time + seconds_for.get(driver_id or "", 0.0),
                    row,
                )
            )

    # More laps first, then less time -- which is how a classification is
    # ordered and is not the same as ordering on time alone.
    running.sort(key=lambda item: (-item[0], item[1]))

    order: list[tuple[int, int]] = []
    position = 1
    for _, _, row in running:
        order.append((row.car_number, position))
        position += 1
    for row in retired:
        order.append((row.car_number, position))
        position += 1
    return order
