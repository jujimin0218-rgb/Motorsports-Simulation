"""Aerodynamics.

The two forces both scale with dynamic pressure (project rule 12):

.. code-block:: text

    downforce = 0.5 * rho * v^2 * ClA
    drag      = 0.5 * rho * v^2 * CdA

What makes aero a *choice* rather than a number is that they are not
independent.  Drag has two parts: the zero-lift drag of pushing a car-shaped
object through air, and **induced drag**, which grows with the square of the
downforce being generated:

.. code-block:: text

    CdA = CdA_0 + k * ClA^2

So the tenth wing level costs far more drag than the first.  That single
relationship is what makes Monza and Monaco want different cars, with no
per-track correction anywhere -- a low wing setting is fast down a long
straight and hopeless through a slow corner, and the circuit decides which
matters.  Project rule 2.3 is satisfied by the physics, not by a lookup table.

Setup exposes one continuous knob, ``wing_level`` in ``[0, 1]``, spanning the
car's legal wing range.  Front wing, rear wing, floor, diffuser, ride height
and yaw sensitivity are Phase 12; they slot in behind this same interface.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..core.config import AeroConfig
from ..core.errors import ConfigError
from ..core.interpolation import clamp, lerp
from ..core.units import Newtons

__all__ = ["AeroProperties", "AeroModel", "AeroForces"]


@dataclass(frozen=True, slots=True)
class AeroProperties:
    """A car's aerodynamic platform."""

    min_downforce_area: float = 3.6
    """ClA, m^2, at the lowest legal wing setting (a Monza package)."""

    max_downforce_area: float = 6.2
    """ClA, m^2, at the highest wing setting (a Monaco package)."""

    zero_lift_drag_area: float = 0.4978
    """CdA_0, m^2 -- drag that does not come from making downforce.

    Wheels, bodywork and cooling.  It is about half the drag of a low-downforce
    car and a quarter of a high-downforce one, which is why adding wing costs
    proportionally more the more of it there already is."""

    induced_drag_factor: float = 0.03258
    """``k`` in ``CdA = CdA_0 + k * ClA^2``, 1/m^2.

    Calibrated so the pair land on published figures at both ends of the range:
    a Monza package at ``ClA 3.6`` comes out at ``CdA 0.92``, and a Monaco one
    at ``ClA 6.2`` at ``CdA 1.75``.  Getting the high-downforce end right is
    what makes the wing choice a real decision -- with too little drag up
    there, downforce is nearly free and every circuit wants maximum wing."""

    aero_balance_front: float = 0.44
    """Fraction of downforce acting on the front axle."""

    def __post_init__(self) -> None:
        if self.min_downforce_area <= 0.0:
            raise ConfigError("min_downforce_area must be positive")
        if self.max_downforce_area < self.min_downforce_area:
            raise ConfigError(
                "max_downforce_area must be at least min_downforce_area"
            )
        if self.zero_lift_drag_area <= 0.0:
            raise ConfigError("zero_lift_drag_area must be positive")
        if self.induced_drag_factor < 0.0:
            raise ConfigError("induced_drag_factor must be non-negative")
        if not 0.2 <= self.aero_balance_front <= 0.8:
            raise ConfigError("aero_balance_front must lie in [0.2, 0.8]")

    def downforce_area(self, wing_level: float) -> float:
        """ClA, m^2, at the given wing level."""
        return lerp(
            self.min_downforce_area,
            self.max_downforce_area,
            clamp(wing_level, 0.0, 1.0),
        )

    def drag_area(self, wing_level: float) -> float:
        """CdA, m^2, at the given wing level, including induced drag."""
        lift_area = self.downforce_area(wing_level)
        return self.zero_lift_drag_area + self.induced_drag_factor * lift_area * lift_area

    def efficiency(self, wing_level: float) -> float:
        """Lift-to-drag ratio, ``ClA / CdA``.

        Falls across most of the wing range, gently: a low-downforce package
        sits near 3.9 and a high-downforce one near 3.5.  The fall is shallow
        because a large part of an F1 car's drag comes from the wheels and
        bodywork rather than from the wings, so what really decides the wing
        choice is the *marginal* drag of the last bit of downforce,
        ``dCdA/dClA = 2 k ClA``, which grows with every wing level.
        """
        return self.downforce_area(wing_level) / self.drag_area(wing_level)

    def marginal_drag(self, wing_level: float) -> float:
        """``dCdA/dClA`` at this wing level, dimensionless.

        The price of one more unit of downforce area.  It rises with wing
        level, which is what makes a low-drag circuit want a small wing and a
        high-downforce one accept the cost."""
        return 2.0 * self.induced_drag_factor * self.downforce_area(wing_level)

    def to_dict(self) -> dict[str, Any]:
        return {
            "min_downforce_area": self.min_downforce_area,
            "max_downforce_area": self.max_downforce_area,
            "zero_lift_drag_area": self.zero_lift_drag_area,
            "induced_drag_factor": self.induced_drag_factor,
            "aero_balance_front": self.aero_balance_front,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AeroProperties:
        known = set(cls.__slots__)
        unknown = set(data) - known
        if unknown:
            raise ConfigError(f"unknown aero key(s): {', '.join(sorted(unknown))}")
        return cls(**data)


@dataclass(frozen=True, slots=True)
class AeroForces:
    """Aerodynamic forces at one instant."""

    downforce: Newtons
    drag: Newtons
    downforce_front: Newtons
    downforce_rear: Newtons
    dynamic_pressure: float

    @property
    def efficiency(self) -> float:
        return self.downforce / self.drag if self.drag > 0.0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "downforce": self.downforce,
            "drag": self.drag,
            "downforce_front": self.downforce_front,
            "downforce_rear": self.downforce_rear,
            "dynamic_pressure": self.dynamic_pressure,
        }


class AeroModel:
    """Evaluates aerodynamic forces for a given platform and setup."""

    __slots__ = ("_properties", "_config", "_areas")

    def __init__(
        self, properties: AeroProperties, config: AeroConfig | None = None
    ) -> None:
        self._properties = properties
        self._config = config or AeroConfig()
        # A car's wing does not move.  The two areas depend on the wing level
        # and whether DRS is open and on nothing else, so the whole engine only
        # ever asks for two pairs of numbers and it asks a hundred thousand
        # times a lap.
        self._areas: dict[tuple[float, bool], tuple[float, float]] = {}

    def _area_pair(self, wing_level: float, drs_open: bool) -> tuple[float, float]:
        key = (wing_level, drs_open)
        pair = self._areas.get(key)
        if pair is None:
            lift = self._properties.downforce_area(wing_level)
            drag = self._properties.drag_area(wing_level)
            if drs_open:
                lift *= 1.0 - self._config.drs_downforce_loss
                drag *= 1.0 - self._config.drs_drag_reduction
            pair = (lift, drag)
            self._areas[key] = pair
        return pair

    @property
    def properties(self) -> AeroProperties:
        return self._properties

    @property
    def config(self) -> AeroConfig:
        return self._config

    def downforce_area(self, wing_level: float, *, drs_open: bool = False) -> float:
        return self._area_pair(wing_level, drs_open)[0]

    def drag_area(self, wing_level: float, *, drs_open: bool = False) -> float:
        return self._area_pair(wing_level, drs_open)[1]

    def downforce_and_drag(
        self, speed: float, air_density: float, wing_level: float, *, drs_open: bool = False
    ) -> tuple[Newtons, Newtons]:
        """Both forces from one dynamic pressure.

        The force balance needs the pair every time it is evaluated, and asking
        for them separately computes ``0.5 rho v^2`` twice.
        """
        lift_area, drag_area = self._area_pair(wing_level, drs_open)
        dynamic_pressure = 0.5 * air_density * speed * speed
        return dynamic_pressure * lift_area, dynamic_pressure * drag_area

    def forces(
        self,
        speed: float,
        air_density: float,
        wing_level: float,
        *,
        drs_open: bool = False,
    ) -> AeroForces:
        """Downforce and drag at ``speed``, both proportional to ``v^2``."""
        lift_area, drag_area = self._area_pair(wing_level, drs_open)
        dynamic_pressure = 0.5 * air_density * speed * speed
        downforce = dynamic_pressure * lift_area
        drag = dynamic_pressure * drag_area
        balance = self._properties.aero_balance_front
        return AeroForces(
            downforce=downforce,
            drag=drag,
            downforce_front=downforce * balance,
            downforce_rear=downforce * (1.0 - balance),
            dynamic_pressure=dynamic_pressure,
        )

    def downforce(
        self, speed: float, air_density: float, wing_level: float, *, drs_open: bool = False
    ) -> Newtons:
        return (
            0.5
            * air_density
            * speed
            * speed
            * self.downforce_area(wing_level, drs_open=drs_open)
        )

    def drag(
        self, speed: float, air_density: float, wing_level: float, *, drs_open: bool = False
    ) -> Newtons:
        return (
            0.5
            * air_density
            * speed
            * speed
            * self.drag_area(wing_level, drs_open=drs_open)
        )
