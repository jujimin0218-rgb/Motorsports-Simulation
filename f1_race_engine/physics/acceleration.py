"""Acceleration zones.

Project rule 17 asks that corner exit and straight-line acceleration behave
differently, and they do -- for a reason that falls out of the model rather
than being written into it.

Leaving a slow corner the car is **traction limited**: the rear tyres cannot
put the available torque down, and downforce is too small to help. Halfway
down a straight it is **power limited**: there is grip to spare and the engine
simply has no more to give at that speed. Each zone below reports how much of
it was spent in each regime, which is the clearest single read-out of what a
corner exit is asking of a car.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..core.units import Metres, MetresPerSecond, ms_to_kph
from ..environment.conditions import AmbientConditions
from ..track.model import Track
from ..tyres.state import TyreState
from ..vehicle.model import Vehicle
from .longitudinal import traction_limited_force
from .speed_profile import SpeedProfile

__all__ = ["AccelerationZone", "acceleration_zones"]


@dataclass(frozen=True, slots=True)
class AccelerationZone:
    """One run of the lap spent accelerating."""

    start_distance: Metres
    end_distance: Metres
    entry_speed: MetresPerSecond
    exit_speed: MetresPerSecond
    peak_acceleration: float
    duration: float
    traction_limited_length: Metres
    """Distance over which the rear tyres, not the engine, were the limit."""

    corner_id: int | None = None
    corner_name: str | None = None

    @property
    def length(self) -> Metres:
        return self.end_distance - self.start_distance

    @property
    def speed_gained(self) -> MetresPerSecond:
        return self.exit_speed - self.entry_speed

    @property
    def peak_acceleration_g(self) -> float:
        return self.peak_acceleration / 9.80665

    @property
    def traction_limited_fraction(self) -> float:
        if self.length <= 0.0:
            return 0.0
        return self.traction_limited_length / self.length

    def to_dict(self) -> dict[str, Any]:
        return {
            "start_distance": self.start_distance,
            "end_distance": self.end_distance,
            "length": self.length,
            "entry_speed_kph": ms_to_kph(self.entry_speed),
            "exit_speed_kph": ms_to_kph(self.exit_speed),
            "speed_gained_kph": ms_to_kph(self.speed_gained),
            "peak_acceleration": self.peak_acceleration,
            "peak_acceleration_g": self.peak_acceleration_g,
            "duration": self.duration,
            "traction_limited_length": self.traction_limited_length,
            "traction_limited_fraction": self.traction_limited_fraction,
            "corner_id": self.corner_id,
            "corner_name": self.corner_name,
        }


def acceleration_zones(
    profile: SpeedProfile,
    track: Track | None = None,
    vehicle: Vehicle | None = None,
    ambient: AmbientConditions | None = None,
    *,
    mass: float | None = None,
    tyre_state: TyreState | None = None,
    minimum_acceleration: float = 0.5,
    minimum_speed_gain: float = 2.0,
) -> list[AccelerationZone]:
    """Find every acceleration zone in ``profile``.

    Pass ``vehicle`` to have each zone report how much of it was traction
    limited rather than power limited.
    """
    count = len(profile)
    if count < 2:
        return []

    accelerating = [
        profile.longitudinal_acceleration(i) > minimum_acceleration
        for i in range(count)
    ]
    if not any(accelerating):
        return []
    try:
        origin = next(i for i in range(count) if not accelerating[i])
    except StopIteration:  # pragma: no cover
        return []

    conditions = ambient or AmbientConditions()
    air_density = conditions.air_density
    car_mass = (
        mass if mass is not None else (vehicle.total_mass() if vehicle else 0.0)
    )
    tyres = tyre_state or TyreState()

    zones: list[AccelerationZone] = []
    index = 0
    while index < count:
        i = (origin + index) % count
        if not accelerating[i]:
            index += 1
            continue

        run = [i]
        index += 1
        while index < count:
            j = (origin + index) % count
            if not accelerating[j]:
                break
            run.append(j)
            index += 1

        first, last = run[0], run[-1]
        end_node = (last + 1) % count
        start_distance = profile.distance[first]
        end_distance = start_distance + sum(profile.length[k] for k in run)
        entry = profile.speed[first]
        exit_speed = profile.speed[end_node]

        if exit_speed - entry < minimum_speed_gain:
            continue

        duration = sum(
            2.0 * profile.length[k]
            / (profile.speed[k] + profile.speed[(k + 1) % count])
            for k in run
        )

        traction_limited = 0.0
        if vehicle is not None:
            for k in run:
                speed = profile.speed[k]
                lateral = car_mass * speed * speed * abs(profile.curvature[k])
                powertrain = vehicle.power_unit.tractive_force(speed)
                traction = traction_limited_force(
                    vehicle,
                    speed,
                    air_density,
                    mass=car_mass,
                    tyre_state=tyres,
                    lateral_force_used=lateral,
                )
                if traction < powertrain:
                    traction_limited += profile.length[k]

        corner_id = corner_name = None
        if track is not None:
            state = track.state_at(start_distance % track.length)
            corner_id, corner_name = state.corner_id, state.corner_name

        zones.append(
            AccelerationZone(
                start_distance=start_distance,
                end_distance=end_distance,
                entry_speed=entry,
                exit_speed=exit_speed,
                peak_acceleration=max(
                    profile.longitudinal_acceleration(k) for k in run
                ),
                duration=duration,
                traction_limited_length=traction_limited,
                corner_id=corner_id,
                corner_name=corner_name,
            )
        )

    zones.sort(key=lambda zone: zone.start_distance)
    return zones
