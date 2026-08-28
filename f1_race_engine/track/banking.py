"""Track banking (cross-slope).

Banking changes the amount of lateral force the tyres must generate for a given
cornering speed, because part of the load is carried by the track surface
itself.  It is stored in **radians** and signed the same way as curvature:
positive banking supports a left-hand corner.  So banking helps when
``sign(banking) == sign(curvature)`` and hurts when it opposes it -- the
cornering model in Phase 3 reads it directly rather than through any per-track
fudge factor.

Definitions are supplied in degrees, because that is how circuit data is
published; conversion happens once, here at the boundary (project rule 38).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from ..core.interpolation import ConstantProfile, PiecewiseProfile
from ..core.units import Metres, Radians, deg_to_rad, rad_to_deg

__all__ = ["BankingProfile"]


@dataclass(frozen=True, slots=True)
class BankingProfile:
    """Banking angle ``phi(s)`` over a lap, in radians."""

    _profile: PiecewiseProfile
    lap_length: Metres

    @classmethod
    def flat(cls, lap_length: Metres) -> BankingProfile:
        """No banking anywhere."""
        return cls(_profile=ConstantProfile(0.0), lap_length=lap_length)

    @classmethod
    def from_control_points_deg(
        cls,
        points: Iterable[tuple[float, float]],
        lap_length: Metres,
        *,
        method: str = "monotone_cubic",
    ) -> BankingProfile:
        """Build from ``(distance, banking_degrees)`` pairs."""
        pts = [(float(d), deg_to_rad(float(a))) for d, a in points]
        if not pts:
            return cls.flat(lap_length)
        if len(pts) == 1:
            return cls(_profile=ConstantProfile(pts[0][1]), lap_length=lap_length)
        return cls(
            _profile=PiecewiseProfile(pts, method=method, period=lap_length),  # type: ignore[arg-type]
            lap_length=lap_length,
        )

    def banking(self, distance: Metres) -> Radians:
        """Banking angle at ``distance``, radians."""
        return self._profile.value(distance)

    def banking_deg(self, distance: Metres) -> float:
        return rad_to_deg(self.banking(distance))

    @property
    def control_points_deg(self) -> tuple[tuple[float, float], ...]:
        return tuple((p.x, rad_to_deg(p.y)) for p in self._profile.control_points)

    @property
    def is_flat(self) -> bool:
        return all(abs(p.y) < 1e-12 for p in self._profile.control_points)

    def to_dict(self) -> dict[str, Any]:
        return {
            "lap_length": self.lap_length,
            "control_points_deg": [list(p) for p in self.control_points_deg],
        }
