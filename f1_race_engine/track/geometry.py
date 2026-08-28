"""Plan-view geometry of a track.

The track model is fundamentally a function of arc length (project rule 5), so
the physics never needs ``(x, y)`` coordinates.  A drawn map does, though: the
debug plots, the SVG export and -- later -- a Unity client all need to know
where the circuit actually goes.

Given curvature as a function of arc length, the centreline follows from

.. code-block:: text

    theta(s) = theta0 + integral(k ds)
    x(s)     = x0 + integral(cos theta ds)
    y(s)     = y0 + integral(sin theta ds)

Because segments carry curvature that is linear in ``s``, ``theta(s)`` is exact
in closed form (a quadratic -- the Euler spiral).  Only the position integral
needs quadrature, and composite Simpson over a handful of sub-intervals per
segment is accurate to well under a millimetre.

The residual gap between the last point and the first is the **closure error**:
a genuinely useful diagnostic, because hand-entered corner radii that are
slightly wrong show up here immediately.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from ..core.units import Metres, Radians
from .segment import TrackSegment

__all__ = [
    "Centerline",
    "PlanPoint",
    "centerline_from_segments",
    "integrate_arc",
]


@dataclass(frozen=True, slots=True)
class PlanPoint:
    """A point on the plan-view centreline."""

    distance: Metres
    x: Metres
    y: Metres
    heading: Radians
    elevation: Metres = 0.0


def integrate_arc(
    x: Metres,
    y: Metres,
    heading: Radians,
    curvature_start: float,
    curvature_end: float,
    length: Metres,
    *,
    intervals: int = 8,
) -> tuple[Metres, Metres, Radians]:
    """Advance a pose along one linear-curvature segment.

    Returns the pose ``(x, y, heading)`` at the end of the segment.  ``theta``
    is evaluated exactly; the position uses composite Simpson quadrature with
    ``intervals`` sub-intervals (must be even).
    """
    if length <= 0.0:
        return x, y, heading
    if intervals < 2 or intervals % 2:
        raise ValueError("intervals must be an even integer >= 2")

    rate = (curvature_end - curvature_start) / length

    def theta(s: float) -> float:
        return heading + curvature_start * s + 0.5 * rate * s * s

    h = length / intervals
    # Simpson weights: 1, 4, 2, 4, ..., 4, 1
    sum_cos = math.cos(theta(0.0)) + math.cos(theta(length))
    sum_sin = math.sin(theta(0.0)) + math.sin(theta(length))
    for i in range(1, intervals):
        weight = 4.0 if i % 2 else 2.0
        angle = theta(i * h)
        sum_cos += weight * math.cos(angle)
        sum_sin += weight * math.sin(angle)
    factor = h / 3.0
    return x + factor * sum_cos, y + factor * sum_sin, theta(length)


@dataclass(frozen=True, slots=True)
class Centerline:
    """The sampled plan view of a lap."""

    points: tuple[PlanPoint, ...]
    length: Metres

    # -- extent --------------------------------------------------------------

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        """``(min_x, min_y, max_x, max_y)`` of the centreline."""
        if not self.points:
            return (0.0, 0.0, 0.0, 0.0)
        xs = [p.x for p in self.points]
        ys = [p.y for p in self.points]
        return (min(xs), min(ys), max(xs), max(ys))

    @property
    def extent(self) -> tuple[float, float]:
        """``(width, height)`` of the bounding box, m."""
        min_x, min_y, max_x, max_y = self.bounds
        return (max_x - min_x, max_y - min_y)

    # -- closure -------------------------------------------------------------

    @property
    def closure_error(self) -> Metres:
        """Distance from the end of the lap back to its start, m."""
        if len(self.points) < 2:
            return 0.0
        first, last = self.points[0], self.points[-1]
        return math.hypot(last.x - first.x, last.y - first.y)

    @property
    def closure_error_fraction(self) -> float:
        """Closure error as a fraction of lap length."""
        if self.length <= 0.0:
            return 0.0
        return self.closure_error / self.length

    @property
    def total_heading_change(self) -> Radians:
        """Total turning over the lap, radians.  A closed circuit gives
        ``+/-2*pi`` per lap of the loop."""
        if len(self.points) < 2:
            return 0.0
        return self.points[-1].heading - self.points[0].heading

    # -- export --------------------------------------------------------------

    def normalised(
        self, width: float = 1000.0, height: float = 1000.0, padding: float = 20.0
    ) -> list[tuple[float, float]]:
        """Scale the centreline into a ``width`` x ``height`` box.

        The aspect ratio is preserved and the y-axis is flipped so the result
        can be dropped straight into an SVG viewBox (SVG's y grows downward).
        """
        if not self.points:
            return []
        min_x, min_y, max_x, max_y = self.bounds
        span_x = max(max_x - min_x, 1e-9)
        span_y = max(max_y - min_y, 1e-9)
        usable_w = max(width - 2.0 * padding, 1e-9)
        usable_h = max(height - 2.0 * padding, 1e-9)
        scale = min(usable_w / span_x, usable_h / span_y)
        offset_x = padding + 0.5 * (usable_w - span_x * scale)
        offset_y = padding + 0.5 * (usable_h - span_y * scale)
        return [
            (
                offset_x + (p.x - min_x) * scale,
                height - (offset_y + (p.y - min_y) * scale),
            )
            for p in self.points
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "length": self.length,
            "closure_error": self.closure_error,
            "bounds": list(self.bounds),
            "points": [
                {
                    "distance": p.distance,
                    "x": p.x,
                    "y": p.y,
                    "heading": p.heading,
                    "elevation": p.elevation,
                }
                for p in self.points
            ],
        }

    def __len__(self) -> int:
        return len(self.points)


def centerline_from_segments(
    segments: Sequence[TrackSegment],
    *,
    samples_per_segment: int = 1,
    quadrature_intervals: int = 8,
) -> Centerline:
    """Build a :class:`Centerline` by walking the segments.

    ``samples_per_segment`` above 1 subdivides each segment for smoother
    drawing; it does not change the endpoint, because the quadrature is exact
    to the same order either way.
    """
    if samples_per_segment < 1:
        raise ValueError("samples_per_segment must be >= 1")
    if not segments:
        return Centerline(points=(), length=0.0)

    points: list[PlanPoint] = []
    x, y, heading = segments[0].x, segments[0].y, segments[0].heading
    total_length = 0.0

    for segment in segments:
        step = segment.length / samples_per_segment
        for i in range(samples_per_segment):
            s0 = segment.distance + i * step
            points.append(
                PlanPoint(
                    distance=s0,
                    x=x,
                    y=y,
                    heading=heading,
                    elevation=segment.elevation_at(s0),
                )
            )
            k0 = segment.curvature_at(s0)
            k1 = segment.curvature_at(s0 + step)
            x, y, heading = integrate_arc(
                x, y, heading, k0, k1, step, intervals=quadrature_intervals
            )
        total_length += segment.length

    last = segments[-1]
    points.append(
        PlanPoint(
            distance=last.end_distance,
            x=x,
            y=y,
            heading=heading,
            elevation=last.elevation_end,
        )
    )
    return Centerline(points=tuple(points), length=total_length)
