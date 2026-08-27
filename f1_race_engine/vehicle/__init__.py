"""The vehicle: a set of independently developable systems (project rule 11)."""

from __future__ import annotations

from .aero import AeroForces, AeroModel, AeroProperties
from .brakes import BrakeProperties, BrakeSystem
from .io import builtin_vehicle_names, load_builtin_vehicle, load_vehicle_spec
from .mass import MassProperties
from .model import Vehicle, VehicleSpec
from .power_unit import PowerUnit, PowerUnitProperties
from .setup import HIGH_DOWNFORCE, LOW_DOWNFORCE, MEDIUM_DOWNFORCE, VehicleSetup
from .state import VehicleState

__all__ = [
    "AeroForces", "AeroModel", "AeroProperties", "BrakeProperties", "BrakeSystem",
    "HIGH_DOWNFORCE", "LOW_DOWNFORCE", "MEDIUM_DOWNFORCE", "MassProperties",
    "PowerUnit", "PowerUnitProperties", "Vehicle", "VehicleSetup", "VehicleSpec",
    "VehicleState", "builtin_vehicle_names", "load_builtin_vehicle",
    "load_vehicle_spec",
]
