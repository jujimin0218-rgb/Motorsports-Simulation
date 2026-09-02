"""What goes wrong, described once so everything can react to it.

Project rule 35: race events reach the race state through an event layer, not
through the physics.  An :class:`Incident` is that layer's currency -- a
mechanical failure, a collision and a spin are the same *kind* of thing to
everyone downstream, and they differ only in what caused them and how bad they
were.

The separation that matters is between **what happened** and **what race
control does about it**.  A car stopping is an incident; a safety car is a
decision.  Keeping them apart is why the same failure can produce a local
yellow at one point on the circuit and a red flag at another, without either
outcome being written into the failure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ..core.events import Event
from ..core.units import Metres, Seconds

__all__ = [
    "Incident",
    "IncidentKind",
    "IncidentRaised",
    "IncidentSeverity",
]


class IncidentKind(str, Enum):
    """What caused it."""

    MECHANICAL = "mechanical"
    COLLISION = "collision"
    DRIVER_ERROR = "driver_error"
    PUNCTURE = "puncture"
    DEBRIS = "debris"


class IncidentSeverity(str, Enum):
    """What it costs, in ascending order of trouble.

    Ordered deliberately: race control only ever has to ask whether an incident
    is at least as bad as something, and a car only retires at
    :attr:`RETIREMENT` or worse.
    """

    MINOR = "minor"
    """A moment.  Time lost, nothing broken."""

    DAMAGE = "damage"
    """The car goes on with less of it -- a wing, a floor, a bodywork panel."""

    RETIREMENT = "retirement"
    """The car stops, but somewhere it can be recovered without stopping the
    race."""

    BLOCKING = "blocking"
    """The car stops, or leaves debris, where it cannot be left.  This is what
    brings out a flag."""

    @property
    def ends_the_race_for_the_car(self) -> bool:
        return self in (IncidentSeverity.RETIREMENT, IncidentSeverity.BLOCKING)

    @property
    def needs_recovery(self) -> bool:
        """Whether marshals have to go and get something off the circuit."""
        return self is IncidentSeverity.BLOCKING


#: Ranking used for "at least as bad as" comparisons.
_ORDER = {
    IncidentSeverity.MINOR: 0,
    IncidentSeverity.DAMAGE: 1,
    IncidentSeverity.RETIREMENT: 2,
    IncidentSeverity.BLOCKING: 3,
}


def severity_rank(severity: IncidentSeverity) -> int:
    """Integer rank of a severity, for ordering and comparison."""
    return _ORDER[severity]


@dataclass(frozen=True)
class Incident:
    """One thing going wrong, for one car, at one place on one lap."""

    kind: IncidentKind
    severity: IncidentSeverity
    car_number: int
    lap: int
    distance: Metres = 0.0
    """Where on the lap it happened, m."""

    system: str | None = None
    """Which part failed, for a mechanical.  ``None`` otherwise."""

    involved: tuple[int, ...] = ()
    """Other cars caught up in it, for contact."""

    damage: float = 0.0
    """Aerodynamic damage carried away from it, 0 (none) to 1 (a wreck)."""

    time_lost: Seconds = 0.0
    """Time lost on the lap it happened, s, for anything the car drives away
    from."""

    debris: bool = False
    """Whether something was left on the circuit that has to be picked up.

    Separate from whether the car retired, because they are separate things: a
    front wing shed at speed brings out a virtual safety car while its owner
    carries on to the pits, and a car that stops in a run-off area often needs
    nothing at all.  Conflating them loses the most common reason a modern race
    is neutralised."""

    description: str = ""

    @property
    def retires(self) -> bool:
        return self.severity.ends_the_race_for_the_car

    @property
    def needs_recovery(self) -> bool:
        """Whether marshals have to go and get something off the circuit."""
        return self.severity.needs_recovery or self.debris

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "severity": self.severity.value,
            "car_number": self.car_number,
            "lap": self.lap,
            "distance": self.distance,
            "system": self.system,
            "involved": list(self.involved),
            "damage": self.damage,
            "time_lost": self.time_lost,
            "debris": self.debris,
            "description": self.description,
        }

    def __str__(self) -> str:  # pragma: no cover - display only
        where = f" at {self.distance:.0f} m" if self.distance else ""
        return (
            f"lap {self.lap}: car {self.car_number} {self.kind.value} "
            f"({self.severity.value}){where}"
            + (f" -- {self.description}" if self.description else "")
        )


@dataclass(frozen=True)
class IncidentRaised(Event):
    """Bus event carrying an incident."""

    incident: Incident | None = None
