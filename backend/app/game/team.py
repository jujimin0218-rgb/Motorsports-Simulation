"""A team: a factory, a budget, an engine deal and two drivers.

The interesting thing about a team is that its three resources -- money,
research and reputation -- buy different things on different timescales.  Money
buys a driver now.  Research buys car performance over a few rounds.
Reputation buys the *option* to sign the driver at all, and takes a season to
move.  A team that spends only on the fastest of the three wins nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .car import CarPerformance, Facilities
from .errors import InsufficientBudget

__all__ = ["Team"]


@dataclass(slots=True)
class Team:
    """One constructor."""

    id: str
    name: str
    nationality: str = ""
    engine: str = ""
    """Id of the :class:`~app.game.car.EngineSupplier` this team runs."""

    budget: float = 145.0
    """Millions.  Spent on drivers, research, the engine deal and running the
    thing; refilled by prize money and sponsors."""

    reputation: float = 0.6
    """0 to 1.  What a driver thinks of the seat, and what a sponsor will pay
    to be on the car."""

    car: CarPerformance = field(default_factory=CarPerformance)
    facilities: Facilities = field(default_factory=Facilities)
    rd_points: float = 0.0
    """Research banked but not yet spent on anything."""

    drivers: list[str] = field(default_factory=list)
    """Driver ids, in car order.  The first is the number one seat."""

    staff: int = 600
    """Head count.  Raises the research a round produces and the cost of
    producing it, which is what makes a big team expensive to be."""

    # -- money ---------------------------------------------------------------

    def can_afford(self, amount: float) -> bool:
        return self.budget >= amount

    def spend(self, amount: float, *, what: str = "") -> None:
        """Take money out, refusing rather than going quietly negative."""
        if amount < 0.0:
            raise InsufficientBudget("cannot spend a negative amount")
        if not self.can_afford(amount):
            detail = f" on {what}" if what else ""
            raise InsufficientBudget(
                f"{self.name} cannot afford {amount:.1f}M{detail} "
                f"(budget {self.budget:.1f}M)"
            )
        self.budget -= amount

    def earn(self, amount: float) -> None:
        self.budget += amount

    # -- research ------------------------------------------------------------

    def development_rate(self, area: str, *, per_level: float = 0.18) -> float:
        """How efficiently this team turns research into progress in ``area``.

        A level-3 facility is the reference and returns 1.0, so a team with
        nothing built is not punished twice -- once for the facility and again
        for the budget it took to build it.
        """
        from .car import FACILITY_FOR_AREA

        facility = FACILITY_FOR_AREA.get(area)
        if facility is None:
            return 1.0
        return 1.0 + per_level * (self.facilities.level(facility) - 3)

    # -- persistence ---------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "nationality": self.nationality,
            "engine": self.engine,
            "budget": round(self.budget, 4),
            "reputation": self.reputation,
            "car": self.car.to_dict(),
            "facilities": self.facilities.to_dict(),
            "rd_points": round(self.rd_points, 4),
            "drivers": list(self.drivers),
            "staff": self.staff,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Team:
        return cls(
            id=str(data["id"]),
            name=str(data.get("name", data["id"])),
            nationality=str(data.get("nationality", "")),
            engine=str(data.get("engine", "")),
            budget=float(data.get("budget", 145.0)),
            reputation=float(data.get("reputation", 0.6)),
            car=CarPerformance.from_dict(data.get("car", {})),
            facilities=Facilities.from_dict(data.get("facilities", {})),
            rd_points=float(data.get("rd_points", 0.0)),
            drivers=list(data.get("drivers", [])),
            staff=int(data.get("staff", 600)),
        )
