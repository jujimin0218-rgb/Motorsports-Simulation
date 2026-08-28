"""Setup search: let the circuit decide the setup.

Project rule 2.3 forbids per-track corrections.  The positive statement of that
rule is this module: given a circuit and a car, sweep the setup and let the lap
time say what the circuit wants.  Nothing here knows a track's name; it only
knows how long the lap took.

Measured on the shipped circuits with the reference car, the optimum spans the
entire wing range -- minimum wing on the power circuit, maximum on the street
circuit, and a genuine interior optimum on the balanced one.  That is the
mechanism working, not a table being read.

The sweep is deliberately simple.  A real setup optimiser also varies brake
bias, ride height, differential and gear ratios, and those arrive as further
axes here once Phase 12 gives the car something to vary.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..environment.conditions import AmbientConditions
from ..track.model import Track
from ..tyres.state import TyreState
from ..vehicle.model import Vehicle
from .lap_time import compute_lap_time

__all__ = ["SetupSweep", "SweepPoint", "optimal_wing_level", "wing_level_sweep"]


@dataclass(frozen=True, slots=True)
class SweepPoint:
    """One setup evaluated."""

    wing_level: float
    lap_time: float
    top_speed: float
    minimum_speed: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "wing_level": self.wing_level,
            "lap_time": self.lap_time,
            "top_speed": self.top_speed,
            "minimum_speed": self.minimum_speed,
        }


@dataclass(frozen=True, slots=True)
class SetupSweep:
    """The result of sweeping one setup axis."""

    track_name: str
    vehicle_name: str
    points: tuple[SweepPoint, ...]

    @property
    def best(self) -> SweepPoint:
        return min(self.points, key=lambda point: point.lap_time)

    @property
    def worst(self) -> SweepPoint:
        return max(self.points, key=lambda point: point.lap_time)

    @property
    def spread(self) -> float:
        """Lap time cost, s, of the worst setting versus the best."""
        return self.worst.lap_time - self.best.lap_time

    @property
    def is_interior_optimum(self) -> bool:
        """True when the best setting is not at either end of the range.

        An interior optimum is the clearest evidence that the trade-off is
        real: the circuit wants some downforce but not all of it.
        """
        if len(self.points) < 3:
            return False
        return self.best is not self.points[0] and self.best is not self.points[-1]

    def to_dict(self) -> dict[str, Any]:
        return {
            "track": self.track_name,
            "vehicle": self.vehicle_name,
            "best": self.best.to_dict(),
            "spread": self.spread,
            "interior_optimum": self.is_interior_optimum,
            "points": [point.to_dict() for point in self.points],
        }


def wing_level_sweep(
    track: Track,
    vehicle: Vehicle,
    ambient: AmbientConditions | None = None,
    *,
    levels: tuple[float, ...] | None = None,
    mass: float | None = None,
    tyre_state: TyreState | None = None,
) -> SetupSweep:
    """Evaluate a lap at each wing level and report the results."""
    steps = levels if levels is not None else tuple(i / 10.0 for i in range(11))
    conditions = ambient or AmbientConditions()
    points: list[SweepPoint] = []
    for level in steps:
        result = compute_lap_time(
            track,
            vehicle.with_wing(level),
            conditions,
            mass=mass,
            tyre_state=tyre_state,
            analyse_zones=False,
        )
        points.append(
            SweepPoint(
                wing_level=level,
                lap_time=result.lap_time,
                top_speed=result.top_speed,
                minimum_speed=result.minimum_speed,
            )
        )
    return SetupSweep(
        track_name=track.name,
        vehicle_name=vehicle.name,
        points=tuple(points),
    )


def optimal_wing_level(
    track: Track,
    vehicle: Vehicle,
    ambient: AmbientConditions | None = None,
    *,
    coarse_steps: int = 11,
    refine: bool = True,
    **kwargs: Any,
) -> float:
    """The wing level that produces the fastest lap.

    A coarse sweep followed by an optional refinement around the winner, which
    is enough for a smooth single-axis trade-off.
    """
    coarse = tuple(i / (coarse_steps - 1) for i in range(coarse_steps))
    sweep = wing_level_sweep(track, vehicle, ambient, levels=coarse, **kwargs)
    best = sweep.best.wing_level
    if not refine:
        return best
    step = 1.0 / (coarse_steps - 1)
    window = tuple(
        min(1.0, max(0.0, best + offset * step / 4.0)) for offset in (-2, -1, 0, 1, 2)
    )
    return wing_level_sweep(
        track, vehicle, ambient, levels=tuple(sorted(set(window))), **kwargs
    ).best.wing_level
