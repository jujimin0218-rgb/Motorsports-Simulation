"""Track evolution (project rule 30).

The circuit is not the same at the end of a session as at the start, and none
of the reasons are the clock.

**Rubber** goes down where the cars run.  A green track is slow, and it gets
quicker all through a session -- which is why the last runner in qualifying has
an advantage nobody gave them.

**Marbles** come off the tyres and collect off the line.  They are the other
half of the same process: the rubber that does not end up on the racing line.

**Water** arrives from the sky, drains away down the camber, and is thrown off
the road by the cars themselves.  That last one is what makes a drying line:
the track dries *where the cars run and nowhere else*, so the racing line comes
back before the rest of the circuit does, and a driver who steps off it finds
the water still there.

**Rain washes rubber away**, which is why a track that goes green in a shower
is slow again afterwards even once it is dry.

Everything below is a rate applied to what actually happened -- car-laps run,
seconds of rain fallen -- so a session that runs longer, or with more cars, or
in heavier rain, gets a different track without anything being scheduled.

Each process is integrated **in closed form** rather than stepped, because each
one is linear: water fills at a rate and drains in proportion to its depth,
rubber approaches saturation in proportion to what is missing.  So an hour
applied in one call and an hour applied in a hundred give the same track, and a
caller's update frequency is a sampling choice rather than a modelling one --
project rule 12, applied to time instead of distance.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from ..core.config import TrackConditionsConfig, TrackEvolutionConfig
from ..core.interpolation import clamp
from ..core.units import Seconds
from ..track.surface import TrackConditions
from .weather import WeatherState

__all__ = ["TrackEvolution"]


@dataclass
class TrackEvolution:
    """Drives one session's :class:`TrackConditions` forward.

    Owns nothing the track owns: the geometry stays immutable and shareable,
    and only the per-segment condition array moves.
    """

    conditions: TrackConditions
    config: TrackEvolutionConfig | None = None
    surface_config: TrackConditionsConfig | None = None

    def __post_init__(self) -> None:
        if self.config is None:
            self.config = TrackEvolutionConfig()
        if self.surface_config is None:
            self.surface_config = self.conditions.config

    # -- what the cars do ----------------------------------------------------

    def run_laps(self, car_laps: float) -> None:
        """Apply the effect of ``car_laps`` completed laps of running.

        One car completing one lap is one car-lap.  Twenty cars doing three
        laps rubbers a track in as fast as one car doing sixty, which is the
        real behaviour and falls out of counting the right thing.
        """
        if car_laps <= 0.0:
            return
        cfg = self.config
        # Each process approaches its limit in proportion to how far it still
        # has to go, so the closed-form solution is an exponential and the
        # answer does not depend on how the running was chunked.
        rubber_left = math.exp(-cfg.rubber_per_car_lap * car_laps)
        marbles_left = math.exp(-cfg.marbles_per_car_lap * car_laps)
        water_left = math.exp(-cfg.drying_per_car_lap * car_laps)

        for index in range(len(self.conditions)):
            condition = self.conditions[index]
            condition.rubber = clamp(
                1.0 - (1.0 - condition.rubber) * rubber_left, 0.0, 1.0
            )
            condition.marbles = clamp(
                1.0 - (1.0 - condition.marbles) * marbles_left, 0.0, 1.0
            )
            if condition.water_depth > 0.0:
                # The drying line: cars throw water off the road where they
                # run, and only what is actually there.
                dried = condition.water_depth * water_left
                condition.water_depth = dried if dried > cfg.dry_threshold else 0.0

    # -- what the sky does ---------------------------------------------------

    def apply_weather(self, weather: WeatherState, duration: Seconds) -> None:
        """Apply ``duration`` seconds under ``weather``.

        Water accumulates with the rain, drains with the camber, and takes the
        rubber with it.  Drainage uses each segment's own gradient, so the wet
        patch on a circuit is always in the same place -- the bottom of the dip
        -- without anybody marking it as one.
        """
        if duration <= 0.0:
            return
        cfg = self.config
        surface = self.surface_config
        falling = cfg.rain_accumulation * weather.rain_intensity
        washed = math.exp(
            -surface.rubber_wash_rate * weather.rain_intensity * duration / 60.0
        )

        for index in range(len(self.conditions)):
            condition = self.conditions[index]
            gradient = abs(self.conditions.segment_gradient(index))
            # d(depth)/dt = falling - k*depth.  Water fills at a rate and drains
            # in proportion to how much of it there is, so a circuit reaches an
            # equilibrium depth in steady rain rather than flooding without
            # limit -- and the equilibrium is shallower where the road slopes,
            # which is why the wet patch is always in the same place.
            rate = cfg.drainage_rate + cfg.gradient_drainage * gradient
            settled = falling / rate if rate > 0.0 else condition.water_depth + falling
            decay = math.exp(-rate * duration)
            depth = settled + (condition.water_depth - settled) * decay
            condition.water_depth = depth if depth > cfg.dry_threshold else 0.0
            if washed < 1.0:
                condition.rubber *= washed
                # Marbles wash away first: they are loose.
                condition.marbles *= washed * washed

    # -- reporting -----------------------------------------------------------

    @property
    def mean_water_depth(self) -> float:
        count = len(self.conditions)
        if count == 0:
            return 0.0
        return sum(
            self.conditions[i].water_depth for i in range(count)
        ) / count

    @property
    def wet_fraction(self) -> float:
        """Share of the circuit with standing water on it."""
        count = len(self.conditions)
        if count == 0:
            return 0.0
        return sum(
            1 for i in range(count) if self.conditions[i].water_depth > 0.0
        ) / count

    def to_dict(self) -> dict[str, Any]:
        return {
            "mean_rubber": self.conditions.mean_rubber,
            "mean_water_depth": self.mean_water_depth,
            "wet_fraction": self.wet_fraction,
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"TrackEvolution(rubber={self.conditions.mean_rubber:.2f}, "
            f"water={self.mean_water_depth * 1000:.2f} mm, "
            f"wet={self.wet_fraction:.0%})"
        )
