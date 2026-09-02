"""Vehicle setup -- the choices a team makes before a session.

Phase 2 exposes the two that matter to the physics already implemented: how
much wing to run, and where to put the brake bias.  Setup is deliberately
separate from the car's *specification*: the spec is what the team built, the
setup is how they run it this weekend, and a setup optimiser (later) needs to
vary one without touching the other.

Ride height, suspension, differential, gear ratios and tyre pressures join in
Phase 12 as further fields here.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from ..core.errors import ConfigError

__all__ = ["VehicleSetup"]


@dataclass(frozen=True, slots=True)
class VehicleSetup:
    """How a car is configured for a session."""

    wing_level: float = 0.5
    """Aerodynamic downforce level, 0 (minimum wing) to 1 (maximum wing).

    The single most consequential setup choice: it trades cornering grip
    against straight-line speed, and which side of that trade wins is decided
    by the circuit, not by any per-track adjustment."""

    brake_bias_front: float | None = None
    """Overrides the car's default brake bias when set."""

    fuel_load: float = 100.0
    """Fuel put in for the session, kg.  Burns off during the run (Phase 5)."""

    def __post_init__(self) -> None:
        if not 0.0 <= self.wing_level <= 1.0:
            raise ConfigError(
                f"wing_level must lie in [0, 1], got {self.wing_level}"
            )
        if self.brake_bias_front is not None and not 0.3 <= self.brake_bias_front <= 0.8:
            raise ConfigError("brake_bias_front must lie in [0.3, 0.8]")
        if self.fuel_load < 0.0:
            raise ConfigError("fuel_load must be non-negative")

    def with_wing(self, wing_level: float) -> VehicleSetup:
        """A copy at a different wing level."""
        return replace(self, wing_level=wing_level)

    def with_fuel(self, fuel_load: float) -> VehicleSetup:
        """A copy with a different fuel load."""
        return replace(self, fuel_load=fuel_load)

    def to_dict(self) -> dict[str, Any]:
        return {
            "wing_level": self.wing_level,
            "brake_bias_front": self.brake_bias_front,
            "fuel_load": self.fuel_load,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VehicleSetup:
        known = set(cls.__slots__)
        unknown = set(data) - known
        if unknown:
            raise ConfigError(f"unknown setup key(s): {', '.join(sorted(unknown))}")
        return cls(**data)


#: Convenient starting points.  Not per-track corrections -- just sensible
#: places to begin a setup search, which the physics then judges.
LOW_DOWNFORCE = VehicleSetup(wing_level=0.05)
MEDIUM_DOWNFORCE = VehicleSetup(wing_level=0.5)
HIGH_DOWNFORCE = VehicleSetup(wing_level=0.95)
