"""The driver.

Project rule 18: a driver is not one rating.  Ten separate abilities, each
connected to something the car actually does, so that a driver who is strong on
the brakes and weak on traction drives differently from one who is the reverse
-- rather than both being "a 7 out of 10".

Where each attribute connects:

===================  =========================================================
attribute            what it changes
===================  =========================================================
braking              how much grip is used under braking, hence braking points
cornering            how much lateral grip is used, hence apex speeds
throttle_control     how much grip is used on the way out, hence exit traction
consistency          lap-to-lap and corner-to-corner variation
risk_management      how often a mistake happens, and how bad
pace                 a small overall commitment bias on top of the specifics
qualifying           extra commitment on a single flying lap
tyre_management      tyre degradation (Phase 5)
racecraft            overtaking and defending (Phase 9)
wet_skill            grip in the wet (Phase 10)
===================  =========================================================

The three attributes with a "(Phase N)" note are carried now and used later.
They are real fields on a real model, not placeholders: a driver file written
today will still be correct when Phase 5 reads ``tyre_management``.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from ..core.errors import ConfigError

__all__ = ["Driver", "DriverAttributes"]

_ATTRIBUTES = (
    "pace",
    "qualifying",
    "racecraft",
    "consistency",
    "tyre_management",
    "braking",
    "cornering",
    "throttle_control",
    "wet_skill",
    "risk_management",
)


@dataclass(frozen=True, slots=True)
class DriverAttributes:
    """A driver's abilities, each on a 0-1 scale.

    1.0 is the best on the grid, not a theoretical perfect human.  Formula 1
    drivers occupy roughly 0.70 to 1.00; the scale has room below that for
    junior categories.
    """

    pace: float = 0.85
    qualifying: float = 0.85
    racecraft: float = 0.85
    consistency: float = 0.85
    tyre_management: float = 0.85
    braking: float = 0.85
    cornering: float = 0.85
    throttle_control: float = 0.85
    wet_skill: float = 0.85
    risk_management: float = 0.85

    def __post_init__(self) -> None:
        for name in _ATTRIBUTES:
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ConfigError(
                    f"driver attribute {name!r} must lie in [0, 1], got {value}"
                )

    @property
    def overall(self) -> float:
        """Unweighted mean, for display only.

        Deliberately not used by the physics: collapsing ten abilities into one
        number is exactly what project rule 18 forbids.
        """
        return sum(getattr(self, name) for name in _ATTRIBUTES) / len(_ATTRIBUTES)

    def to_dict(self) -> dict[str, float]:
        return {name: getattr(self, name) for name in _ATTRIBUTES}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DriverAttributes:
        unknown = set(data) - set(_ATTRIBUTES)
        if unknown:
            raise ConfigError(
                f"unknown driver attribute(s): {', '.join(sorted(unknown))}"
            )
        return cls(**data)

    def with_attribute(self, name: str, value: float) -> DriverAttributes:
        if name not in _ATTRIBUTES:
            raise ConfigError(f"unknown driver attribute {name!r}")
        return replace(self, **{name: value})


@dataclass(frozen=True)
class Driver:
    """One driver."""

    name: str
    abbreviation: str = "DRV"
    number: int | None = None
    team: str | None = None
    attributes: DriverAttributes = field(default_factory=DriverAttributes)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name:
            raise ConfigError("a driver needs a name")
        if self.number is not None and not 1 <= self.number <= 99:
            raise ConfigError(f"driver number must lie in 1-99, got {self.number}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "abbreviation": self.abbreviation,
            "number": self.number,
            "team": self.team,
            "attributes": self.attributes.to_dict(),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Driver:
        if "name" not in data:
            raise ConfigError("driver data is missing the 'name' key")
        known = {"name", "abbreviation", "number", "team", "attributes", "metadata"}
        unknown = set(data) - known
        if unknown:
            raise ConfigError(f"unknown driver key(s): {', '.join(sorted(unknown))}")
        return cls(
            name=data["name"],
            abbreviation=data.get("abbreviation", "DRV"),
            number=data.get("number"),
            team=data.get("team"),
            attributes=DriverAttributes.from_dict(data.get("attributes", {})),
            metadata=dict(data.get("metadata", {})),
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Driver({self.name!r}, {self.abbreviation}, overall={self.attributes.overall:.2f})"
