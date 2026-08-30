"""Brakes.

A Formula 1 car can lock its wheels at any speed: the brake system is capable
of more torque than the tyres can transmit.  So braking is **grip limited**,
not brake limited, and the deceleration a car achieves is set by tyre friction
plus the downforce pressing it down -- which is why an F1 car brakes at over
5 g from 300 km/h and barely 2 g from 100 km/h.

The system capability is still modelled, for two reasons: it is what makes a
brake-by-wire or brake-bias change meaningful, and it is where thermal fade
attaches in Phase 12.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..core.errors import ConfigError
from ..core.units import Newtons

__all__ = ["BrakeProperties", "BrakeSystem"]


@dataclass(frozen=True, slots=True)
class BrakeProperties:
    """A car's braking system."""

    max_brake_force: Newtons = 60_000.0
    """Peak retarding force the system can apply at the wheels, N.

    Deliberately above any grip limit the tyres can offer: that is what makes
    the car lockable, and it means braking performance comes from grip rather
    than from this number."""

    brake_bias_front: float = 0.57
    """Fraction of braking effort sent to the front axle."""

    def __post_init__(self) -> None:
        if self.max_brake_force <= 0.0:
            raise ConfigError("max_brake_force must be positive")
        if not 0.3 <= self.brake_bias_front <= 0.8:
            raise ConfigError("brake_bias_front must lie in [0.3, 0.8]")

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_brake_force": self.max_brake_force,
            "brake_bias_front": self.brake_bias_front,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BrakeProperties:
        known = set(cls.__slots__)
        unknown = set(data) - known
        if unknown:
            raise ConfigError(f"unknown brake key(s): {', '.join(sorted(unknown))}")
        return cls(**data)


class BrakeSystem:
    """Applies braking effort, capped by what the system can produce."""

    __slots__ = ("_properties",)

    def __init__(self, properties: BrakeProperties) -> None:
        self._properties = properties

    @property
    def properties(self) -> BrakeProperties:
        return self._properties

    def system_limit(self) -> Newtons:
        """Maximum retarding force the brakes themselves can make, N."""
        return self._properties.max_brake_force

    def brake_force(self, demand: float) -> Newtons:
        """Retarding force for a pedal ``demand`` in ``[0, 1]``, N.

        Still subject to the tyre grip limit, which the longitudinal model
        applies.
        """
        if demand <= 0.0:
            return 0.0
        return self._properties.max_brake_force * min(demand, 1.0)
