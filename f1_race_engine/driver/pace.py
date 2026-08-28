"""Turning driver ability into physics.

This is the module project rule 18 is really about: an attribute that does not
change how the car is driven is decoration.  Each of the three driving
abilities becomes a **commitment** -- the fraction of the available grip the
driver actually uses on that axis:

.. code-block:: text

    utilisation = 1 - (1 - attribute) * max_commitment_deficit

and those go straight into
:class:`~f1_race_engine.physics.speed_profile.PerformanceLimits`, the seam that
has been wired through the speed profile since Phase 3.  Nothing in the physics
knows a driver exists; it only knows how much grip is being asked for.

The consequences follow on their own.  A driver weak on the brakes brakes
earlier, because the backward pass finds a lower deceleration.  A driver weak
on traction is slower out of slow corners specifically, because that is where
traction binds.  No lap time is ever adjusted.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..core.config import DriverConfig
from ..core.interpolation import clamp
from ..physics.speed_profile import PerformanceLimits
from .model import DriverAttributes

__all__ = ["Commitment", "commitment_for", "performance_limits_for"]


@dataclass(frozen=True, slots=True)
class Commitment:
    """The fraction of available grip a driver uses on each axis."""

    cornering: float
    braking: float
    traction: float

    def as_limits(self) -> PerformanceLimits:
        return PerformanceLimits(
            cornering=self.cornering, braking=self.braking, traction=self.traction
        )


#: How much of a driving axis is the specific ability rather than raw pace.
#: Blending rather than adding matters: an additive pace bonus pushes the
#: strongest drivers to 100% commitment in race trim, and a driver already at
#: the limit has nothing left to find on a qualifying lap.
_SPECIFIC_WEIGHT = 0.70


def _utilisation(attribute: float, deficit: float, bias: float, floor: float) -> float:
    return clamp(1.0 - (1.0 - attribute) * deficit + bias, floor, 1.0)


def _blend(specific: float, pace: float) -> float:
    """Combine a specific ability with the driver's raw pace."""
    return _SPECIFIC_WEIGHT * specific + (1.0 - _SPECIFIC_WEIGHT) * pace


def commitment_for(
    attributes: DriverAttributes,
    config: DriverConfig | None = None,
    *,
    qualifying: bool = False,
    bias: float = 0.0,
) -> Commitment:
    """Map a driver's abilities to grip utilisation.

    ``bias`` is an additive offset used by the consistency model to nudge a
    single lap or a single corner; ``qualifying`` lets a driver's one-lap
    ability lift their commitment when it is a flying lap that counts.
    """
    cfg = config or DriverConfig()
    deficit = cfg.max_commitment_deficit
    floor = cfg.min_commitment

    # A flying lap that counts is worth extra commitment, and how much a driver
    # finds is exactly what the qualifying ability measures.  Applied as a bias
    # so that a driver already on the limit gains little and a one-lap
    # specialist gains a lot.
    total_bias = bias
    if qualifying:
        total_bias += (attributes.qualifying - 0.85) * deficit * 0.5

    pace = attributes.pace
    return Commitment(
        cornering=_utilisation(
            _blend(attributes.cornering, pace), deficit, total_bias, floor
        ),
        braking=_utilisation(
            _blend(attributes.braking, pace), deficit, total_bias, floor
        ),
        traction=_utilisation(
            _blend(attributes.throttle_control, pace), deficit, total_bias, floor
        ),
    )


def performance_limits_for(
    attributes: DriverAttributes,
    config: DriverConfig | None = None,
    **kwargs: float | bool,
) -> PerformanceLimits:
    """Convenience wrapper returning the physics-facing limits directly."""
    return commitment_for(attributes, config, **kwargs).as_limits()  # type: ignore[arg-type]
