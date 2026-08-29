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

Both of those regimes are really the same thing seen through a gearbox, and
Phase 12 replaces the stand-in with the real one.  A power unit makes its power
over a narrow band of crank speed; the gear set is how a car that has to go
from 60 km/h to 350 km/h keeps it there.  So:

.. code-block:: text

    F_drive(v) = P(rpm(v, gear)) * eta / v,  over the gear that gives the most

with no drive at all past the ratio's limit, because the engine has run out of
revolutions.  What was a flat torque cap and a hard speed ceiling is now the
engine's own curve and the top gear, and three things follow that a single
number could not give:

* force is not flat within a gear -- it rises and falls as the engine climbs
  its curve between shifts;
* top speed is a gear rather than a balance of forces, which is why a Formula 1
  car at Monza sits on the limiter instead of creeping towards a terminal
  velocity;
* shifting costs time, and it costs a short gear a real share of itself.

The torque a driveshaft can take is no longer a limit here either.  It never
was the thing stopping the car: what stops it off the line is the rear tyres,
and that limit already exists in :mod:`f1_race_engine.physics.longitudinal`.

ERS is deliberately absent.  It is a separate energy system with its own state,
harvesting and deployment limits (project rule 24), and it arrives in Phase 5 as
an additive term here -- never as a lap-time bonus.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from ..core.config import PowertrainConfig
from ..core.errors import ConfigError
from ..core.units import Metres, Newtons, Watts
from .gearbox import Gearbox, GearboxProperties, GearSelection

__all__ = ["PowerUnitProperties", "PowerUnit"]


@dataclass(frozen=True, slots=True)
class PowerUnitProperties:
    """A car's powertrain."""

    max_power: Watts = 560_000.0
    """Peak crank power, W.  About 750 hp for the internal combustion engine
    alone; the electric contribution is Phase 5."""

    wheel_radius: Metres = 0.36
    """Loaded rear wheel radius, m."""

    gearbox: GearboxProperties = field(default_factory=GearboxProperties)
    """The gear set and the engine curve behind it.

    Geared long for a low-drag circuit and short for a street one, which is a
    setup decision the model can express rather than a constant."""

    def __post_init__(self) -> None:
        if self.max_power <= 0.0:
            raise ConfigError("max_power must be positive")
        if self.wheel_radius <= 0.0:
            raise ConfigError("wheel_radius must be positive")


    def to_dict(self) -> dict[str, Any]:
        return {
            "max_power": self.max_power,
            "wheel_radius": self.wheel_radius,
            "gearbox": self.gearbox.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PowerUnitProperties:
        payload = dict(data)
        unknown = set(payload) - set(cls.__slots__)
        if unknown:
            raise ConfigError(f"unknown power unit key(s): {', '.join(sorted(unknown))}")
        if "gearbox" in payload:
            payload["gearbox"] = GearboxProperties.from_dict(payload["gearbox"])
        return cls(**payload)


class PowerUnit:
    """Delivers tractive force from the powertrain."""

    __slots__ = ("_properties", "_config", "_gearbox")

    def __init__(
        self, properties: PowerUnitProperties, config: PowertrainConfig | None = None
    ) -> None:
        self._properties = properties
        self._config = config or PowertrainConfig()
        self._gearbox = Gearbox(properties.gearbox, properties.wheel_radius)

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

    @property
    def gearbox(self) -> Gearbox:
        """The gear set, ready to be asked what a road speed is worth."""
        return self._gearbox

    def tractive_force(self, speed: float, *, throttle: float = 1.0) -> Newtons:
        """Drive force available at ``speed``, N, before the traction limit.

        ``throttle`` scales the demand between 0 and 1.  The tyre's ability to
        put this down is a separate question, answered in
        :mod:`f1_race_engine.physics.longitudinal`.
        """
        if throttle <= 0.0:
            return 0.0
        effective_speed = max(speed, self._config.min_tractive_speed)
        return (
            self._gearbox.tractive_force(effective_speed, self.wheel_power)
            * min(throttle, 1.0)
        )

    def gear_at(self, speed: float) -> GearSelection:
        """What gear the car is in at ``speed``, and what it is getting."""
        return self._gearbox.select(
            max(speed, self._config.min_tractive_speed), self.wheel_power
        )

    @property
    def maximum_speed(self) -> float:
        """Road speed on the limiter in top gear, m/s -- the car's ceiling."""
        return self._gearbox.maximum_speed

    def power_at_speed(self, speed: float, *, throttle: float = 1.0) -> Watts:
        """Power actually delivered to the road at ``speed``, W."""
        return self.tractive_force(speed, throttle=throttle) * speed

    @property
    def peak_force_speed(self) -> float:
        """Road speed, m/s, at which the car makes the most drive force.

        Bottom gear on its power peak: the fastest the car can be while still
        multiplying torque as hard as it can.
        """
        ratio = self._properties.gearbox.ratios[0]
        return (
            self._properties.gearbox.peak_power_rpm * 2.0 * math.pi / 60.0
            * self._properties.wheel_radius / ratio
        )
