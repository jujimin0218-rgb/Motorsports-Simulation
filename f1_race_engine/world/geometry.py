"""Plane geometry, in metres.

The engine's physics is a **distance** model: everything it decides -- a
cornering limit, a lap time, a gap -- is a function of how far round the lap a
car is.  This package is the other thing a race has, which is a place: two
cars at the same distance are somewhere, and whether they touch is a question
about where.

Kept deliberately small and free of the rest of the engine.  Nothing in here
knows what a lap is.

Every operation is plain float arithmetic in a fixed order, because the world
above it has to give the same answer twice from the same seed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

__all__ = ["Vec2", "closest_point_on_segment", "project_polyline"]


@dataclass(frozen=True, slots=True)
class Vec2:
    """A point or a direction on the plane, in metres."""

    x: float
    y: float

    def __add__(self, other: Vec2) -> Vec2:
        return Vec2(self.x + other.x, self.y + other.y)

    def __sub__(self, other: Vec2) -> Vec2:
        return Vec2(self.x - other.x, self.y - other.y)

    def __mul__(self, scale: float) -> Vec2:
        return Vec2(self.x * scale, self.y * scale)

    __rmul__ = __mul__

    def dot(self, other: Vec2) -> float:
        return self.x * other.x + self.y * other.y

    def cross(self, other: Vec2) -> float:
        """The z of the cross product: positive when ``other`` is to the left."""
        return self.x * other.y - self.y * other.x

    @property
    def length(self) -> float:
        return math.hypot(self.x, self.y)

    @property
    def length_squared(self) -> float:
        return self.x * self.x + self.y * self.y

    def normalised(self) -> Vec2:
        """Unit length, or zero for a zero vector rather than a division error."""
        size = self.length
        return Vec2(0.0, 0.0) if size == 0.0 else Vec2(self.x / size, self.y / size)

    @property
    def left(self) -> Vec2:
        """A quarter turn anticlockwise -- the direction "across to the left"."""
        return Vec2(-self.y, self.x)

    def rotated(self, angle: float) -> Vec2:
        cos = math.cos(angle)
        sin = math.sin(angle)
        return Vec2(self.x * cos - self.y * sin, self.x * sin + self.y * cos)

    @property
    def heading(self) -> float:
        return math.atan2(self.y, self.x)

    def to_tuple(self) -> tuple[float, float]:
        return (self.x, self.y)


def closest_point_on_segment(point: Vec2, start: Vec2, end: Vec2) -> Vec2:
    """The point on segment ``start``-``end`` nearest ``point``.

    The whole of barrier and edge collision is this question asked of a lot of
    segments, so it is written once and kept branch-free apart from the
    degenerate segment.
    """
    along = end - start
    span = along.length_squared
    if span == 0.0:
        return start
    t = (point - start).dot(along) / span
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    return start + along * t


def project_polyline(points: tuple[Vec2, ...], offsets: tuple[float, ...]) -> tuple[Vec2, ...]:
    """Push each point of a polyline sideways by its own offset.

    Left is positive, matching the way the race records a car's place across
    the road.  The direction "sideways" at a point is a quarter turn from the
    way the line is going there, taken from the neighbours on both sides so a
    corner does not kink the edge it generates.
    """
    count = len(points)
    if count < 2:
        return points
    out: list[Vec2] = []
    last = Vec2(0.0, 1.0)
    for index, point in enumerate(points):
        before = points[index - 1] if index > 0 else points[-1]
        after = points[index + 1] if index + 1 < count else points[0]
        along = (after - before).normalised()
        # A line that stands still has no direction to be offset along.  Rather
        # than collapse the offset to nothing -- which puts the edge of the road
        # on top of its centre -- carry the last direction that meant anything.
        normal = along.left if along.length_squared > 0.0 else last
        last = normal
        out.append(point + normal * offsets[index])
    return tuple(out)
