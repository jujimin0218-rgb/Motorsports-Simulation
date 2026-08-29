"""Mass, its distribution, and how it moves.

Mass enters the physics in four separate places, which is why it deserves its
own model rather than a single number:

* inertia -- ``a = F / m``;
* weight -- vertical load on the tyres, hence grip;
* the gradient term -- ``m * g * sin(theta)`` up Eau Rouge;
* load transfer -- how much of that weight sits on the driven axle.

Fuel is part of it and burns away (project rule 23), so a car is a different
machine on lap 1 and lap 50 without anyone writing a rule that says so.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..core.errors import ConfigError
from ..core.units import Kilograms, Metres, Newtons

__all__ = ["MassProperties"]


@dataclass(frozen=True, slots=True)
class MassProperties:
    """The car's mass and geometry.

    ``chassis_mass`` plus ``driver_mass`` is the regulated minimum mass, which
    excludes fuel -- so the fuel load is tracked separately, on the state.
    """

    chassis_mass: Kilograms = 718.0
    """Car without driver or fuel, kg."""

    driver_mass: Kilograms = 80.0
    """Driver plus seat and equipment, kg."""

    wheelbase: Metres = 3.6
    cg_height: Metres = 0.30
    """Centre-of-gravity height, m.  Sets how much load transfers under
    acceleration and braking."""

    weight_distribution_front: float = 0.45
    """Fraction of static weight carried by the front axle."""

    track_width: Metres = 1.60
    """Distance between the wheel centres across the car, m.

    What sets lateral load transfer, and the reason a wide car corners better
    than a narrow one at the same centre-of-gravity height: transfer is
    ``m * a_y * h_cg / track``, so the wider the car the less of it there is."""

    def __post_init__(self) -> None:
        if self.chassis_mass <= 0.0:
            raise ConfigError("chassis_mass must be positive")
        if self.driver_mass < 0.0:
            raise ConfigError("driver_mass must be non-negative")
        if self.wheelbase <= 0.0:
            raise ConfigError("wheelbase must be positive")
        if self.cg_height < 0.0:
            raise ConfigError("cg_height must be non-negative")
        if self.track_width <= 0.0:
            raise ConfigError("track_width must be positive")
        if not 0.2 <= self.weight_distribution_front <= 0.8:
            raise ConfigError(
                "weight_distribution_front must lie in [0.2, 0.8], got "
                f"{self.weight_distribution_front}"
            )

    @property
    def dry_mass(self) -> Kilograms:
        """Car plus driver, without fuel -- the regulated minimum mass."""
        return self.chassis_mass + self.driver_mass

    def total_mass(self, fuel_mass: Kilograms = 0.0) -> Kilograms:
        """Everything the engine has to accelerate, kg."""
        if fuel_mass < 0.0:
            raise ConfigError("fuel_mass must be non-negative")
        return self.dry_mass + fuel_mass

    def weight(self, fuel_mass: Kilograms = 0.0, gravity: float = 9.80665) -> Newtons:
        """Weight force, N."""
        return self.total_mass(fuel_mass) * gravity

    @property
    def weight_distribution_rear(self) -> float:
        return 1.0 - self.weight_distribution_front

    def lateral_load_transfer(
        self, lateral_acceleration: float, mass: Kilograms
    ) -> Newtons:
        """Vertical load moved from the inside wheels to the outside ones, N.

        Quasi-static, the same form as the longitudinal transfer and for the
        same reason: ``dN = m * a_y * h_cg / track``.  Roll stiffness decides
        how it splits front to rear, which is what a setup change to the
        anti-roll bars actually does; that is Phase 12's suspension model and
        this is the total it has to share out.
        """
        return mass * lateral_acceleration * self.cg_height / self.track_width

    def load_transfer(self, longitudinal_acceleration: float, mass: Kilograms) -> Newtons:
        """Vertical load moved from the front axle to the rear, N.

        Quasi-static: ``dN = m * a * h_cg / wheelbase``.  Positive under
        acceleration (load goes rearward), negative under braking.  Suspension
        response, damping, pitch and lateral transfer are Phase 12.
        """
        return mass * longitudinal_acceleration * self.cg_height / self.wheelbase

    def to_dict(self) -> dict[str, Any]:
        return {
            "chassis_mass": self.chassis_mass,
            "driver_mass": self.driver_mass,
            "wheelbase": self.wheelbase,
            "cg_height": self.cg_height,
            "weight_distribution_front": self.weight_distribution_front,
            "track_width": self.track_width,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MassProperties:
        known = set(cls.__slots__)
        unknown = set(data) - known
        if unknown:
            raise ConfigError(f"unknown mass key(s): {', '.join(sorted(unknown))}")
        return cls(**data)
