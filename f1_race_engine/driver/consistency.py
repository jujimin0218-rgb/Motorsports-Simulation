"""Lap-to-lap and corner-to-corner variation.

Project rule 18 lists ``consistency`` as an ability, and it has to mean
something more specific than "add noise to the lap time".  What varies is how
much of the car a driver uses, and it varies at two scales:

* **per lap** -- a lap that is generally on it, or generally not;
* **per corner** -- some corners come off better than others within the same
  lap.

The second is what turns a driver's lap times into a *distribution* rather than
a single offset plus jitter, and it is what makes a stint's fastest lap and its
median differ the way real ones do.

All variation is drawn from named RNG sub-streams (project rule 36), so a
session replays exactly, and adding a new source of randomness later cannot
disturb the numbers this one produces.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..core.config import DriverConfig
from ..core.rng import RngHub
from .model import DriverAttributes

__all__ = ["LapVariation", "sample_lap_variation"]


@dataclass(frozen=True, slots=True)
class LapVariation:
    """The commitment offsets a driver happens to produce on one lap."""

    lap_bias: float
    """Applied to every axis for the whole lap."""

    corner_bias: dict[int, float]
    """Extra offset for each corner, keyed by corner id."""

    def bias_for_corner(self, corner_id: int | None) -> float:
        if corner_id is None:
            return self.lap_bias
        return self.lap_bias + self.corner_bias.get(corner_id, 0.0)

    @property
    def is_perfect(self) -> bool:
        return self.lap_bias == 0.0 and not self.corner_bias


def sample_lap_variation(
    attributes: DriverAttributes,
    rng: RngHub,
    *,
    driver: str,
    lap: int,
    corner_ids: tuple[int, ...] = (),
    config: DriverConfig | None = None,
) -> LapVariation:
    """Draw one lap's worth of variation for ``driver``.

    A driver with ``consistency == 1.0`` produces no variation at all, which is
    what makes the ideal lap reproducible and the tests deterministic.
    """
    cfg = config or DriverConfig()
    inconsistency = 1.0 - attributes.consistency
    if inconsistency <= 0.0 or cfg.consistency_sigma <= 0.0:
        return LapVariation(lap_bias=0.0, corner_bias={})

    total_sigma = cfg.consistency_sigma * inconsistency
    corner_share = cfg.corner_sigma_fraction
    lap_sigma = total_sigma * (1.0 - corner_share) ** 0.5
    corner_sigma = total_sigma * corner_share**0.5

    lap_stream = rng.stream("driver.consistency.lap", driver=driver, lap=lap)
    lap_bias = -abs(lap_stream.normal(0.0, lap_sigma))

    corner_bias: dict[int, float] = {}
    if corner_sigma > 0.0:
        for corner_id in corner_ids:
            stream = rng.stream(
                "driver.consistency.corner", driver=driver, lap=lap, corner=corner_id
            )
            # Commitment is bounded above by the car: a driver can fall short of
            # the limit but not exceed it, so the variation is one-sided.
            corner_bias[corner_id] = -abs(stream.normal(0.0, corner_sigma))

    return LapVariation(lap_bias=lap_bias, corner_bias=corner_bias)
