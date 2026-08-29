"""The season's circuits, and the state machine one round runs through.

A **circuit** here is the management layer's view: a name, a length, a race
distance, and five weights saying what it asks of a car.  It is deliberately
not the physics track.  The race engine has its own distance-based track model
with curvature, camber, elevation and surface, and the engine's model is what
actually decides a lap time; ``physics_track`` names which one a round is run
on.  Keeping the two apart is what lets the calendar be edited by anybody while
the geometry stays something only a survey can produce.

The **phase machine** is enforced here and checked in the service layer, not in
the UI.  A player who has not run qualifying cannot start a race by pointing a
client at the endpoint, because the round says so.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .car import AREA_NAMES
from .errors import InvalidGamePhase, UnknownEntity
from .paths import data_file

__all__ = ["Calendar", "Circuit", "Round", "RoundPhase"]


class RoundPhase(str, Enum):
    """Where a round has got to.

    Values are strings so a save file and an API response read the same.
    """

    NOT_STARTED = "not_started"
    PRACTICE = "practice"
    QUALIFYING = "qualifying"
    STRATEGY = "strategy"
    RACE = "race"
    RESULT = "result"
    DEVELOPMENT = "development"
    COMPLETE = "complete"


#: The only moves allowed.  A round advances one step at a time and never goes
#: back; re-running a race is done by reloading a save, which is also what makes
#: the result reproducible.
_NEXT: dict[RoundPhase, RoundPhase] = {
    RoundPhase.NOT_STARTED: RoundPhase.PRACTICE,
    RoundPhase.PRACTICE: RoundPhase.QUALIFYING,
    RoundPhase.QUALIFYING: RoundPhase.STRATEGY,
    RoundPhase.STRATEGY: RoundPhase.RACE,
    RoundPhase.RACE: RoundPhase.RESULT,
    RoundPhase.RESULT: RoundPhase.DEVELOPMENT,
    RoundPhase.DEVELOPMENT: RoundPhase.COMPLETE,
}


@dataclass(frozen=True, slots=True)
class Circuit:
    """One venue, as the management game sees it."""

    id: str
    name: str
    country: str = ""
    city: str = ""
    length_km: float = 5.0
    corner_count: int = 15
    race_laps: int = 55
    drs_zones: int = 2
    physics_track: str = "synthetic_proving_ground"
    """The race engine's circuit this round is actually driven on."""

    power_sensitivity: float = 0.6
    downforce_requirement: float = 0.6
    tyre_stress: float = 0.6
    brake_stress: float = 0.6
    overtaking_ease: float = 0.5

    @property
    def race_distance_km(self) -> float:
        return self.length_km * self.race_laps

    def area_weights(self) -> dict[str, float]:
        """What this circuit asks of each area of a car.

        Three of the six come straight off the circuit's character.  The other
        three are reasoned rather than listed:

        * **mechanical grip** matters where power does not.  A circuit whose
          lap is decided on the straights is not decided in the slow corners,
          and the reverse holds -- so it is the complement of power
          sensitivity.
        * **chassis** underpins everything and is never irrelevant, so it
          carries a flat weight rather than swinging with the venue.
        * **reliability** always counts, and counts for more where the brakes
          are worked hardest, because that is where a car breaks.
        """
        return {
            "aero": self.downforce_requirement,
            "power_unit": self.power_sensitivity,
            "mechanical_grip": 1.0 - self.power_sensitivity,
            "chassis": 0.60,
            "tyre_management": self.tyre_stress,
            "reliability": 0.35 + 0.30 * self.brake_stress,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "country": self.country,
            "city": self.city,
            "length_km": self.length_km,
            "corner_count": self.corner_count,
            "race_laps": self.race_laps,
            "drs_zones": self.drs_zones,
            "physics_track": self.physics_track,
            "characteristics": {
                "power_sensitivity": self.power_sensitivity,
                "downforce_requirement": self.downforce_requirement,
                "tyre_stress": self.tyre_stress,
                "brake_stress": self.brake_stress,
                "overtaking_ease": self.overtaking_ease,
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Circuit:
        chars = data.get("characteristics", {})
        return cls(
            id=str(data["id"]),
            name=str(data.get("name", data["id"])),
            country=str(data.get("country", "")),
            city=str(data.get("city", "")),
            length_km=float(data.get("length_km", 5.0)),
            corner_count=int(data.get("corner_count", 15)),
            race_laps=int(data.get("race_laps", 55)),
            drs_zones=int(data.get("drs_zones", 2)),
            physics_track=str(data.get("physics_track", "synthetic_proving_ground")),
            power_sensitivity=float(chars.get("power_sensitivity", 0.6)),
            downforce_requirement=float(chars.get("downforce_requirement", 0.6)),
            tyre_stress=float(chars.get("tyre_stress", 0.6)),
            brake_stress=float(chars.get("brake_stress", 0.6)),
            overtaking_ease=float(chars.get("overtaking_ease", 0.5)),
        )


@dataclass(slots=True)
class Round:
    """One grand prix weekend on the calendar."""

    number: int
    circuit_id: str
    name: str = ""
    laps: int = 55
    phase: RoundPhase = RoundPhase.NOT_STARTED
    race_id: str | None = None
    """Where the result of this round's race is filed, once there is one."""

    grid: list[str] = field(default_factory=list)
    """The starting order, as driver ids, once qualifying has run.

    Driver ids rather than car numbers: a car number is assigned when a field
    is assembled and would stop meaning anything if a driver changed teams
    between qualifying and the race."""

    @property
    def is_complete(self) -> bool:
        return self.phase is RoundPhase.COMPLETE

    def require(self, *phases: RoundPhase) -> None:
        """Refuse unless the round is in one of ``phases``."""
        if self.phase not in phases:
            allowed = ", ".join(p.value for p in phases)
            raise InvalidGamePhase(
                f"round {self.number} is at {self.phase.value}; "
                f"this needs {allowed}"
            )

    def advance(self, expected: RoundPhase | None = None) -> RoundPhase:
        """Take the single legal step forward.

        ``expected`` guards against advancing a round that has moved on
        underneath the caller -- two clients racing the same save, say.
        """
        if expected is not None and self.phase is not expected:
            raise InvalidGamePhase(
                f"round {self.number} is at {self.phase.value}, not {expected.value}"
            )
        nxt = _NEXT.get(self.phase)
        if nxt is None:
            raise InvalidGamePhase(f"round {self.number} is already complete")
        self.phase = nxt
        return self.phase

    def to_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "circuit": self.circuit_id,
            "name": self.name,
            "laps": self.laps,
            "phase": self.phase.value,
            "race_id": self.race_id,
            "grid": list(self.grid),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Round:
        return cls(
            number=int(data["number"]),
            circuit_id=str(data["circuit"]),
            name=str(data.get("name", "")),
            laps=int(data.get("laps", 55)),
            phase=RoundPhase(data.get("phase", "not_started")),
            race_id=data.get("race_id"),
            grid=list(data.get("grid", [])),
        )


@dataclass(slots=True)
class Calendar:
    """A season's rounds, and the circuits they are held at."""

    season: int
    rounds: list[Round] = field(default_factory=list)
    circuits: dict[str, Circuit] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.rounds)

    def __iter__(self):
        return iter(self.rounds)

    # -- lookups -------------------------------------------------------------

    def round(self, number: int) -> Round:
        for entry in self.rounds:
            if entry.number == number:
                return entry
        raise UnknownEntity(f"no round {number} in the {self.season} calendar")

    def circuit(self, circuit_id: str) -> Circuit:
        try:
            return self.circuits[circuit_id]
        except KeyError as error:
            raise UnknownEntity(f"unknown circuit {circuit_id!r}") from error

    def circuit_for(self, number: int) -> Circuit:
        return self.circuit(self.round(number).circuit_id)

    @property
    def next_incomplete(self) -> Round | None:
        """The round the season is waiting on, or ``None`` if it is over."""
        for entry in self.rounds:
            if not entry.is_complete:
                return entry
        return None

    # -- building ------------------------------------------------------------

    @classmethod
    def load(cls, *, season: int | None = None) -> Calendar:
        """Read the shipped calendar and the circuits it refers to."""
        try:
            calendar_data = json.loads(
                data_file("calendar.json").read_text(encoding="utf-8")
            )
            track_data = json.loads(
                data_file("tracks", "tracks.json").read_text(encoding="utf-8")
            )
        except FileNotFoundError as error:  # pragma: no cover - configuration
            raise UnknownEntity(f"missing calendar data: {error}") from error

        circuits = {
            entry["id"]: Circuit.from_dict(entry) for entry in track_data["tracks"]
        }
        rounds = []
        for entry in calendar_data["rounds"]:
            circuit_id = entry["track"]
            if circuit_id not in circuits:
                raise UnknownEntity(
                    f"round {entry['round']} names circuit {circuit_id!r}, "
                    "which is not in the track data"
                )
            rounds.append(
                Round(
                    number=int(entry["round"]),
                    circuit_id=circuit_id,
                    name=str(entry.get("name", "")),
                    laps=int(entry.get("laps", circuits[circuit_id].race_laps)),
                )
            )
        rounds.sort(key=lambda r: r.number)
        return cls(
            season=season if season is not None else int(calendar_data["season"]),
            rounds=rounds,
            circuits=circuits,
        )

    # -- persistence ---------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "season": self.season,
            "rounds": [entry.to_dict() for entry in self.rounds],
            "circuits": {cid: c.to_dict() for cid, c in self.circuits.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Calendar:
        return cls(
            season=int(data["season"]),
            rounds=[Round.from_dict(entry) for entry in data.get("rounds", [])],
            circuits={
                cid: Circuit.from_dict(entry)
                for cid, entry in data.get("circuits", {}).items()
            },
        )


# A guard rather than a comment: if a car area is ever added, the weighting
# above has to learn about it, and this says so at import time.
assert set(Circuit(id="_", name="_").area_weights()) == set(AREA_NAMES), (
    "Circuit.area_weights must weight every car area"
)
