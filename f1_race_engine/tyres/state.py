"""Tyre state.

One instance per car (Phase 2 treats the four tyres as a set; per-corner state
arrives with the suspension model in Phase 12).

In Phase 2 the state is deliberately close to inert: it tracks which compound
is fitted and how far it has run, and :meth:`TyreState.grip_multiplier` returns
exactly 1.0.  Phase 5 gives temperature, wear and degradation real behaviour by
filling in that one method and the fields it reads -- no consumer changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..core.state import MutableState
from .compound import TyreCompound

__all__ = ["TyreState"]


@dataclass
class TyreState(MutableState):
    """Condition of the tyres currently fitted."""

    compound: TyreCompound = field(default_factory=lambda: TyreCompound("Medium", "M"))

    age_laps: float = 0.0
    """Laps completed on this set."""

    age_distance: float = 0.0
    """Distance covered on this set, m."""

    wear: float = 0.0
    """Tread used, 0 (new) to 1 (worn out).  Driven from Phase 5."""

    surface_temperature: float = 80.0
    """Tread surface temperature, degC.  Driven from Phase 5."""

    carcass_temperature: float = 70.0
    """Carcass bulk temperature, degC.  Driven from Phase 5."""

    pressure: float = 152_000.0
    """Inflation pressure, Pa (about 22 psi cold)."""

    def snapshot(self) -> dict[str, Any]:
        return {
            "compound": self.compound.code,
            "age_laps": self.age_laps,
            "age_distance": self.age_distance,
            "wear": self.wear,
            "surface_temperature": self.surface_temperature,
            "carcass_temperature": self.carcass_temperature,
            "pressure": self.pressure,
        }

    def grip_multiplier(self) -> float:
        """Condition-derived multiplier on the compound's peak friction.

        Phase 2 returns 1.0: a fresh tyre at its working temperature performs
        exactly as its compound says.  Phase 5 replaces this with the
        temperature-window and degradation model.  Everything downstream reads
        this one number, so nothing else has to change when it does.
        """
        return 1.0

    def fit(self, compound: TyreCompound) -> None:
        """Fit a fresh set of ``compound``."""
        self.compound = compound
        self.age_laps = 0.0
        self.age_distance = 0.0
        self.wear = 0.0

    @property
    def is_wet_weather(self) -> bool:
        return self.compound.is_wet_weather

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"TyreState({self.compound.code}, {self.age_laps:.1f} laps, "
            f"wear {self.wear:.0%})"
        )
