"""Curvature utilities.

Curvature ``k = 1/R`` is the quantity the cornering model actually needs
(project rule 8): it is finite everywhere, it is zero on a straight instead of
infinite, and it interpolates linearly through a clothoid transition.  Radius
is derived from it for human-facing output, never the other way round.

Sign convention throughout the engine: **positive curvature is a left-hand
corner**, negative a right-hand corner.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import Enum

from ..core.units import (
    STANDARD_GRAVITY,
    Curvature,
    Metres,
    MetresPerSecond,
    Radians,
    curvature_from_radius,
    radius_from_curvature,
)
from .segment import TrackSegment

__all__ = [
    "CornerSpeedClass",
    "CurvatureProfile",
    "classify_corner",
    "curvature_from_radius",
    "curvature_profile",
    "heading_change",
    "nominal_corner_speed",
    "radius_from_curvature",
    "signed_curvature",
]

#: Reference lateral acceleration, in g, used only to translate a radius into a
#: rough "how fast is this corner" label for reports and UI.  It is *not* part
#: of the physics: the real cornering speed comes from the vehicle's grip,
#: downforce and mass in Phase 3.
REFERENCE_LATERAL_G: float = 3.5


class CornerSpeedClass(str, Enum):
    """Coarse corner classification used for track characteristics reports."""

    STRAIGHT = "straight"
    LOW_SPEED = "low_speed"
    MEDIUM_SPEED = "medium_speed"
    HIGH_SPEED = "high_speed"


def signed_curvature(radius: Metres, turns_left: bool) -> Curvature:
    """Return the signed curvature of a corner of unsigned ``radius``."""
    if radius <= 0.0:
        raise ValueError(f"corner radius must be positive, got {radius}")
    magnitude = curvature_from_radius(radius)
    return magnitude if turns_left else -magnitude


def heading_change(
    curvature_start: Curvature, curvature_end: Curvature, length: Metres
) -> Radians:
    """Heading change over a segment whose curvature varies linearly.

    ``integral(k ds) = 0.5 * (k0 + k1) * L`` -- exact for a clothoid.
    """
    return 0.5 * (curvature_start + curvature_end) * length


def nominal_corner_speed(
    radius: Metres, lateral_g: float = REFERENCE_LATERAL_G
) -> MetresPerSecond:
    """Rough cornering speed for a given radius, m/s.

    ``v = sqrt(a_lat * R)``.  Reporting only -- see
    :data:`REFERENCE_LATERAL_G`.
    """
    if math.isinf(radius):
        return math.inf
    return math.sqrt(max(abs(radius), 0.0) * lateral_g * STANDARD_GRAVITY)


def classify_corner(
    radius: Metres,
    *,
    low_speed_kph: float = 130.0,
    high_speed_kph: float = 250.0,
    lateral_g: float = REFERENCE_LATERAL_G,
) -> CornerSpeedClass:
    """Label a corner low / medium / high speed from its radius.

    Thresholds follow the usual paddock split (slow below ~130 km/h, fast above
    ~250 km/h) applied to the nominal speed from :func:`nominal_corner_speed`.
    """
    if math.isinf(radius):
        return CornerSpeedClass.STRAIGHT
    speed_kph = nominal_corner_speed(radius, lateral_g) * 3.6
    if speed_kph < low_speed_kph:
        return CornerSpeedClass.LOW_SPEED
    if speed_kph < high_speed_kph:
        return CornerSpeedClass.MEDIUM_SPEED
    return CornerSpeedClass.HIGH_SPEED


@dataclass(frozen=True, slots=True)
class CurvatureProfile:
    """Sampled curvature along a lap -- the input to plots and validation."""

    distance: tuple[float, ...]
    curvature: tuple[float, ...]
    radius: tuple[float, ...]
    curvature_rate: tuple[float, ...]

    def __len__(self) -> int:
        return len(self.distance)

    @property
    def max_abs_curvature(self) -> Curvature:
        return max((abs(k) for k in self.curvature), default=0.0)

    @property
    def min_radius(self) -> Metres:
        finite = [r for r in self.radius if math.isfinite(r)]
        return min((abs(r) for r in finite), default=math.inf)

    @property
    def max_abs_curvature_rate(self) -> float:
        return max((abs(r) for r in self.curvature_rate), default=0.0)

    @property
    def total_heading_change(self) -> Radians:
        """Signed total turning of the sampled profile, radians."""
        total = 0.0
        for i in range(len(self.distance) - 1):
            ds = self.distance[i + 1] - self.distance[i]
            total += 0.5 * (self.curvature[i] + self.curvature[i + 1]) * ds
        return total


def curvature_profile(
    segments: Sequence[TrackSegment], *, samples_per_segment: int = 1
) -> CurvatureProfile:
    """Sample the curvature of ``segments`` for plotting and validation.

    With ``samples_per_segment=1`` each segment contributes its start point and
    the final segment also contributes its end point, which is enough to see
    every clothoid; raise it to render smoother debug plots.
    """
    if samples_per_segment < 1:
        raise ValueError("samples_per_segment must be >= 1")
    distances: list[float] = []
    curvatures: list[float] = []
    radii: list[float] = []
    rates: list[float] = []

    for segment in segments:
        for i in range(samples_per_segment):
            t = i / samples_per_segment
            distance = segment.distance + t * segment.length
            k = segment.curvature_at(distance)
            distances.append(distance)
            curvatures.append(k)
            radii.append(radius_from_curvature(k))
            rates.append(segment.curvature_rate)
    if segments:
        last = segments[-1]
        distances.append(last.end_distance)
        curvatures.append(last.curvature_end)
        radii.append(radius_from_curvature(last.curvature_end))
        rates.append(last.curvature_rate)

    return CurvatureProfile(
        distance=tuple(distances),
        curvature=tuple(curvatures),
        radius=tuple(radii),
        curvature_rate=tuple(rates),
    )


def curvature_discontinuities(
    segments: Sequence[TrackSegment],
) -> list[tuple[int, float]]:
    """Find joints where curvature jumps between neighbouring segments.

    Returns ``(index_of_following_segment, jump_magnitude)`` pairs.  A track
    built from clothoid corners should return an empty list up to
    floating-point noise; anything else means the data is broken.
    """
    jumps: list[tuple[int, float]] = []
    if len(segments) < 2:
        return jumps
    for previous, current in zip(segments, segments[1:]):
        jump = abs(current.curvature_start - previous.curvature_end)
        if jump > 0.0:
            jumps.append((current.index, jump))
    # The lap closes on itself, so the start/finish joint counts too.
    seam = abs(segments[0].curvature_start - segments[-1].curvature_end)
    if seam > 0.0:
        jumps.append((segments[0].index, seam))
    return jumps


def summarise_corners(
    segments: Iterable[TrackSegment],
) -> dict[int, dict[str, float | str | None]]:
    """Aggregate segments into per-corner statistics.

    Returns a mapping of ``corner_id`` to the corner's name, length, minimum
    radius, total turn angle and speed class.
    """
    corners: dict[int, dict[str, float | str | None]] = {}
    for segment in segments:
        if segment.corner_id is None:
            continue
        entry = corners.setdefault(
            segment.corner_id,
            {
                "corner_id": segment.corner_id,
                "name": segment.corner_name,
                "start_distance": segment.distance,
                "length": 0.0,
                "min_radius": math.inf,
                "turn_angle": 0.0,
            },
        )
        entry["length"] = float(entry["length"]) + segment.length
        entry["turn_angle"] = float(entry["turn_angle"]) + segment.heading_change
        if segment.corner_radius < float(entry["min_radius"]):
            entry["min_radius"] = segment.corner_radius
    for entry in corners.values():
        radius = float(entry["min_radius"])
        entry["speed_class"] = classify_corner(radius).value
        entry["nominal_speed"] = nominal_corner_speed(radius)
        entry["direction"] = "left" if float(entry["turn_angle"]) >= 0.0 else "right"
    return corners
