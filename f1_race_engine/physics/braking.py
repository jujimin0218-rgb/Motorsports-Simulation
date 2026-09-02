"""Braking zones.

Project rule 16 asks for the braking point, the braking distance, and the entry
and exit speeds of every braking event.  None of those is decided: they are
read out of the speed profile, which is where braking already happened as a
consequence of the tyres, the downforce, the mass and the gradient.

A braking zone is simply a run of the lap where the profile is falling.  Its
start is the braking point -- the last moment the driver could still have been
on the throttle -- and its end is the apex the braking was for.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..core.units import Metres, MetresPerSecond, ms_to_kph
from ..track.model import Track
from .speed_profile import SpeedProfile

__all__ = ["BrakingZone", "braking_zones"]


@dataclass(frozen=True, slots=True)
class BrakingZone:
    """One braking event."""

    start_distance: Metres
    """The braking point, m from the start/finish line."""

    end_distance: Metres
    """Where the deceleration ends -- the apex it was braking for."""

    entry_speed: MetresPerSecond
    exit_speed: MetresPerSecond
    peak_deceleration: float
    """Largest deceleration reached, m/s^2 (a positive number)."""

    mean_deceleration: float
    duration: float
    """Time spent braking, s."""

    corner_id: int | None = None
    corner_name: str | None = None

    @property
    def length(self) -> Metres:
        """Braking distance, m."""
        return self.end_distance - self.start_distance

    @property
    def speed_lost(self) -> MetresPerSecond:
        return self.entry_speed - self.exit_speed

    @property
    def peak_deceleration_g(self) -> float:
        return self.peak_deceleration / 9.80665

    def to_dict(self) -> dict[str, Any]:
        return {
            "start_distance": self.start_distance,
            "end_distance": self.end_distance,
            "length": self.length,
            "entry_speed": self.entry_speed,
            "entry_speed_kph": ms_to_kph(self.entry_speed),
            "exit_speed": self.exit_speed,
            "exit_speed_kph": ms_to_kph(self.exit_speed),
            "speed_lost_kph": ms_to_kph(self.speed_lost),
            "peak_deceleration": self.peak_deceleration,
            "peak_deceleration_g": self.peak_deceleration_g,
            "mean_deceleration": self.mean_deceleration,
            "duration": self.duration,
            "corner_id": self.corner_id,
            "corner_name": self.corner_name,
        }


def braking_zones(
    profile: SpeedProfile,
    track: Track | None = None,
    *,
    minimum_deceleration: float = 0.5,
    minimum_speed_loss: float = 2.0,
) -> list[BrakingZone]:
    """Find every braking zone in ``profile``.

    ``minimum_deceleration`` (m/s^2) filters out the gentle lift a car makes
    through a fast kink, which is not a braking zone in any useful sense.
    ``minimum_speed_loss`` (m/s) discards anything too small to matter.
    """
    count = len(profile)
    if count < 2:
        return []

    decelerating = [
        profile.longitudinal_acceleration(i) < -minimum_deceleration
        for i in range(count)
    ]
    if not any(decelerating):
        return []

    # Start scanning after a segment that is not braking, so a zone that spans
    # the start/finish line is found whole rather than split in two.
    try:
        origin = next(i for i in range(count) if not decelerating[i])
    except StopIteration:  # pragma: no cover - a lap cannot brake everywhere
        return []

    zones: list[BrakingZone] = []
    index = 0
    while index < count:
        i = (origin + index) % count
        if not decelerating[i]:
            index += 1
            continue

        run = [i]
        index += 1
        while index < count:
            j = (origin + index) % count
            if not decelerating[j]:
                break
            run.append(j)
            index += 1

        first, last = run[0], run[-1]
        end_node = (last + 1) % count
        start_distance = profile.distance[first]
        end_distance = start_distance + sum(profile.length[k] for k in run)

        decelerations = [-profile.longitudinal_acceleration(k) for k in run]
        entry = profile.speed[first]
        exit_speed = profile.speed[end_node]
        duration = sum(
            2.0 * profile.length[k]
            / (profile.speed[k] + profile.speed[(k + 1) % count])
            for k in run
        )
        distance = sum(profile.length[k] for k in run)

        if entry - exit_speed < minimum_speed_loss:
            continue

        corner_id = corner_name = None
        if track is not None:
            state = track.state_at(end_distance % track.length)
            corner_id, corner_name = state.corner_id, state.corner_name

        zones.append(
            BrakingZone(
                start_distance=start_distance,
                end_distance=end_distance,
                entry_speed=entry,
                exit_speed=exit_speed,
                peak_deceleration=max(decelerations),
                mean_deceleration=(
                    (entry * entry - exit_speed * exit_speed) / (2.0 * distance)
                    if distance > 0.0
                    else 0.0
                ),
                duration=duration,
                corner_id=corner_id,
                corner_name=corner_name,
            )
        )

    zones.sort(key=lambda zone: zone.start_distance)
    return zones
