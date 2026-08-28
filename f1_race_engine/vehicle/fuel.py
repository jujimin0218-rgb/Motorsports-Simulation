"""Fuel (project rule 23).

Fuel is not a lap counter.  It is mass on board, and it is burned in proportion
to the work the engine actually does:

.. code-block:: text

    fuel burned = engine work / (thermal efficiency * heating value)

That one relationship gives the behaviour rule 23 asks for without anything
else being written down.  The car is heavier at the start of a race than at the
end, so it corners and accelerates worse on lap 1 than on lap 50, and a circuit
that demands more energy per lap empties the tank faster.

It also means fuel consumption and lap time are *coupled*: pushing harder burns
more, and lifting to save fuel costs time.  Phase 8 turns that into a strategy
decision; Phase 5 makes it true.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..core.config import FuelConfig
from ..core.errors import ConfigError
from ..core.units import Joules, Kilograms, Seconds

__all__ = ["FuelProperties", "fuel_burned"]


@dataclass(frozen=True, slots=True)
class FuelProperties:
    """A car's fuel system."""

    capacity: Kilograms = 110.0
    """Maximum fuel load, kg.  Formula 1's race allowance."""

    max_flow_rate: float = 0.0278
    """Regulated maximum flow, kg/s (100 kg/h)."""

    def __post_init__(self) -> None:
        if self.capacity <= 0.0:
            raise ConfigError("fuel capacity must be positive")
        if self.max_flow_rate <= 0.0:
            raise ConfigError("fuel max_flow_rate must be positive")

    def to_dict(self) -> dict[str, Any]:
        return {"capacity": self.capacity, "max_flow_rate": self.max_flow_rate}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FuelProperties:
        unknown = set(data) - set(cls.__slots__)
        if unknown:
            raise ConfigError(f"unknown fuel key(s): {', '.join(sorted(unknown))}")
        return cls(**data)


def fuel_burned(
    engine_work: Joules,
    dt: Seconds,
    *,
    properties: FuelProperties | None = None,
    config: FuelConfig | None = None,
) -> Kilograms:
    """Fuel consumed producing ``engine_work`` over ``dt`` seconds.

    ``engine_work`` is the mechanical work the *internal combustion* engine
    did -- energy delivered by the electrical side does not burn fuel, which is
    exactly why a hybrid is more efficient.

    The regulated flow limit caps the answer, so a car cannot burn its way past
    the rules however hard it is being driven.
    """
    cfg = config or FuelConfig()
    props = properties or FuelProperties()
    if dt <= 0.0:
        return 0.0
    energy_per_kilogram = cfg.lower_heating_value * cfg.thermal_efficiency
    burned = max(engine_work, 0.0) / energy_per_kilogram + cfg.idle_flow * dt
    return min(burned, props.max_flow_rate * dt)
