"""The pit lane, and what a stop actually costs (project rule 32).

    "피트스탑 시간 손실은 상수로 두지 않는다."

So there is no constant here.  A stop costs whatever the difference is between
two journeys between the same two points on the circuit:

* the one through the pit lane -- brake to the limit, run the lane at the
  limit, stop, get going again, rejoin;
* the one the car would have made on the racing line, which the car's own speed
  profile already answers exactly.

That subtraction is the whole model, and it gives every behaviour a strategist
needs without any of them being written down:

* a stop costs more at a circuit with a long pit lane, and less at one with a
  short one;
* it costs more at a fast circuit than a slow one, because the road the pit
  lane replaces would have gone by quicker;
* raising the speed limit makes stops cheaper, and so does a quicker crew, and
  the two are separate numbers because they are separate things;
* a car with better acceleration loses less getting back up to speed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..core.errors import ConfigError
from ..core.units import Metres, MetresPerSecond, Seconds
from ..environment.conditions import AmbientConditions
from ..physics.longitudinal import longitudinal_forces
from ..physics.speed_profile import SpeedProfile
from ..tyres.state import TyreState
from ..vehicle.model import Vehicle

__all__ = ["PitLane", "PitLoss", "pit_loss"]


@dataclass(frozen=True, slots=True)
class PitLane:
    """A circuit's pit lane.  Geometry and regulations, nothing derived."""

    entry_distance: Metres
    """Where the pit road leaves the circuit, in lap coordinates."""

    exit_distance: Metres
    """Where it rejoins."""

    length: Metres
    """Road distance from entry to exit through the lane."""

    speed_limit: MetresPerSecond = 22.22
    """80 km/h, the usual race limit."""

    stationary_time: Seconds = 2.4
    """How long the car is stopped for a tyre change.  A crew's number."""

    def __post_init__(self) -> None:
        if self.length <= 0.0:
            raise ConfigError("pit lane length must be positive")
        if self.speed_limit <= 0.0:
            raise ConfigError("pit lane speed limit must be positive")
        if self.stationary_time < 0.0:
            raise ConfigError("stationary time must be non-negative")

    @property
    def bypassed_distance(self) -> Metres:
        """Track distance between the entry and the exit, in lap coordinates."""
        return self.exit_distance - self.entry_distance

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_distance": self.entry_distance,
            "exit_distance": self.exit_distance,
            "length": self.length,
            "speed_limit": self.speed_limit,
            "stationary_time": self.stationary_time,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PitLane:
        unknown = set(data) - set(cls.__slots__)
        if unknown:
            raise ConfigError(f"unknown pit lane key(s): {', '.join(sorted(unknown))}")
        return cls(**data)

    @classmethod
    def for_track(cls, track_length: Metres, **overrides: Any) -> PitLane:
        """A plausible pit lane for a circuit that does not describe one.

        Placed along the start/finish straight and scaled with the circuit, so
        a synthetic track gets something defensible rather than nothing.  A
        real circuit should carry its own measurements.
        """
        length = overrides.pop("length", max(300.0, min(0.09 * track_length, 500.0)))
        entry = overrides.pop("entry_distance", max(track_length - length * 0.6, 0.0))
        exit_distance = overrides.pop("exit_distance", min(entry + length * 0.9, track_length))
        return cls(
            entry_distance=entry,
            exit_distance=exit_distance,
            length=length,
            **overrides,
        )


@dataclass(frozen=True, slots=True)
class PitLoss:
    """What a stop costs, and where the cost came from."""

    total: Seconds
    """Time lost against staying on the circuit."""

    lane_time: Seconds
    """Time from entry to exit through the pit lane, stop included."""

    track_time: Seconds
    """Time the same journey would have taken on the racing line."""

    stationary: Seconds

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "lane_time": self.lane_time,
            "track_time": self.track_time,
            "stationary": self.stationary,
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"PitLoss({self.total:.2f} s, {self.stationary:.2f} s stationary)"


def pit_loss(
    vehicle: Vehicle,
    lane: PitLane,
    profile: SpeedProfile,
    *,
    ambient: AmbientConditions | None = None,
    mass: float | None = None,
    tyre_state: TyreState | None = None,
    surface_grip: float = 1.0,
    water_depth: float = 0.0,
    stationary_time: Seconds | None = None,
) -> PitLoss:
    """Time lost by pitting, in seconds.

    The pit-lane journey is integrated with the same force model as everything
    else: the car brakes from racing speed to the limit, runs the lane, stops,
    and accelerates back out.  The alternative is read straight off the car's
    own speed profile.  Neither is a constant, and the difference between two
    circuits comes out of their geometry.
    """
    conditions = ambient or AmbientConditions()
    car_mass = vehicle.total_mass() if mass is None else mass
    tyres = tyre_state or TyreState()
    stop = lane.stationary_time if stationary_time is None else stationary_time

    entry_speed = profile.speed_at(lane.entry_distance)
    exit_speed = profile.speed_at(lane.exit_distance)

    # Slowing to the limit, then getting back to it after the stop, then back
    # up to racing speed at the exit.  All three come out of the car's own
    # longitudinal capability rather than a table.
    braking = _distance_to_slow(
        vehicle, entry_speed, lane.speed_limit, conditions, car_mass, tyres,
        surface_grip, water_depth,
    )
    from_rest = _accelerate(
        vehicle, 0.0, lane.speed_limit, conditions, car_mass, tyres,
        surface_grip, water_depth,
    )
    rejoin = _accelerate(
        vehicle, lane.speed_limit, exit_speed, conditions, car_mass, tyres,
        surface_grip, water_depth,
    )

    # The lane itself, entry to exit: brake in, cruise, stop, get going again.
    cruising = max(lane.length - braking.distance - from_rest.distance, 0.0)
    lane_time = braking.time + cruising / lane.speed_limit + stop + from_rest.time
    track_time = profile.time_between(lane.entry_distance, lane.exit_distance)

    # Rejoining is not free either: the car leaves the pit exit at the limit
    # and has to get back to racing speed on a piece of road it would have
    # covered flat out.  That happens after the exit, so it is charged
    # separately rather than eating into the lane.
    rejoin_penalty = 0.0
    if rejoin.distance > 0.0:
        on_track = profile.time_between(
            lane.exit_distance, lane.exit_distance + rejoin.distance
        )
        rejoin_penalty = max(rejoin.time - on_track, 0.0)

    return PitLoss(
        total=lane_time - track_time + rejoin_penalty,
        lane_time=lane_time,
        track_time=track_time,
        stationary=stop,
    )


@dataclass(frozen=True, slots=True)
class _Segment:
    time: Seconds
    distance: Metres


def _accelerate(
    vehicle: Vehicle,
    start: float,
    target: float,
    ambient: AmbientConditions,
    mass: float,
    tyres: TyreState,
    surface_grip: float,
    water_depth: float,
    steps: int = 60,
) -> _Segment:
    """Accelerate from ``start`` to ``target``, returning time and distance."""
    if target <= start:
        return _Segment(0.0, 0.0)
    air_density = ambient.air_density
    step = (target - start) / steps
    time = distance = 0.0
    speed = start
    for _ in range(steps):
        mid = speed + 0.5 * step
        forces = longitudinal_forces(
            vehicle, max(mid, 0.5), air_density, mass=mass, throttle=1.0,
            tyre_state=tyres, surface_grip=surface_grip, water_depth=water_depth,
        )
        acceleration = max(forces.acceleration, 0.05)
        dt = step / acceleration
        time += dt
        distance += mid * dt
        speed += step
    return _Segment(time, distance)


def _distance_to_slow(
    vehicle: Vehicle,
    start: float,
    target: float,
    ambient: AmbientConditions,
    mass: float,
    tyres: TyreState,
    surface_grip: float,
    water_depth: float,
    steps: int = 60,
) -> _Segment:
    """Brake from ``start`` down to ``target``."""
    if start <= target:
        return _Segment(0.0, 0.0)
    air_density = ambient.air_density
    step = (start - target) / steps
    time = distance = 0.0
    speed = start
    for _ in range(steps):
        mid = speed - 0.5 * step
        forces = longitudinal_forces(
            vehicle, max(mid, 0.5), air_density, mass=mass, brake=1.0,
            tyre_state=tyres, surface_grip=surface_grip, water_depth=water_depth,
        )
        deceleration = max(-forces.acceleration, 0.05)
        dt = step / deceleration
        time += dt
        distance += mid * dt
        speed -= step
    return _Segment(time, distance)
