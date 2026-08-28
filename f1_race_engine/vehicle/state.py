"""Vehicle state -- the physics half.

Project rules 4 and 27 keep two kinds of state apart.  What is here is what the
*physics* needs to advance the car: where it is, how fast it is going, what it
weighs right now, and what its tyres are doing.

What is deliberately **not** here is race state -- lap number, classified
position, gap, pit status, penalties.  That belongs to the race core and
arrives in Phases 6-7.  Keeping them separate is what allows the same physics
to run a qualifying lap, a race stint or an offline benchmark without knowing
which it is.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..core.state import MutableState
from ..tyres.state import TyreState

__all__ = ["VehicleState"]


@dataclass
class VehicleState(MutableState):
    """The evolving physical condition of one car."""

    distance: float = 0.0
    """Distance travelled from the start/finish line, m.  Accumulates across
    laps; the track wraps it when queried."""

    speed: float = 0.0
    """Forward speed, m/s."""

    acceleration: float = 0.0
    """Longitudinal acceleration from the last step, m/s^2."""

    lateral_acceleration: float = 0.0
    """Lateral acceleration from the last step, m/s^2."""

    time: float = 0.0
    """Elapsed simulated time, s."""

    fuel_mass: float = 100.0
    """Fuel on board, kg.  Part of the car's mass, so it changes how the car
    accelerates, brakes and corners.  Burn-off arrives in Phase 5; until then
    this is set once and held."""

    tyres: TyreState = field(default_factory=TyreState)

    drs_open: bool = False
    """Whether the rear flap is open.  The aero model responds to it; deciding
    when it is allowed is a race-core matter in Phase 9."""

    # -- last applied control inputs, recorded for telemetry -----------------

    throttle: float = 0.0
    brake: float = 0.0
    """The inputs actually applied on the last step, each in ``[0, 1]``.
    Recorded rather than commanded here: the driver model owns the decision
    from Phase 4, through the input abstraction in project rule 19."""

    def snapshot(self) -> dict[str, Any]:
        return {
            "distance": self.distance,
            "speed": self.speed,
            "acceleration": self.acceleration,
            "lateral_acceleration": self.lateral_acceleration,
            "time": self.time,
            "fuel_mass": self.fuel_mass,
            "drs_open": self.drs_open,
            "throttle": self.throttle,
            "brake": self.brake,
            "tyres": self.tyres.snapshot(),
        }

    def reset(self, *, speed: float = 0.0, fuel_mass: float | None = None) -> None:
        """Return to the start of a run."""
        self.distance = 0.0
        self.speed = speed
        self.acceleration = 0.0
        self.lateral_acceleration = 0.0
        self.time = 0.0
        self.throttle = 0.0
        self.brake = 0.0
        self.drs_open = False
        if fuel_mass is not None:
            self.fuel_mass = fuel_mass

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"VehicleState(d={self.distance:.1f} m, v={self.speed * 3.6:.1f} km/h, "
            f"a={self.acceleration:.2f} m/s^2, fuel={self.fuel_mass:.1f} kg)"
        )
