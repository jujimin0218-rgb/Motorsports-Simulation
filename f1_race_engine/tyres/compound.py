"""Tyre compounds.

A compound is *data*: what the rubber can do.  How much grip it actually
delivers under a given load is the model's job
(:mod:`f1_race_engine.tyres.model`), and how that decays over a stint is
Phase 5's.

Phase 2 uses two properties, both real and both measurable:

* **peak friction** at a reference vertical load, and
* **load sensitivity** -- how much the friction coefficient falls as load
  rises.

The temperature and degradation fields are carried now, with neutral defaults,
so that Phase 5 fills them in rather than reshaping the type.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from ..core.errors import ConfigError

__all__ = ["CompoundFamily", "TyreCompound", "CompoundSet"]


class CompoundFamily(str, Enum):
    """Which conditions a compound is built for."""

    SLICK = "slick"
    INTERMEDIATE = "intermediate"
    WET = "wet"


@dataclass(frozen=True, slots=True)
class TyreCompound:
    """One tyre compound."""

    name: str
    code: str
    """Short label used in timing screens: ``S``, ``M``, ``H``, ``I``, ``W``."""

    family: CompoundFamily = CompoundFamily.SLICK

    peak_friction: float = 1.68
    """Peak friction coefficient at :attr:`reference_load`.

    Around 1.6-1.8 for a modern F1 slick.  This is the *tyre's* number; the
    surface it runs on scales it (``TrackSegment.surface_grip``)."""

    reference_load: float = 8000.0
    """Vertical load, N, at which :attr:`peak_friction` applies.

    A **whole-car** figure -- roughly the static weight of a fuelled car, so
    the peak coefficient is the one the tyre shows sitting still.  Queries
    about a single axle convert to this basis first
    (:meth:`TyreModel.friction_coefficient`), because load sensitivity belongs
    to one contact patch and not to the car."""

    load_sensitivity: float = 0.08
    """Exponent ``k`` in ``mu = mu_peak * (N / N_ref)^-k``.

    Real tyres lose friction coefficient as they are pressed harder -- doubling
    the load does not double the grip.  This single number is why an F1 car
    pulls over 5 g in a fast corner yet its *coefficient* there is lower than
    in a slow one.  Zero would mean Coulomb friction, which no tyre obeys."""

    rolling_resistance: float = 0.012
    """Rolling resistance coefficient, dimensionless."""

    # -- carried for Phase 5; neutral in Phase 2 -----------------------------

    optimal_temperature: float = 100.0
    """Centre of the working temperature window, degC."""

    temperature_window: float = 25.0
    """Half-width of the working window, K."""

    wear_rate: float = 1.0
    """Relative wear rate, 1.0 = reference.  Softer compounds wear faster."""

    warmup_laps: float = 1.5
    """Laps to reach the working window from cold."""

    peak_water_depth: float = 0.0
    """Water depth, m, this compound is designed to clear.  Zero for slicks."""

    def __post_init__(self) -> None:
        if self.peak_friction <= 0.0:
            raise ConfigError(f"{self.name}: peak_friction must be positive")
        if self.reference_load <= 0.0:
            raise ConfigError(f"{self.name}: reference_load must be positive")
        if not 0.0 <= self.load_sensitivity < 1.0:
            raise ConfigError(
                f"{self.name}: load_sensitivity must lie in [0, 1), "
                f"got {self.load_sensitivity}"
            )
        if self.rolling_resistance < 0.0:
            raise ConfigError(f"{self.name}: rolling_resistance must be non-negative")
        if self.temperature_window <= 0.0:
            raise ConfigError(f"{self.name}: temperature_window must be positive")
        if self.wear_rate < 0.0:
            raise ConfigError(f"{self.name}: wear_rate must be non-negative")

    @property
    def is_wet_weather(self) -> bool:
        return self.family is not CompoundFamily.SLICK

    def friction_coefficient(self, normal_load: float) -> float:
        """Friction coefficient at ``normal_load`` newtons.

        ``mu = mu_peak * (N / N_ref) ** -k``.  Loads at or below zero return the
        peak value: an unloaded tyre carries no force anyway, and the power law
        diverges there.
        """
        if normal_load <= 0.0:
            return self.peak_friction
        if self.load_sensitivity == 0.0:
            return self.peak_friction
        return self.peak_friction * (normal_load / self.reference_load) ** (
            -self.load_sensitivity
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "code": self.code,
            "family": self.family.value,
            "peak_friction": self.peak_friction,
            "reference_load": self.reference_load,
            "load_sensitivity": self.load_sensitivity,
            "rolling_resistance": self.rolling_resistance,
            "optimal_temperature": self.optimal_temperature,
            "temperature_window": self.temperature_window,
            "wear_rate": self.wear_rate,
            "warmup_laps": self.warmup_laps,
            "peak_water_depth": self.peak_water_depth,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TyreCompound:
        payload = dict(data)
        if "family" in payload:
            payload["family"] = CompoundFamily(payload["family"])
        known = {f for f in cls.__slots__}
        unknown = set(payload) - known
        if unknown:
            raise ConfigError(
                f"unknown tyre compound key(s): {', '.join(sorted(unknown))}"
            )
        return cls(**payload)


class CompoundSet:
    """The compounds available at an event."""

    __slots__ = ("_compounds", "_by_code", "name")

    def __init__(self, compounds: list[TyreCompound], name: str = "compound set") -> None:
        if not compounds:
            raise ConfigError("a compound set needs at least one compound")
        self.name = name
        self._compounds = tuple(compounds)
        self._by_code: dict[str, TyreCompound] = {}
        for compound in compounds:
            key = compound.code.upper()
            if key in self._by_code:
                raise ConfigError(f"duplicate compound code {compound.code!r}")
            self._by_code[key] = compound

    @property
    def compounds(self) -> tuple[TyreCompound, ...]:
        return self._compounds

    @property
    def slicks(self) -> tuple[TyreCompound, ...]:
        return tuple(c for c in self._compounds if not c.is_wet_weather)

    @property
    def wets(self) -> tuple[TyreCompound, ...]:
        return tuple(c for c in self._compounds if c.is_wet_weather)

    def __getitem__(self, code: str) -> TyreCompound:
        try:
            return self._by_code[code.upper()]
        except KeyError:
            available = ", ".join(sorted(self._by_code))
            raise KeyError(
                f"unknown compound {code!r}; available: {available}"
            ) from None

    def __contains__(self, code: object) -> bool:
        return isinstance(code, str) and code.upper() in self._by_code

    def __len__(self) -> int:
        return len(self._compounds)

    def __iter__(self):
        return iter(self._compounds)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "compounds": [c.to_dict() for c in self._compounds],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CompoundSet:
        return cls(
            [TyreCompound.from_dict(c) for c in data["compounds"]],
            name=data.get("name", "compound set"),
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"CompoundSet({self.name!r}, {[c.code for c in self._compounds]})"
