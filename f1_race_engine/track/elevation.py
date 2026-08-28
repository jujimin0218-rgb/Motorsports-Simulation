"""Elevation and gradient along the lap.

Elevation is defined by sparse control points and interpolated with a monotone
cubic, so the **gradient is continuous** everywhere.  That matters more than it
looks: gradient enters the longitudinal force balance directly (project rule
13, ``F = ... - m*g*sin(theta)``), so a kink in the elevation profile would
appear in the physics as an impulsive force at a single point.

A circuit is a closed loop, so the profile is periodic: the elevation arriving
at the end of the lap must join the elevation leaving the start/finish line,
in value *and* slope.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from ..core.interpolation import ConstantProfile, PiecewiseProfile
from ..core.units import Metres

__all__ = ["ElevationProfile"]


@dataclass(frozen=True, slots=True)
class ElevationProfile:
    """Elevation ``z(s)`` and gradient ``dz/ds`` over a lap."""

    _profile: PiecewiseProfile
    lap_length: Metres

    # -- construction --------------------------------------------------------

    @classmethod
    def flat(cls, lap_length: Metres, elevation: Metres = 0.0) -> ElevationProfile:
        """A perfectly flat circuit."""
        return cls(_profile=ConstantProfile(elevation), lap_length=lap_length)

    @classmethod
    def from_control_points(
        cls,
        points: Iterable[tuple[float, float]],
        lap_length: Metres,
        *,
        method: str = "monotone_cubic",
    ) -> ElevationProfile:
        """Build from ``(distance, elevation)`` pairs.

        Points may include both ``0`` and ``lap_length``; the trailing point is
        recognised as the wrap of the first, and any mismatch between them is
        preserved in :attr:`closure_mismatch` for validation to report.
        """
        pts = list(points)
        if not pts:
            return cls.flat(lap_length)
        if len(pts) == 1:
            return cls(_profile=ConstantProfile(pts[0][1]), lap_length=lap_length)
        return cls(
            _profile=PiecewiseProfile(pts, method=method, period=lap_length),  # type: ignore[arg-type]
            lap_length=lap_length,
        )

    # -- evaluation ----------------------------------------------------------

    def elevation(self, distance: Metres) -> Metres:
        """Elevation at ``distance``, m."""
        return self._profile.value(distance)

    def gradient(self, distance: Metres) -> float:
        """Slope ``dz/ds`` at ``distance`` (dimensionless, + is uphill)."""
        return self._profile.derivative(distance)

    def gradient_percent(self, distance: Metres) -> float:
        return self.gradient(distance) * 100.0

    # -- summary -------------------------------------------------------------

    @property
    def closure_mismatch(self) -> Metres:
        """Elevation difference between the end and start of the lap, m."""
        return self._profile.closure_mismatch

    @property
    def control_points(self) -> tuple[tuple[float, float], ...]:
        return tuple((p.x, p.y) for p in self._profile.control_points)

    def sample(self, count: int = 400) -> tuple[list[float], list[float], list[float]]:
        """Return ``(distances, elevations, gradients)`` sampled evenly."""
        if count < 2:
            raise ValueError("count must be >= 2")
        step = self.lap_length / (count - 1)
        distances = [i * step for i in range(count)]
        return (
            distances,
            [self.elevation(d) for d in distances],
            [self.gradient(d) for d in distances],
        )

    def statistics(self, samples: int = 1000) -> dict[str, float]:
        """Total climb, total descent and extremes over the lap."""
        distances, elevations, gradients = self.sample(samples)
        climb = 0.0
        descent = 0.0
        for a, b in zip(elevations, elevations[1:]):
            delta = b - a
            if delta > 0.0:
                climb += delta
            else:
                descent -= delta
        return {
            "min_elevation": min(elevations),
            "max_elevation": max(elevations),
            "elevation_range": max(elevations) - min(elevations),
            "total_climb": climb,
            "total_descent": descent,
            "max_gradient": max(gradients),
            "min_gradient": min(gradients),
            "max_abs_gradient": max(abs(g) for g in gradients),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "lap_length": self.lap_length,
            "control_points": [list(p) for p in self.control_points],
        }
