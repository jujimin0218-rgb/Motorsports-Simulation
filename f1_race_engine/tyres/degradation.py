"""Tyre degradation -- how a worn, hot tyre loses grip.

Two separate losses, because they behave differently.

**Wear** is recoverable only by fitting a new set, and it is *progressive*: a
tyre holds its performance and then falls away, rather than fading linearly.
The exponent above one is what produces the cliff a strategist plans around.

**Thermal damage** is what is left after a tyre has been cooked.  It does not
come back when the tyre cools down, which is precisely why overheating a set
early in a stint is so expensive.
"""

from __future__ import annotations

from ..core.config import TyreWearConfig
from ..core.interpolation import clamp

__all__ = ["thermal_damage_increment", "wear_grip_factor"]


def wear_grip_factor(wear: float, config: TyreWearConfig | None = None) -> float:
    """Grip multiplier from how much tread has gone."""
    cfg = config or TyreWearConfig()
    used = clamp(wear, 0.0, 1.0)
    return 1.0 - cfg.grip_loss_at_full_wear * used**cfg.grip_loss_exponent


def thermal_damage_increment(
    surface_temperature: float,
    optimal_temperature: float,
    temperature_window: float,
    dt: float,
    *,
    lap_reference: float = 90.0,
    config: TyreWearConfig | None = None,
) -> float:
    """Permanent grip lost over ``dt`` seconds spent above the window.

    ``lap_reference`` is the lap time the damage rate is quoted against, so the
    rate means "per lap spent one window above the optimum" regardless of how
    long a lap happens to be.
    """
    cfg = config or TyreWearConfig()
    if dt <= 0.0 or cfg.thermal_damage_rate <= 0.0:
        return 0.0
    excess = surface_temperature - (optimal_temperature + temperature_window)
    if excess <= 0.0:
        return 0.0
    severity = excess / max(temperature_window, 1e-6)
    return cfg.thermal_damage_rate * severity * (dt / lap_reference)
