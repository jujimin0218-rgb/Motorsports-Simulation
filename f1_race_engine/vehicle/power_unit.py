"""The power unit.

Phase 2 models what the powertrain can put on the road, in two regimes that
every car has:

* **torque limited** at low speed -- the drivetrain can only multiply torque so
  far, so tractive force is capped and roughly constant;
* **power limited** at high speed -- ``F = P / v``, so force falls as speed
  rises, which is why acceleration tails off long before drag alone would
  explain it.

.. code-block:: text

    F_drive(v) = min( T_wheel_max / r_wheel ,  P_max * eta / v )

That shape is right, and it is what the acceleration model needs.  What it does
*not* yet resolve is individual gears and the engine's torque curve: Phase 12
replaces ``peak_wheel_torque`` with real ratios and a real curve, behind this
same method.

ERS is deliberately absent.  It is a separate energy system with its own state,
harvesting and deployment limits (project rule 24), and it arrives in Phase 5 as
an additive term here -- never as a lap-time bonus.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..core.config import PowertrainConfig
from ..core.errors import ConfigError
from ..core.units import Metres, Newtons, Watts

__all__ = ["PowerUnitProperties", "PowerUnit"]


@dataclass(frozen=True, slots=True)
class PowerUnitProperties:
    """A car's powertrain."""

    max_power: Watts = 560_000.0
    """Peak crank power, W.  About 750 hp for the internal combustion engine
    alone; the electric contribution is Phase 5."""

    peak_wheel_torque: float = 4200.0
    """Maximum torque deliverable at the wheels, Nm.

    Stands in for the engine torque curve multiplied by the lowest usable gear
    ratio.  Phase 12 replaces it with the real thing."""

    wheel_radius: Metres = 0.36
    """Loaded rear wheel radius, m."""

    def __post_init__(self) -> None:
        if self.max_power <= 0.0:
            raise ConfigError("max_power must be positive")
        if self.peak_wheel_torque <= 0.0:
            raise ConfigError("peak_wheel_torque must be positive")
        if self.wheel_radius <= 0.0:
            raise ConfigError("wheel_radius must be positive")

    @property
    def max_tractive_force(self) -> Newtons:
        """Torque-limited ceiling on drive force, N."""
        return self.peak_wheel_torque / self.wheel_radius

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_power": self.max_power,
            "peak_wheel_torque": self.peak_wheel_torque,
            "wheel_radius": self.wheel_radius,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PowerUnitProperties:
        known = set(cls.__slots__)
        unknown = set(data) - known
        if unknown:
            raise ConfigError(f"unknown power unit key(s): {', '.join(sorted(unknown))}")
        return cls(**data)


class PowerUnit:
    """Delivers tractive force from the powertrain."""

    __slots__ = ("_properties", "_config")

    def __init__(
        self, properties: PowerUnitProperties, config: PowertrainConfig | None = None
    ) -> None:
        self._properties = properties
        self._config = config or PowertrainConfig()

    @property
    def properties(self) -> PowerUnitProperties:
        return self._properties

    @property
    def config(self) -> PowertrainConfig:
        return self._config

    @property
    def wheel_power(self) -> Watts:
        """Peak power reaching the road after drivetrain losses, W."""
        return self._properties.max_power * self._config.drivetrain_efficiency

    def tractive_force(self, speed: float, *, throttle: float = 1.0) -> Newtons:
        """Drive force available at ``speed``, N, before the traction limit.

        ``throttle`` scales the demand between 0 and 1.  The tyre's ability to
        put this down is a separate question, answered in
        :mod:`f1_race_engine.physics.longitudinal`.
        """
        if throttle <= 0.0:
            return 0.0
        effective_speed = max(speed, self._config.min_tractive_speed)
        power_limited = self.wheel_power / effective_speed
        torque_limited = self._properties.max_tractive_force
        return min(torque_limited, power_limited) * min(throttle, 1.0)

    def power_at_speed(self, speed: float, *, throttle: float = 1.0) -> Watts:
        """Power actually delivered to the road at ``speed``, W."""
        return self.tractive_force(speed, throttle=throttle) * speed

    @property
    def torque_limit_speed(self) -> float:
        """Speed, m/s, where the power limit takes over from the torque limit."""
        return self.wheel_power / self._properties.max_tractive_force
