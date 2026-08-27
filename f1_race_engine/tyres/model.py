"""The tyre grip model.

Two pieces of physics, both of which matter far more than their size suggests.

**Load sensitivity.**  A tyre's friction coefficient falls as it is pressed
harder, so grip is not proportional to load.  Without this, an F1 car's
cornering ability would rise linearly with downforce and the high-speed corners
would come out absurd.  The compound owns the coefficient
(:meth:`TyreCompound.friction_coefficient`); this module applies it.

**The friction ellipse.**  A tyre has one friction budget, shared between
braking/accelerating and cornering:

.. code-block:: text

    (Fx / F_max)^n + (Fy / F_max)^n  <=  1

with ``n = 2`` giving the classic ellipse.  This is what makes trail braking a
trade rather than a free lunch, and it is the constraint the speed profile
(Phase 3) and the driver model (Phase 4) both work against.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..core.config import TyreConfig
from ..core.interpolation import clamp
from .compound import TyreCompound
from .state import TyreState

__all__ = ["TyreModel", "GripLimit"]


@dataclass(frozen=True, slots=True)
class GripLimit:
    """The friction available at one instant, and how it may be spent."""

    normal_load: float
    """Total vertical load on the tyres, N."""

    friction_coefficient: float
    """Effective coefficient after load sensitivity, condition and surface."""

    capacity: float
    """Maximum friction force, N -- the radius of the friction circle."""

    def available_lateral(self, longitudinal_used: float, exponent: float = 2.0) -> float:
        """Lateral force still available while using ``longitudinal_used``, N."""
        return _remaining(self.capacity, longitudinal_used, exponent)

    def available_longitudinal(self, lateral_used: float, exponent: float = 2.0) -> float:
        """Longitudinal force still available while using ``lateral_used``, N."""
        return _remaining(self.capacity, lateral_used, exponent)

    def utilisation(
        self, longitudinal: float, lateral: float, exponent: float = 2.0
    ) -> float:
        """How much of the friction budget is spent, 1.0 being the limit."""
        if self.capacity <= 0.0:
            return float("inf")
        return (
            (abs(longitudinal) / self.capacity) ** exponent
            + (abs(lateral) / self.capacity) ** exponent
        ) ** (1.0 / exponent)


def _remaining(capacity: float, used: float, exponent: float) -> float:
    if capacity <= 0.0:
        return 0.0
    ratio = clamp(abs(used) / capacity, 0.0, 1.0)
    return capacity * (1.0 - ratio**exponent) ** (1.0 / exponent)


class TyreModel:
    """Turns a compound, a load and a surface into an available friction force."""

    __slots__ = ("_config",)

    def __init__(self, config: TyreConfig | None = None) -> None:
        self._config = config or TyreConfig()

    @property
    def config(self) -> TyreConfig:
        return self._config

    def friction_coefficient(
        self,
        compound: TyreCompound,
        normal_load: float,
        *,
        state: TyreState | None = None,
        surface_grip: float = 1.0,
    ) -> float:
        """Effective friction coefficient.

        Three independent factors: the compound under this load, the tyre's own
        condition, and the surface it is running on.  Each is owned by a
        different part of the engine, and each can change without the others
        knowing.
        """
        load = max(normal_load, self._config.min_normal_load)
        coefficient = compound.friction_coefficient(load)
        if state is not None:
            coefficient *= state.grip_multiplier()
        return coefficient * surface_grip

    def grip_limit(
        self,
        compound: TyreCompound,
        normal_load: float,
        *,
        state: TyreState | None = None,
        surface_grip: float = 1.0,
    ) -> GripLimit:
        """The friction circle available at this load."""
        load = max(normal_load, 0.0)
        coefficient = self.friction_coefficient(
            compound, load, state=state, surface_grip=surface_grip
        )
        return GripLimit(
            normal_load=load,
            friction_coefficient=coefficient,
            capacity=coefficient * load,
        )

    def rolling_resistance_force(
        self, compound: TyreCompound, normal_load: float
    ) -> float:
        """Rolling resistance, N.  Proportional to vertical load."""
        return compound.rolling_resistance * max(normal_load, 0.0)

    # -- combined grip -------------------------------------------------------

    def available_lateral(self, limit: GripLimit, longitudinal_used: float) -> float:
        return limit.available_lateral(
            longitudinal_used, self._config.combined_grip_exponent
        )

    def available_longitudinal(self, limit: GripLimit, lateral_used: float) -> float:
        return limit.available_longitudinal(
            lateral_used, self._config.combined_grip_exponent
        )

    def utilisation(
        self, limit: GripLimit, longitudinal: float, lateral: float
    ) -> float:
        return limit.utilisation(
            longitudinal, lateral, self._config.combined_grip_exponent
        )
