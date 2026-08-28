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
from ..driver.model import Driver
from ..tyres.compound import TyreCompound
from ..tyres.state import TyreState
from ..vehicle.ers import ErsState
from ..vehicle.model import Vehicle

__all__ = ["RaceEntry"]


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
    """Where the car started.  Phase 7 fills this in from qualifying; Phase 6
    only carries it so a session can be reported in a sensible order."""

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
        """Bolt on a fresh set.  Phase 8 calls this from the pit box."""
        self.tyres.fit(compound, temperature=temperature)

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
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"RaceEntry(#{self.car_number} {self.driver.abbreviation}, "
            f"{self.vehicle.name}, {self.compound})"
        )
