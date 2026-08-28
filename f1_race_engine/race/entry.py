"""One car in a session.

An entry is the car, the driver in it, and everything that car is *carrying*:
the set of tyres fitted, the fuel on board, the state of its energy store.  It
is the natural home for that state because it is the thing that persists across
laps -- the simulator is stateless between laps and the track certainly is.

Phase 6 runs entries side by side without them interacting.  That is a real
limitation and it is deliberate: dirty air, overtaking and defence are Phase 9,
and putting a placeholder for them here would mean unpicking it later.  What
this phase establishes is the bookkeeping that racing needs -- who is where,
how far apart, on what -- computed from distance and time (rule 28).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..core.errors import EntryError
from ..core.units import Seconds
from ..driver.model import Driver
from ..tyres.compound import TyreCompound
from ..tyres.state import TyreState
from ..vehicle.ers import ErsState
from ..vehicle.model import Vehicle
from .strategy import RaceStrategy

__all__ = ["PitStop", "RaceEntry"]


@dataclass(frozen=True, slots=True)
class PitStop:
    """One visit to the pit box."""

    lap: int
    from_compound: str
    to_compound: str
    loss: Seconds
    """Time lost against staying on the circuit, in seconds."""

    reason: str = "plan"

    def to_dict(self) -> dict[str, Any]:
        return {
            "lap": self.lap,
            "from_compound": self.from_compound,
            "to_compound": self.to_compound,
            "loss": self.loss,
            "reason": self.reason,
        }


@dataclass
class RaceEntry:
    """A car, its driver, and what it is carrying."""

    car_number: int
    driver: Driver
    vehicle: Vehicle
    team: str = ""

    tyres: TyreState = field(default_factory=TyreState)
    energy: ErsState | None = None
    """Energy store.  ``None`` means "start full", resolved on first use."""

    fuel_mass: float | None = None
    """Fuel on board, kg.  ``None`` takes the car's own setup fuel load."""

    grid_position: int | None = None
    """Where the car started, filled in by qualifying."""

    strategy: RaceStrategy | None = None
    """How this car intends to cover the distance, and when it changes its
    mind.  ``None`` runs the whole race on one set."""

    compounds: tuple[TyreCompound, ...] = ()
    """The sets available to this car.  The strategist chooses from these."""

    pit_stops: list[PitStop] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.car_number <= 0:
            raise EntryError("car_number must be positive")
        if self.energy is None:
            self.energy = ErsState(energy_remaining=self.vehicle.spec.ers.capacity)
        if self.fuel_mass is None:
            self.fuel_mass = self.vehicle.setup.fuel_load

    # -- identity ------------------------------------------------------------

    @property
    def label(self) -> str:
        return f"{self.car_number:>2} {self.driver.abbreviation}"

    @property
    def name(self) -> str:
        return self.driver.name

    # -- what it is carrying -------------------------------------------------

    def fit(self, compound: TyreCompound, *, temperature: float | None = None) -> None:
        """Bolt on a fresh set."""
        self.tyres.fit(compound, temperature=temperature)
        if self.strategy is not None:
            self.strategy.start_stint(compound)

    @property
    def compound(self) -> str:
        return self.tyres.compound.code

    def snapshot(self) -> dict[str, Any]:
        return {
            "car_number": self.car_number,
            "driver": self.driver.name,
            "abbreviation": self.driver.abbreviation,
            "team": self.team,
            "vehicle": self.vehicle.name,
            "grid_position": self.grid_position,
            "fuel_mass": self.fuel_mass,
            "tyres": self.tyres.snapshot(),
            "energy": self.energy.snapshot(),
            "pit_stops": [stop.to_dict() for stop in self.pit_stops],
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"RaceEntry(#{self.car_number} {self.driver.abbreviation}, "
            f"{self.vehicle.name}, {self.compound})"
        )
