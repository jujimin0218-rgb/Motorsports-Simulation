"""Tyre temperature (project rule 21).

A tyre only works inside a window.  Cold, it has no grip; too hot, the surface
goes off and it starts destroying itself.  Both ends have to come out of a
model of where the heat actually comes from and where it goes, or "warm-up" and
"overheating" become two more magic numbers.

Heat in is the work the tyre does: a small fraction of the frictional power at
the contact patch ends up in the tread, the rest going into the road and the
air.  Heat out is convection to the airstream -- which grows with speed, so a
car in traffic or in a slow corner cools its tyres less -- and conduction into
the track surface, which is why track temperature matters as much as air
temperature.

Two masses, not one.  The tread has a small heat capacity and responds in
seconds; the carcass has a large one and lags by laps.  That separation is what
produces the real behaviour where a tyre is up to temperature on the outside
after one lap and still cold underneath.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..core.config import TyreThermalConfig
from ..core.interpolation import clamp
from .compound import TyreCompound

__all__ = ["ThermalStep", "thermal_grip_factor", "update_temperatures"]


@dataclass(frozen=True, slots=True)
class ThermalStep:
    """The result of advancing the tyre temperatures over one step."""

    surface_temperature: float
    carcass_temperature: float
    heat_in: float
    """Frictional energy that entered the tread, J."""

    heat_out: float
    """Energy lost to air and track, J."""


def update_temperatures(
    *,
    surface_temperature: float,
    carcass_temperature: float,
    friction_force: float,
    speed: float,
    air_temperature: float,
    track_temperature: float,
    dt: float,
    hysteresis: float = 1.0,
    config: TyreThermalConfig | None = None,
) -> ThermalStep:
    """Advance the tread and carcass temperatures by ``dt`` seconds.

    ``friction_force`` is the total friction the tyres are actually generating,
    longitudinal and lateral combined -- a car cruising in a straight line barely
    heats its tyres, and one on the limit through a long corner heats them hard.

    ``hysteresis`` scales the share of that work which stays in the rubber.
    Softer compounds lose more energy internally, so they heat faster; the
    caller derives the figure from the compound rather than the model assuming
    every tyre is the same.
    """
    cfg = config or TyreThermalConfig()
    if dt <= 0.0:
        return ThermalStep(surface_temperature, carcass_temperature, 0.0, 0.0)

    # Frictional power, of which only a small share reaches the rubber.
    heat_in = (
        cfg.work_coefficient
        * max(hysteresis, 0.0)
        * abs(friction_force)
        * max(speed, 0.0)
    )

    convection = (cfg.convection_base + cfg.convection_speed * max(speed, 0.0)) * (
        surface_temperature - air_temperature
    )
    conduction = cfg.track_conduction * (surface_temperature - track_temperature)
    internal = cfg.internal_conduction * (surface_temperature - carcass_temperature)

    surface_rate = (heat_in - convection - conduction - internal) / cfg.surface_heat_capacity
    carcass_rate = (
        internal - 0.25 * cfg.convection_base * (carcass_temperature - air_temperature)
    ) / cfg.carcass_heat_capacity

    # Explicit Euler is fine here -- the tread's time constant is seconds and a
    # step is milliseconds -- but clamp the change so a pathological step size
    # can never make the model blow up (project rule 26).
    surface = surface_temperature + clamp(surface_rate * dt, -25.0, 25.0)
    carcass = carcass_temperature + clamp(carcass_rate * dt, -25.0, 25.0)

    return ThermalStep(
        surface_temperature=clamp(surface, -20.0, 260.0),
        carcass_temperature=clamp(carcass, -20.0, 220.0),
        heat_in=heat_in * dt,
        heat_out=(convection + conduction) * dt,
    )


def thermal_grip_factor(
    compound: TyreCompound,
    surface_temperature: float,
    config: TyreThermalConfig | None = None,
) -> float:
    """Grip multiplier from temperature alone.

    A quadratic well centred on the compound's optimum: 1.0 in the middle,
    falling away by ``grip_falloff`` at one window half-width, and floored so a
    cold tyre still has some grip rather than none.
    """
    cfg = config or TyreThermalConfig()
    offset = (surface_temperature - compound.optimal_temperature) / compound.temperature_window
    return clamp(1.0 - cfg.grip_falloff * offset * offset, cfg.min_thermal_grip, 1.0)
