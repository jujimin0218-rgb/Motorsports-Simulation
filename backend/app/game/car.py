"""The car, the factory that builds it, and the engine in the back.

Car performance is deliberately **not one number**.  A single "car rating"
makes every circuit the same circuit, and the thing that makes a season
interesting is that it is not: a car that is quick at Monza is quick because of
its power unit and its low drag, and the same car is nowhere at Monaco.  So
performance is kept as six areas, and what a circuit asks of each of them is a
property of the circuit (``data/tracks/tracks.json``).

None of these numbers reach the physics directly.  The adapter in Phase 2 turns
them into a :class:`~f1_race_engine.vehicle.VehicleSpec` -- real aerodynamic
areas, real masses, real power -- and the race engine works out the lap time
from that.  A rating here is a statement about *how good this team's version of
the car is*, not a lap-time bonus.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .errors import UnknownEntity

__all__ = [
    "AREA_NAMES",
    "CarPerformance",
    "EngineSupplier",
    "FACILITY_NAMES",
    "Facilities",
]

#: The six areas a car is developed in.  Kept as a tuple so that the R&D
#: system, the save format and the API all agree on the spelling.
AREA_NAMES: tuple[str, ...] = (
    "aero",
    "chassis",
    "power_unit",
    "mechanical_grip",
    "tyre_management",
    "reliability",
)

#: The six departments a team can invest in.
FACILITY_NAMES: tuple[str, ...] = (
    "aerodynamics",
    "power_unit",
    "chassis",
    "reliability",
    "simulator",
    "driver_development",
)

#: Which facility raises which area of the car.  Two of the six departments --
#: the simulator and driver development -- deliberately do not appear: they pay
#: off in setup quality and in how fast a driver grows, not in the car itself.
FACILITY_FOR_AREA: dict[str, str] = {
    "aero": "aerodynamics",
    "chassis": "chassis",
    "power_unit": "power_unit",
    "mechanical_grip": "chassis",
    "tyre_management": "chassis",
    "reliability": "reliability",
}

MAX_FACILITY_LEVEL = 5


@dataclass(slots=True)
class Facilities:
    """What a team has built, by department.

    Levels run 1 to :data:`MAX_FACILITY_LEVEL`.  A facility does not make the
    car quicker on its own; it makes *development* in that area more
    efficient, which is a slower and more interesting kind of advantage --
    a team that invests early compounds, and a team that buys a driver instead
    is quicker this season and slower in three.
    """

    aerodynamics: int = 3
    power_unit: int = 3
    chassis: int = 3
    reliability: int = 3
    simulator: int = 3
    driver_development: int = 3

    def level(self, name: str) -> int:
        if name not in FACILITY_NAMES:
            raise UnknownEntity(f"unknown facility {name!r}")
        return int(getattr(self, name))

    def upgrade(self, name: str) -> None:
        """Raise one department by a level, if there is room."""
        current = self.level(name)
        if current >= MAX_FACILITY_LEVEL:
            raise UnknownEntity(f"{name} is already at the maximum level")
        setattr(self, name, current + 1)

    @property
    def average_level(self) -> float:
        return sum(self.level(name) for name in FACILITY_NAMES) / len(FACILITY_NAMES)

    def to_dict(self) -> dict[str, int]:
        return {name: self.level(name) for name in FACILITY_NAMES}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Facilities:
        return cls(**{name: int(data.get(name, 3)) for name in FACILITY_NAMES})


@dataclass(slots=True)
class CarPerformance:
    """How good this team's car is, area by area.  Every value is 0 to 1."""

    aero: float = 0.80
    chassis: float = 0.80
    power_unit: float = 0.80
    mechanical_grip: float = 0.80
    tyre_management: float = 0.80
    reliability: float = 0.80

    def area(self, name: str) -> float:
        if name not in AREA_NAMES:
            raise UnknownEntity(f"unknown car area {name!r}")
        return float(getattr(self, name))

    def set_area(self, name: str, value: float) -> None:
        self.area(name)  # validates the name
        setattr(self, name, min(1.0, max(0.0, float(value))))

    def improve(self, name: str, amount: float) -> float:
        """Add ``amount`` to one area and return what it became."""
        self.set_area(name, self.area(name) + amount)
        return self.area(name)

    def rating_for(self, weights: dict[str, float]) -> float:
        """How good this car is *at one circuit*.

        ``weights`` says what the circuit asks of each area.  The result is the
        weighted mean, so the same car scores differently at Monza and Monaco
        without anybody writing down a per-circuit correction.
        """
        total = sum(weights.get(name, 0.0) for name in AREA_NAMES)
        if total <= 0.0:
            return self.overall
        return (
            sum(self.area(name) * weights.get(name, 0.0) for name in AREA_NAMES) / total
        )

    @property
    def overall(self) -> float:
        """The unweighted mean.  Useful for a standings screen and for nothing
        else -- no circuit ever asks for this."""
        return sum(self.area(name) for name in AREA_NAMES) / len(AREA_NAMES)

    def to_dict(self) -> dict[str, float]:
        return {name: round(self.area(name), 6) for name in AREA_NAMES}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CarPerformance:
        return cls(**{name: float(data.get(name, 0.8)) for name in AREA_NAMES})


@dataclass(frozen=True, slots=True)
class EngineSupplier:
    """A power unit, and what it costs to have one.

    A works team gets the engine at no charge and a customer pays for it, which
    is the trade the midfield actually makes: a cheaper engine leaves more for
    R&D, and a better one leaves less.
    """

    id: str
    name: str
    nationality: str = ""
    ice_output: float = 0.85
    kers_output: float = 0.85
    fuel_efficiency: float = 0.85
    cooling: float = 0.85
    reliability: float = 0.85
    cost_per_season: float = 15.0
    works_team: str | None = None

    @property
    def power_rating(self) -> float:
        """One number for the power the unit makes, for the car's power_unit
        area.  Deployment counts for less than the engine itself because it is
        available for less of a lap."""
        return 0.7 * self.ice_output + 0.3 * self.kers_output

    def cost_for(self, team_id: str) -> float:
        """What this supply costs ``team_id`` for a season, in millions."""
        return 0.0 if team_id == self.works_team else self.cost_per_season

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "nationality": self.nationality,
            "ice_output": self.ice_output,
            "kers_output": self.kers_output,
            "fuel_efficiency": self.fuel_efficiency,
            "cooling": self.cooling,
            "reliability": self.reliability,
            "cost_per_season": self.cost_per_season,
            "works_team": self.works_team,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EngineSupplier:
        return cls(
            id=str(data["id"]),
            name=str(data.get("name", data["id"])),
            nationality=str(data.get("nationality", "")),
            ice_output=float(data.get("ice_output", 0.85)),
            kers_output=float(data.get("kers_output", 0.85)),
            fuel_efficiency=float(data.get("fuel_efficiency", 0.85)),
            cooling=float(data.get("cooling", 0.85)),
            reliability=float(data.get("reliability", 0.85)),
            cost_per_season=float(data.get("cost_per_season", 15.0)),
            works_team=data.get("works_team"),
        )
