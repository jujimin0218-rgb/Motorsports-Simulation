"""Ambient conditions.

Aerodynamic force is proportional to air density, so the atmosphere is not a
cosmetic detail: the same car makes measurably less downforce on a hot day in
Bahrain than on a cold one at Spa, and its top speed rises as its cornering
speed falls.  Getting that from real physics rather than a per-race constant is
exactly what project rule 2.3 demands.

Density comes from the ideal gas law with a humidity correction:

.. code-block:: text

    rho = (p_dry / (R_dry * T)) + (p_vapour / (R_vapour * T))

Moist air is *less* dense than dry air, because a water molecule is lighter
than the nitrogen or oxygen it displaces -- which surprises people, and is why
the correction is worth carrying rather than assuming dry air.

Phase 1 shipped a static reference density.  This module replaces it with a
computed one.  Phase 10 adds wind, rain and time evolution on top; the
interface a consumer sees does not change.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from ..core.errors import ConfigError
from ..core.units import (
    Celsius,
    Kelvin,
    Pascals,
    celsius_to_kelvin,
)

__all__ = ["AmbientConditions", "air_density", "saturation_vapour_pressure"]

#: Specific gas constant for dry air, J/(kg*K).
DRY_AIR_GAS_CONSTANT: float = 287.058

#: Specific gas constant for water vapour, J/(kg*K).
WATER_VAPOUR_GAS_CONSTANT: float = 461.495


def saturation_vapour_pressure(temperature_c: Celsius) -> Pascals:
    """Saturation vapour pressure of water, Pa (Magnus-Tetens)."""
    return 610.94 * math.exp(
        17.625 * temperature_c / (temperature_c + 243.04)
    )


def air_density(
    temperature_c: Celsius, pressure_pa: Pascals, relative_humidity: float = 0.0
) -> float:
    """Density of moist air, kg/m^3.

    ``relative_humidity`` is a fraction in ``[0, 1]``.
    """
    temperature_k: Kelvin = celsius_to_kelvin(temperature_c)
    if temperature_k <= 0.0:
        raise ConfigError(f"temperature {temperature_c} degC is below absolute zero")
    if pressure_pa <= 0.0:
        raise ConfigError(f"pressure must be positive, got {pressure_pa} Pa")
    vapour = max(0.0, min(relative_humidity, 1.0)) * saturation_vapour_pressure(
        temperature_c
    )
    vapour = min(vapour, pressure_pa)
    dry = pressure_pa - vapour
    return dry / (DRY_AIR_GAS_CONSTANT * temperature_k) + vapour / (
        WATER_VAPOUR_GAS_CONSTANT * temperature_k
    )


@dataclass(frozen=True, slots=True)
class AmbientConditions:
    """The state of the atmosphere and the track surface for one session.

    Immutable: a session that evolves (Phase 10) produces a new instance rather
    than mutating a shared one, so a result recorded at lap 12 keeps the
    conditions it was actually run under.
    """

    air_temperature: Celsius = 25.0
    track_temperature: Celsius = 35.0
    """Track surface temperature.  Typically 10-20 K above air temperature in
    sunshine; it drives tyre behaviour from Phase 5."""

    pressure: Pascals = 101_325.0
    relative_humidity: float = 0.4
    wind_speed: float = 0.0
    """Wind speed, m/s.  Carried now so the interface is stable; the aero model
    starts using it in Phase 10."""

    wind_direction: float = 0.0
    """Wind direction, radians, in the track's plan-view frame."""

    rain_intensity: float = 0.0
    """0 (dry) to 1 (torrential).  Drives the wet-grip path from Phase 10."""

    def __post_init__(self) -> None:
        if not -60.0 <= self.air_temperature <= 70.0:
            raise ConfigError(
                f"air temperature {self.air_temperature} degC is implausible"
            )
        if not -60.0 <= self.track_temperature <= 90.0:
            raise ConfigError(
                f"track temperature {self.track_temperature} degC is implausible"
            )
        if self.pressure <= 0.0:
            raise ConfigError(f"pressure must be positive, got {self.pressure} Pa")
        if not 0.0 <= self.relative_humidity <= 1.0:
            raise ConfigError(
                f"relative humidity must lie in [0, 1], got {self.relative_humidity}"
            )
        if self.wind_speed < 0.0:
            raise ConfigError("wind speed must be non-negative")
        if not 0.0 <= self.rain_intensity <= 1.0:
            raise ConfigError("rain intensity must lie in [0, 1]")

    @property
    def air_density(self) -> float:
        """Density of the air the car is driving through, kg/m^3."""
        return air_density(
            self.air_temperature, self.pressure, self.relative_humidity
        )

    @property
    def is_wet(self) -> bool:
        return self.rain_intensity > 0.0

    def dynamic_pressure(self, speed: float) -> Pascals:
        """``0.5 * rho * v^2`` -- the quantity every aero force scales with."""
        return 0.5 * self.air_density * speed * speed

    def to_dict(self) -> dict[str, Any]:
        return {
            "air_temperature": self.air_temperature,
            "track_temperature": self.track_temperature,
            "pressure": self.pressure,
            "relative_humidity": self.relative_humidity,
            "air_density": self.air_density,
            "wind_speed": self.wind_speed,
            "wind_direction": self.wind_direction,
            "rain_intensity": self.rain_intensity,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AmbientConditions:
        known = {
            "air_temperature", "track_temperature", "pressure",
            "relative_humidity", "wind_speed", "wind_direction", "rain_intensity",
        }
        return cls(**{k: v for k, v in data.items() if k in known})

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"AmbientConditions(air={self.air_temperature:.1f}C, "
            f"track={self.track_temperature:.1f}C, "
            f"rho={self.air_density:.4f} kg/m^3)"
        )
