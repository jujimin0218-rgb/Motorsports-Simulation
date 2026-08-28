"""The vehicle.

Project rule 11 is explicit: a car is not one overall rating.  It is a set of
systems that can each be developed independently, and the whole point of the
composition below is that adding ERS in Phase 5 or a differential in Phase 12
touches one subsystem and nothing else.

:class:`VehicleSpec` is what a team *built* -- pure data, loadable from JSON.
:class:`VehicleSetup` is how they are running it this weekend.
:class:`Vehicle` binds the two together with the models that evaluate them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..core.config import SimulationConfig
from ..core.errors import ConfigError
from ..core.units import Kilograms
from ..tyres.model import TyreModel
from .aero import AeroModel, AeroProperties
from .brakes import BrakeProperties, BrakeSystem
from .ers import ErsProperties
from .fuel import FuelProperties
from .mass import MassProperties
from .power_unit import PowerUnit, PowerUnitProperties
from .setup import VehicleSetup

__all__ = ["Vehicle", "VehicleSpec"]


@dataclass(frozen=True)
class VehicleSpec:
    """A car's specification -- the machine itself, independent of setup."""

    name: str
    team: str | None = None
    mass: MassProperties = field(default_factory=MassProperties)
    aero: AeroProperties = field(default_factory=AeroProperties)
    power_unit: PowerUnitProperties = field(default_factory=PowerUnitProperties)
    brakes: BrakeProperties = field(default_factory=BrakeProperties)
    fuel: FuelProperties = field(default_factory=FuelProperties)
    ers: ErsProperties = field(default_factory=ErsProperties)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "team": self.team,
            "mass": self.mass.to_dict(),
            "aero": self.aero.to_dict(),
            "power_unit": self.power_unit.to_dict(),
            "brakes": self.brakes.to_dict(),
            "fuel": self.fuel.to_dict(),
            "ers": self.ers.to_dict(),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VehicleSpec:
        if "name" not in data:
            raise ConfigError("vehicle data is missing the 'name' key")
        known = {
            "name", "team", "mass", "aero", "power_unit", "brakes", "fuel",
            "ers", "metadata",
        }
        unknown = set(data) - known
        if unknown:
            raise ConfigError(f"unknown vehicle key(s): {', '.join(sorted(unknown))}")
        return cls(
            name=data["name"],
            team=data.get("team"),
            mass=MassProperties.from_dict(data.get("mass", {})),
            aero=AeroProperties.from_dict(data.get("aero", {})),
            power_unit=PowerUnitProperties.from_dict(data.get("power_unit", {})),
            brakes=BrakeProperties.from_dict(data.get("brakes", {})),
            fuel=FuelProperties.from_dict(data.get("fuel", {})),
            ers=ErsProperties.from_dict(data.get("ers", {})),
            metadata=dict(data.get("metadata", {})),
        )


class Vehicle:
    """A specified car, set up and ready to be simulated.

    Immutable: :meth:`with_setup` returns a new vehicle rather than mutating
    this one, so several setups of the same car can be evaluated side by side.
    """

    __slots__ = ("_spec", "_setup", "_config", "aero", "power_unit", "brakes", "tyre_model")

    def __init__(
        self,
        spec: VehicleSpec,
        setup: VehicleSetup | None = None,
        config: SimulationConfig | None = None,
    ) -> None:
        self._spec = spec
        self._setup = setup or VehicleSetup()
        self._config = config or SimulationConfig()
        self.aero = AeroModel(spec.aero, self._config.aero)
        self.power_unit = PowerUnit(spec.power_unit, self._config.powertrain)
        self.brakes = BrakeSystem(spec.brakes)
        self.tyre_model = TyreModel(self._config.tyres, self._config.wet)

    # -- identity ------------------------------------------------------------

    @property
    def spec(self) -> VehicleSpec:
        return self._spec

    @property
    def setup(self) -> VehicleSetup:
        return self._setup

    @property
    def config(self) -> SimulationConfig:
        return self._config

    @property
    def name(self) -> str:
        return self._spec.name

    @property
    def mass(self) -> MassProperties:
        return self._spec.mass

    # -- derived -------------------------------------------------------------

    @property
    def wing_level(self) -> float:
        return self._setup.wing_level

    @property
    def brake_bias_front(self) -> float:
        if self._setup.brake_bias_front is not None:
            return self._setup.brake_bias_front
        return self._spec.brakes.brake_bias_front

    def total_mass(self, fuel_mass: Kilograms | None = None) -> Kilograms:
        """Mass including fuel, kg."""
        fuel = self._setup.fuel_load if fuel_mass is None else fuel_mass
        return self._spec.mass.total_mass(fuel)

    def downforce_area(self, *, drs_open: bool = False) -> float:
        return self.aero.downforce_area(self.wing_level, drs_open=drs_open)

    def drag_area(self, *, drs_open: bool = False) -> float:
        return self.aero.drag_area(self.wing_level, drs_open=drs_open)

    @property
    def aero_efficiency(self) -> float:
        return self._spec.aero.efficiency(self.wing_level)

    # -- variation -----------------------------------------------------------

    def with_setup(self, setup: VehicleSetup) -> Vehicle:
        """The same car, run differently."""
        return Vehicle(self._spec, setup, self._config)

    def with_wing(self, wing_level: float) -> Vehicle:
        return self.with_setup(self._setup.with_wing(wing_level))

    def with_spec(self, spec: VehicleSpec) -> Vehicle:
        """A different car, run the same way -- for A/B comparisons."""
        return Vehicle(spec, self._setup, self._config)

    def to_dict(self) -> dict[str, Any]:
        return {
            "spec": self._spec.to_dict(),
            "setup": self._setup.to_dict(),
            "derived": {
                "dry_mass": self._spec.mass.dry_mass,
                "total_mass": self.total_mass(),
                "downforce_area": self.downforce_area(),
                "drag_area": self.drag_area(),
                "aero_efficiency": self.aero_efficiency,
                "wheel_power": self.power_unit.wheel_power,
                "max_tractive_force": self._spec.power_unit.max_tractive_force,
            },
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"Vehicle({self._spec.name!r}, wing={self.wing_level:.2f}, "
            f"mass={self.total_mass():.0f} kg)"
        )
