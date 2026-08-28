"""Lap time from the speed profile.

Time follows from the profile by integration, and the integral is exact rather
than approximate.  Over a segment where acceleration is constant,

.. code-block:: text

    dt = 2 * ds / (v0 + v1)

which is what the profile's energy-based update already assumes, so the two are
consistent by construction.  Using ``ds / v_mean`` instead would bias every
braking zone.

What comes out is the **limit lap**: a perfect driver, exactly on the tyre
everywhere, with a fixed fuel load and fresh tyres.  That is the right Phase 3
answer -- it is the lap the car is capable of.  Phase 4 adds the driver, whose
imperfection and consistency move it, and Phase 5 adds the fuel burning off and
the tyres going away underneath it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from ..core.units import (
    Metres,
    MetresPerSecond,
    Seconds,
    format_lap_time,
    ms_to_kph,
)
from ..environment.conditions import AmbientConditions
from ..track.model import Track
from ..track.surface import TrackConditions
from ..tyres.state import TyreState
from ..vehicle.model import Vehicle
from .acceleration import AccelerationZone, acceleration_zones
from .braking import BrakingZone, braking_zones
from .longitudinal import longitudinal_forces
from .speed_profile import PerformanceLimits, SpeedProfile, compute_speed_profile

__all__ = ["LapTimeResult", "compute_lap_time", "format_lap_result"]


@dataclass(frozen=True)
class LapTimeResult:
    """A complete lap, with the metrics project rule 41 asks for."""

    track_name: str
    vehicle_name: str
    lap_time: Seconds
    sector_times: tuple[Seconds, ...]
    lap_length: Metres
    top_speed: MetresPerSecond
    minimum_speed: MetresPerSecond
    average_speed: MetresPerSecond
    max_lateral_g: float
    max_braking_g: float
    max_acceleration_g: float
    full_throttle_fraction: float
    """Fraction of the lap *distance* spent accelerating under power.

    Distance-weighted, and it counts any positive drive.  The time-weighted,
    pedal-at-100% figure teams quote is
    :attr:`~f1_race_engine.simulation.telemetry.Telemetry.full_throttle_fraction`,
    which comes out lower on the same lap and is the one to compare with real
    telemetry."""

    braking_fraction: float
    cornering_limited_fraction: float
    energy_delivered: float
    """Mechanical energy the powertrain put into the car over the lap, J.
    Phase 5 turns this into fuel consumed and energy harvested."""

    mean_power: float
    profile: SpeedProfile = field(repr=False)
    braking_zones: tuple[BrakingZone, ...] = field(default=(), repr=False)
    acceleration_zones: tuple[AccelerationZone, ...] = field(default=(), repr=False)

    @property
    def average_speed_kph(self) -> float:
        return ms_to_kph(self.average_speed)

    @property
    def formatted(self) -> str:
        return format_lap_time(self.lap_time)

    def to_dict(self, *, include_profile: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "track": self.track_name,
            "vehicle": self.vehicle_name,
            "lap_time": self.lap_time,
            "lap_time_formatted": self.formatted,
            "sector_times": list(self.sector_times),
            "lap_length": self.lap_length,
            "top_speed_kph": ms_to_kph(self.top_speed),
            "minimum_speed_kph": ms_to_kph(self.minimum_speed),
            "average_speed_kph": self.average_speed_kph,
            "max_lateral_g": self.max_lateral_g,
            "max_braking_g": self.max_braking_g,
            "max_acceleration_g": self.max_acceleration_g,
            "full_throttle_fraction": self.full_throttle_fraction,
            "braking_fraction": self.braking_fraction,
            "cornering_limited_fraction": self.cornering_limited_fraction,
            "energy_delivered": self.energy_delivered,
            "mean_power": self.mean_power,
            "braking_zones": [zone.to_dict() for zone in self.braking_zones],
            "acceleration_zones": [zone.to_dict() for zone in self.acceleration_zones],
        }
        if include_profile:
            payload["profile"] = self.profile.to_dict(include_samples=True)
        return payload

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"LapTimeResult({self.track_name!r}, {self.vehicle_name!r}, "
            f"{self.formatted})"
        )


def _segment_time(v0: float, v1: float, length: float) -> float:
    """Exact time across a segment of constant acceleration."""
    total = v0 + v1
    if total <= 0.0 or length <= 0.0:
        return 0.0
    return 2.0 * length / total


def _speed_at_fraction(v0: float, v1: float, fraction: float) -> float:
    squared = v0 * v0 + (v1 * v1 - v0 * v0) * fraction
    return math.sqrt(max(squared, 0.0))


def compute_lap_time(
    track: Track,
    vehicle: Vehicle,
    ambient: AmbientConditions | None = None,
    *,
    mass: float | None = None,
    tyre_state: TyreState | None = None,
    conditions: TrackConditions | None = None,
    limits: PerformanceLimits | None = None,
    profile: SpeedProfile | None = None,
    analyse_zones: bool = True,
) -> LapTimeResult:
    """Compute the limit lap for ``vehicle`` around ``track``.

    Pass ``profile`` to reuse one already computed; otherwise it is built here.
    """
    conditions_ = ambient or AmbientConditions()
    car_mass = vehicle.total_mass() if mass is None else mass
    tyres = tyre_state or TyreState()
    speed_profile = profile or compute_speed_profile(
        track,
        vehicle,
        conditions_,
        mass=car_mass,
        tyre_state=tyres,
        conditions=conditions,
        limits=limits,
    )

    count = len(speed_profile)
    boundaries = list(track.sector_boundaries)
    sector_times = [0.0] * (len(boundaries) + 1)

    lap_time = 0.0
    energy = 0.0
    full_throttle_distance = 0.0
    braking_distance = 0.0
    max_lateral = 0.0
    max_braking = 0.0
    max_acceleration = 0.0
    air_density = conditions_.air_density

    for i in range(count):
        nxt = (i + 1) % count
        v0, v1 = speed_profile.speed[i], speed_profile.speed[nxt]
        length = speed_profile.length[i]
        start = speed_profile.distance[i]
        acceleration = speed_profile.longitudinal_acceleration(i)

        max_lateral = max(max_lateral, speed_profile.lateral_acceleration(i))
        if acceleration < 0.0:
            max_braking = max(max_braking, -acceleration)
            braking_distance += length
        else:
            max_acceleration = max(max_acceleration, acceleration)

        # Split the segment across sector boundaries so the sector times add up
        # to the lap time exactly.
        cuts: list[float] = [0.0]
        for boundary in boundaries:
            if start < boundary < start + length:
                cuts.append((boundary - start) / length)
        cuts.append(1.0)
        for lower, upper in zip(cuts, cuts[1:]):
            if upper <= lower:
                continue
            piece_start = _speed_at_fraction(v0, v1, lower)
            piece_end = _speed_at_fraction(v0, v1, upper)
            piece_length = (upper - lower) * length
            piece_time = _segment_time(piece_start, piece_end, piece_length)
            lap_time += piece_time
            midpoint = start + (lower + upper) * 0.5 * length
            sector_times[track.sector_of(midpoint) - 1] += piece_time

        segment_time = _segment_time(v0, v1, length)
        mean_speed = 0.5 * (v0 + v1)

        # Energy the powertrain actually delivered over this segment.
        if acceleration > 0.0:
            forces = longitudinal_forces(
                vehicle,
                mean_speed,
                air_density,
                mass=car_mass,
                throttle=1.0,
                tyre_state=tyres,
                lateral_acceleration=speed_profile.lateral_acceleration(i),
                lateral_force_used=car_mass * speed_profile.lateral_acceleration(i),
            )
            energy += forces.drive * length
            if forces.drive > 0.0:
                full_throttle_distance += length

    average_speed = track.length / lap_time if lap_time > 0.0 else 0.0

    zones_braking: tuple[BrakingZone, ...] = ()
    zones_acceleration: tuple[AccelerationZone, ...] = ()
    if analyse_zones:
        zones_braking = tuple(braking_zones(speed_profile, track))
        zones_acceleration = tuple(
            acceleration_zones(
                speed_profile, track, vehicle, conditions_,
                mass=car_mass, tyre_state=tyres,
            )
        )

    return LapTimeResult(
        track_name=track.name,
        vehicle_name=vehicle.name,
        lap_time=lap_time,
        sector_times=tuple(sector_times),
        lap_length=track.length,
        top_speed=speed_profile.top_speed,
        minimum_speed=speed_profile.minimum_speed,
        average_speed=average_speed,
        max_lateral_g=max_lateral / 9.80665,
        max_braking_g=max_braking / 9.80665,
        max_acceleration_g=max_acceleration / 9.80665,
        full_throttle_fraction=full_throttle_distance / track.length,
        braking_fraction=braking_distance / track.length,
        cornering_limited_fraction=speed_profile.cornering_limited_fraction(),
        energy_delivered=energy,
        mean_power=energy / lap_time if lap_time > 0.0 else 0.0,
        profile=speed_profile,
        braking_zones=zones_braking,
        acceleration_zones=zones_acceleration,
    )


def format_lap_result(result: LapTimeResult) -> str:
    """Render a lap result as readable text (project rule 41)."""
    lines: list[str] = []
    lines.append("=" * 74)
    lines.append(f"LAP  --  {result.vehicle_name}  at  {result.track_name}")
    lines.append("=" * 74)
    lines.append(f"  lap time            {result.formatted:>14}")
    for index, sector in enumerate(result.sector_times, start=1):
        lines.append(f"    sector {index}          {sector:>14.3f} s")
    lines.append("")
    lines.append(f"  top speed           {ms_to_kph(result.top_speed):>11.1f} km/h")
    lines.append(f"  minimum speed       {ms_to_kph(result.minimum_speed):>11.1f} km/h")
    lines.append(f"  average speed       {result.average_speed_kph:>11.1f} km/h")
    lines.append("")
    lines.append(f"  max lateral         {result.max_lateral_g:>11.2f} g")
    lines.append(f"  max braking         {result.max_braking_g:>11.2f} g")
    lines.append(f"  max acceleration    {result.max_acceleration_g:>11.2f} g")
    lines.append("")
    lines.append(f"  full throttle       {result.full_throttle_fraction:>11.1%} of the lap")
    lines.append(f"  braking             {result.braking_fraction:>11.1%} of the lap")
    lines.append(
        f"  on the cornering limit{result.cornering_limited_fraction:>9.1%} of the lap"
    )
    lines.append(f"  mean power          {result.mean_power / 1000.0:>11.1f} kW")
    lines.append(f"  energy delivered    {result.energy_delivered / 1.0e6:>11.2f} MJ")

    if result.braking_zones:
        lines.append("")
        lines.append("  BRAKING ZONES")
        lines.append(
            f"    {'at m':>7}{'len m':>8}{'from':>9}{'to':>9}{'peak g':>9}  corner"
        )
        for zone in result.braking_zones:
            lines.append(
                f"    {zone.start_distance:>7.0f}{zone.length:>8.0f}"
                f"{ms_to_kph(zone.entry_speed):>9.0f}{ms_to_kph(zone.exit_speed):>9.0f}"
                f"{zone.peak_deceleration_g:>9.2f}  {zone.corner_name or ''}"
            )

    if result.acceleration_zones:
        lines.append("")
        lines.append("  ACCELERATION ZONES")
        lines.append(
            f"    {'at m':>7}{'len m':>8}{'from':>9}{'to':>9}{'peak g':>9}"
            f"{'tract. m':>10}  corner"
        )
        for zone in result.acceleration_zones:
            lines.append(
                f"    {zone.start_distance:>7.0f}{zone.length:>8.0f}"
                f"{ms_to_kph(zone.entry_speed):>9.0f}{ms_to_kph(zone.exit_speed):>9.0f}"
                f"{zone.peak_acceleration_g:>9.2f}"
                f"{zone.traction_limited_length:>10.0f}  {zone.corner_name or ''}"
            )
    lines.append("=" * 74)
    return "\n".join(lines)
