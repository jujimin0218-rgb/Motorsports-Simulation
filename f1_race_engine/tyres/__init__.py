"""Tyres: compounds, grip, temperature and degradation."""

from __future__ import annotations

from .compound import CompoundFamily, CompoundSet, TyreCompound
from .degradation import thermal_damage_increment, wear_grip_factor
from .io import builtin_compound_sets, load_builtin_compounds, load_compound_set
from .model import GripLimit, TyreModel
from .state import TyreState
from .temperature import ThermalStep, thermal_grip_factor, update_temperatures
from .wear import management_factor, thermal_wear_factor, wear_increment

__all__ = [
    "CompoundFamily", "CompoundSet", "GripLimit", "ThermalStep", "TyreCompound",
    "TyreModel", "TyreState", "builtin_compound_sets", "load_builtin_compounds",
    "load_compound_set", "management_factor", "thermal_damage_increment",
    "thermal_grip_factor", "thermal_wear_factor", "update_temperatures",
    "wear_grip_factor", "wear_increment",
]
