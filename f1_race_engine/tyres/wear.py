"""Tyre wear (project rule 22).

    "타이어 열화는 단순히 매 랩 일정한 시간을 더하는 방식으로 만들지 않는다."

Wear here is the accumulation of *work*: the frictional energy the tyre has
dissipated, scaled by how hot it was while doing it and by the compound's own
durability.  Nothing counts laps.

That single choice produces the behaviour a strategist cares about:

* a slow, twisty circuit wears tyres faster than a fast one at the same lap
  count, because the tyre does more work per lap;
* pushing wears more than cruising, because commitment raises the friction
  force;
* overheating is far worse than merely using the tyre, because the thermal
  term is raised to a power above one;
* a driver good at tyre management genuinely makes a set last longer.
"""

from __future__ import annotations

from ..core.config import TyreWearConfig
from ..core.interpolation import clamp
from .compound import TyreCompound

__all__ = ["management_factor", "thermal_wear_factor", "wear_increment"]


def management_factor(tyre_management: float, config: TyreWearConfig | None = None) -> float:
    """Wear multiplier from a driver's tyre management ability."""
    cfg = config or TyreWearConfig()
    return 1.0 - cfg.management_range * clamp(tyre_management, 0.0, 1.0)


def thermal_wear_factor(
    compound: TyreCompound,
    surface_temperature: float,
    config: TyreWearConfig | None = None,
) -> float:
    """Wear multiplier from temperature.

    At or below its optimum the tyre wears at its reference rate.  Above it,
    wear climbs steeply and keeps climbing -- which is what makes overheating a
    tyre a strategic disaster rather than a small inefficiency.  Measuring the
    excess from the optimum rather than from the edge of the window is
    deliberate: rubber does not wear at one flat rate right up to a cliff.
    """
    cfg = config or TyreWearConfig()
    excess = surface_temperature - compound.optimal_temperature
    if excess <= 0.0:
        return 1.0
    return (1.0 + excess / compound.temperature_window) ** cfg.thermal_wear_exponent


def wear_increment(
    compound: TyreCompound,
    *,
    friction_force: float,
    distance: float,
    surface_temperature: float,
    tyre_management: float = 0.85,
    config: TyreWearConfig | None = None,
) -> float:
    """Fraction of the tread used up over one step.

    The frictional work done is ``friction_force * distance``; dividing by the
    energy a reference compound survives gives the share of its life used.
    """
    cfg = config or TyreWearConfig()
    if distance <= 0.0:
        return 0.0
    energy = abs(friction_force) * distance
    base = energy / cfg.reference_wear_energy
    return (
        base
        * compound.wear_rate
        * thermal_wear_factor(compound, surface_temperature, cfg)
        * management_factor(tyre_management, cfg)
    )
