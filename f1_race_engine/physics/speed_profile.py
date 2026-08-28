"""The speed profile -- how fast the car can be at every point of the lap.

Project rule 15.  This is the piece that turns a circuit and a car into a lap,
and it is built the way real lap-time simulation is built:

.. code-block:: text

    Track -> curvature -> cornering limit
                              |
                    +---------+---------+
                    |                   |
              backward pass        forward pass
             (what braking          (what the engine
              allows into it)        allows out of it)
                    |                   |
                    +---------+---------+
                              |
                       final speed profile  =  the minimum of all three

No corner is given an average speed.  The cornering limit comes from the
tyres, the downforce and the mass; the braking limit from what the tyres can
shed on the way in; the acceleration limit from what the powertrain and the
rear tyres can deliver on the way out.  Where those three curves intersect is
where the apex is, and nobody had to say so.

**Why two passes.**  The speed at a point is constrained from both directions.
A slow corner limits how fast you may still be *arriving* (you must have braked
already) and how fast you can *have got* to the next one (you have to
accelerate from the apex).  One sweep can only propagate one of those.

**Why they wrap.**  A lap is a loop.  A braking zone can start before the
start/finish line, so the sweeps run repeatedly around the lap until nothing
changes -- which is what makes the answer independent of where the lap happens
to be cut.

**Combined grip is respected throughout.**  A car turning at 80% of its lateral
limit has only the remainder of the friction circle left for braking or
traction, so the passes ask the tyre model what is actually available rather
than assuming a free longitudinal budget.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from ..core.config import SimulationConfig, SpeedProfileConfig
from ..core.errors import ConfigError
from ..core.interpolation import clamp
from ..core.units import Metres, MetresPerSecond
from ..environment.conditions import AmbientConditions
from ..track.model import Track
from ..track.surface import TrackConditions
from ..tyres.state import TyreState
from ..vehicle.model import Vehicle
from .lateral import corner_speed_limit
from .longitudinal import longitudinal_forces

__all__ = [
    "PerformanceLimits",
    "SpeedProfile",
    "compute_speed_profile",
    "cornering_limits",
]


@dataclass(frozen=True, slots=True)
class PerformanceLimits:
    """How much of the car's capability is actually used.

    All three default to 1.0, which gives the **limit lap**: a perfect driver
    who is exactly on the tyre at every point.  This is the seam where the
    driver model attaches in Phase 4 (project rules 16 and 18) -- a driver with
    weaker braking runs ``braking`` below 1, and the braking points move
    earlier on their own.

    Each factor scales the *grip the driver is willing to use*, not the grip
    the tyre has, which is why they are applied per axis rather than as one
    number.
    """

    cornering: float = 1.0
    braking: float = 1.0
    traction: float = 1.0

    def __post_init__(self) -> None:
        for name in ("cornering", "braking", "traction"):
            value = getattr(self, name)
            if not 0.0 < value <= 1.0:
                raise ConfigError(
                    f"PerformanceLimits.{name} must lie in (0, 1], got {value}"
                )

    @property
    def is_ideal(self) -> bool:
        return self.cornering == self.braking == self.traction == 1.0

    def to_dict(self) -> dict[str, float]:
        return {
            "cornering": self.cornering,
            "braking": self.braking,
            "traction": self.traction,
        }


@dataclass(frozen=True, slots=True)
class SpeedProfile:
    """Speed as a function of distance around one lap.

    Values are held at **nodes**, one per track segment, with node ``i`` at the
    start of segment ``i``.  Segment ``i`` spans from node ``i`` to node
    ``i + 1`` (wrapping at the start/finish line).
    """

    track_name: str
    vehicle_name: str
    lap_length: Metres
    distance: tuple[float, ...]
    length: tuple[float, ...]
    curvature: tuple[float, ...]
    corner_limit: tuple[float, ...]
    """Speed the tyres allow through each point, ignoring how the car got
    there.  The final profile is at or below this everywhere."""

    speed: tuple[float, ...]
    passes: int
    converged: bool
    limits: PerformanceLimits

    def __len__(self) -> int:
        return len(self.speed)

    # -- summary -------------------------------------------------------------

    @property
    def top_speed(self) -> MetresPerSecond:
        return max(self.speed)

    @property
    def minimum_speed(self) -> MetresPerSecond:
        return min(self.speed)

    @property
    def top_speed_distance(self) -> Metres:
        index = max(range(len(self.speed)), key=lambda i: self.speed[i])
        return self.distance[index]

    @property
    def minimum_speed_distance(self) -> Metres:
        index = min(range(len(self.speed)), key=lambda i: self.speed[i])
        return self.distance[index]

    def cornering_limited_fraction(self, tolerance: float = 0.02) -> float:
        """Fraction of the lap spent at the cornering limit.

        ``tolerance`` is relative: the default counts anything within 2% of the
        limit.  Some slack is necessary because a car cannot sit exactly on the
        pure lateral limit -- with the whole friction circle spent on cornering
        there is nothing left to overcome drag, so it settles just below.

        High on a twisty circuit, low on a power circuit: a direct read-out of
        what a track asks of a car.
        """
        if not self.speed:
            return 0.0
        on_limit = sum(
            length
            for speed, limit, length in zip(self.speed, self.corner_limit, self.length)
            if speed >= limit * (1.0 - tolerance)
        )
        return on_limit / self.lap_length

    # -- queries -------------------------------------------------------------

    def index_at(self, distance: Metres) -> int:
        """Node index at or before ``distance`` (wrapping)."""
        wrapped = distance % self.lap_length
        low, high = 0, len(self.distance) - 1
        if wrapped >= self.distance[high]:
            return high
        while low < high:
            mid = (low + high + 1) // 2
            if self.distance[mid] <= wrapped:
                low = mid
            else:
                high = mid - 1
        return low

    def speed_at(self, distance: Metres) -> MetresPerSecond:
        """Speed at ``distance``, interpolated within the segment.

        Interpolation is on ``v^2``, because that is what varies linearly under
        constant acceleration -- interpolating ``v`` itself would bias every
        braking zone.
        """
        index = self.index_at(distance)
        wrapped = distance % self.lap_length
        length = self.length[index]
        if length <= 0.0:
            return self.speed[index]
        fraction = clamp((wrapped - self.distance[index]) / length, 0.0, 1.0)
        start = self.speed[index] ** 2
        end = self.speed[(index + 1) % len(self.speed)] ** 2
        return math.sqrt(max(start + (end - start) * fraction, 0.0))

    def lateral_acceleration(self, index: int) -> float:
        """Lateral acceleration at node ``index``, m/s^2."""
        return self.speed[index] ** 2 * abs(self.curvature[index])

    def longitudinal_acceleration(self, index: int) -> float:
        """Longitudinal acceleration across segment ``index``, m/s^2."""
        length = self.length[index]
        if length <= 0.0:
            return 0.0
        nxt = (index + 1) % len(self.speed)
        return (self.speed[nxt] ** 2 - self.speed[index] ** 2) / (2.0 * length)

    def to_dict(self, *, include_samples: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "track": self.track_name,
            "vehicle": self.vehicle_name,
            "lap_length": self.lap_length,
            "nodes": len(self.speed),
            "top_speed": self.top_speed,
            "minimum_speed": self.minimum_speed,
            "top_speed_distance": self.top_speed_distance,
            "minimum_speed_distance": self.minimum_speed_distance,
            "cornering_limited_fraction": self.cornering_limited_fraction(),
            "passes": self.passes,
            "converged": self.converged,
            "limits": self.limits.to_dict(),
        }
        if include_samples:
            payload["samples"] = [
                {
                    "distance": d,
                    "speed": v,
                    "corner_limit": c,
                    "curvature": k,
                }
                for d, v, c, k in zip(
                    self.distance, self.speed, self.corner_limit, self.curvature
                )
            ]
        return payload

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"SpeedProfile({self.track_name!r}, {self.vehicle_name!r}, "
            f"nodes={len(self.speed)}, "
            f"{self.minimum_speed * 3.6:.0f}-{self.top_speed * 3.6:.0f} km/h)"
        )


# ---------------------------------------------------------------------------
# Stage 1: the cornering limit
# ---------------------------------------------------------------------------


def cornering_limits(
    track: Track,
    vehicle: Vehicle,
    ambient: AmbientConditions | None = None,
    *,
    mass: float | None = None,
    tyre_state: TyreState | None = None,
    conditions: TrackConditions | None = None,
    limits: PerformanceLimits | None = None,
    config: SpeedProfileConfig | None = None,
) -> list[MetresPerSecond]:
    """Speed the tyres allow at each node, ignoring how the car got there.

    Results are memoised on the track state that actually matters -- curvature,
    banking, gradient and grip -- because a constant-radius arc repeats the same
    query at every node inside it.
    """
    conditions_ = ambient or AmbientConditions()
    cfg = config or SpeedProfileConfig()
    limits_ = limits or PerformanceLimits()
    air_density = conditions_.air_density
    car_mass = vehicle.total_mass() if mass is None else mass
    tyres = tyre_state or TyreState()

    cache: dict[tuple[int, int, int, int], float] = {}
    result: list[float] = []

    for segment in track.segments:
        state = track.state_at(segment.distance, conditions)
        key = (
            round(state.curvature * 1e9),
            round(state.banking * 1e6),
            round(state.gradient * 1e6),
            round(state.grip * 1e6),
        )
        cached = cache.get(key)
        if cached is None:
            cached = corner_speed_limit(
                vehicle,
                state.curvature,
                air_density,
                mass=car_mass,
                tyre_state=tyres,
                surface_grip=state.grip * limits_.cornering,
                banking=state.banking,
                gradient=state.gradient,
                max_speed=cfg.speed_ceiling,
                tolerance=cfg.corner_speed_tolerance,
            )
            cache[key] = cached
        result.append(max(cached, cfg.minimum_speed))
    return result


# ---------------------------------------------------------------------------
# Stage 2: longitudinal capability, with combined grip respected
# ---------------------------------------------------------------------------


def _capability(
    vehicle: Vehicle,
    speed: float,
    curvature: float,
    *,
    air_density: float,
    mass: float,
    tyres: TyreState,
    surface_grip: float,
    banking: float,
    gradient: float,
    limits: PerformanceLimits,
    braking: bool,
) -> float:
    """Longitudinal acceleration available at ``speed``, m/s^2.

    Positive when accelerating, positive when braking too (it is returned as a
    magnitude).  The lateral force the corner is already demanding is passed to
    the tyre model, so the friction ellipse decides what is left.
    """
    lateral_acceleration = speed * speed * abs(curvature)
    lateral_force = mass * lateral_acceleration
    utilisation = limits.braking if braking else limits.traction
    forces = longitudinal_forces(
        vehicle,
        speed,
        air_density,
        mass=mass,
        throttle=0.0 if braking else 1.0,
        brake=1.0 if braking else 0.0,
        gradient=gradient,
        banking=banking,
        tyre_state=tyres,
        surface_grip=surface_grip * utilisation,
        lateral_acceleration=lateral_acceleration,
        lateral_force_used=lateral_force,
    )
    return -forces.acceleration if braking else forces.acceleration


def _step(
    vehicle: Vehicle,
    start_speed: float,
    curvature: float,
    length: float,
    *,
    braking: bool,
    corrector_steps: int,
    minimum_speed: float,
    **kwargs: Any,
) -> float:
    """Advance one segment using ``v1^2 = v0^2 + 2*a*ds``.

    Exact for constant acceleration; ``corrector_steps`` re-evaluations at the
    midpoint speed make it second-order for the real, speed-dependent case.
    """
    acceleration = _capability(
        vehicle, start_speed, curvature, braking=braking, **kwargs
    )
    speed = start_speed
    for _ in range(corrector_steps + 1):
        squared = start_speed * start_speed + 2.0 * acceleration * length
        speed = math.sqrt(squared) if squared > 0.0 else minimum_speed
        midpoint = 0.5 * (start_speed + speed)
        acceleration = _capability(
            vehicle, midpoint, curvature, braking=braking, **kwargs
        )
    squared = start_speed * start_speed + 2.0 * acceleration * length
    return math.sqrt(squared) if squared > 0.0 else minimum_speed


# ---------------------------------------------------------------------------
# Stage 3: the passes
# ---------------------------------------------------------------------------


def compute_speed_profile(
    track: Track,
    vehicle: Vehicle,
    ambient: AmbientConditions | None = None,
    *,
    mass: float | None = None,
    tyre_state: TyreState | None = None,
    conditions: TrackConditions | None = None,
    limits: PerformanceLimits | None = None,
    corner_limit_override: Sequence[float] | None = None,
    config: SimulationConfig | SpeedProfileConfig | None = None,
) -> SpeedProfile:
    """Compute the speed profile for ``vehicle`` around ``track``.

    The result is the pointwise minimum of the cornering limit, what braking
    allows on the way in, and what acceleration allows on the way out.

    ``corner_limit_override`` replaces the computed cornering limit with one
    supplied by the caller, keeping the forward and backward passes.  Phase 4
    uses it to vary a driver's commitment corner by corner and to make a
    mistake cost apex speed -- the passes then propagate the consequences down
    the following straight on their own, which is what makes a mistake cost
    time through the driving rather than by adding it to the result.
    """
    conditions_ = ambient or AmbientConditions()
    if isinstance(config, SimulationConfig):
        cfg = config.speed_profile
    else:
        cfg = config or vehicle.config.speed_profile
    limits_ = limits or PerformanceLimits()

    air_density = conditions_.air_density
    car_mass = vehicle.total_mass() if mass is None else mass
    tyres = tyre_state or TyreState()

    if corner_limit_override is None:
        limit = cornering_limits(
            track,
            vehicle,
            conditions_,
            mass=car_mass,
            tyre_state=tyres,
            conditions=conditions,
            limits=limits_,
            config=cfg,
        )
    else:
        if len(corner_limit_override) != len(track.segments):
            raise ConfigError(
                f"corner_limit_override has {len(corner_limit_override)} entries "
                f"but the track has {len(track.segments)} segments"
            )
        limit = [max(v, cfg.minimum_speed) for v in corner_limit_override]
    speed = list(limit)
    count = len(speed)
    if count == 0:  # pragma: no cover - a Track cannot be empty
        raise ConfigError("cannot build a speed profile for a track with no segments")

    # Per-segment track state, resolved once.
    segment_state = [
        track.state_at(segment.mid_distance, conditions) for segment in track.segments
    ]
    lengths = [segment.length for segment in track.segments]

    def kwargs_for(index: int) -> dict[str, Any]:
        state = segment_state[index]
        return {
            "air_density": air_density,
            "mass": car_mass,
            "tyres": tyres,
            "surface_grip": state.grip,
            "banking": state.banking,
            "gradient": state.gradient,
            "limits": limits_,
        }

    converged = False
    passes = 0
    for passes in range(1, cfg.max_passes + 1):
        largest_change = 0.0

        # Backward: what must the speed be here so that braking can still make
        # the next corner?
        for i in range(count - 1, -1, -1):
            nxt = (i + 1) % count
            allowed = _step(
                vehicle,
                speed[nxt],
                segment_state[i].curvature,
                lengths[i],
                braking=True,
                corrector_steps=cfg.corrector_steps,
                minimum_speed=cfg.minimum_speed,
                **kwargs_for(i),
            )
            if allowed < speed[i]:
                largest_change = max(largest_change, speed[i] - allowed)
                speed[i] = allowed

        # Forward: how fast can the car have got to here, accelerating out of
        # what came before?
        for i in range(count):
            nxt = (i + 1) % count
            reachable = _step(
                vehicle,
                speed[i],
                segment_state[i].curvature,
                lengths[i],
                braking=False,
                corrector_steps=cfg.corrector_steps,
                minimum_speed=cfg.minimum_speed,
                **kwargs_for(i),
            )
            if reachable < speed[nxt]:
                largest_change = max(largest_change, speed[nxt] - reachable)
                speed[nxt] = reachable

        if largest_change <= cfg.convergence_tolerance:
            converged = True
            break

    return SpeedProfile(
        track_name=track.name,
        vehicle_name=vehicle.name,
        lap_length=track.length,
        distance=tuple(segment.distance for segment in track.segments),
        length=tuple(lengths),
        curvature=tuple(state.curvature for state in segment_state),
        corner_limit=tuple(limit),
        speed=tuple(speed),
        passes=passes,
        converged=converged,
        limits=limits_,
    )
