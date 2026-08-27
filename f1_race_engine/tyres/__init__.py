"""Tyres: compounds, grip, and (from Phase 5) temperature and degradation."""

from __future__ import annotations

from .compound import CompoundFamily, CompoundSet, TyreCompound
from .io import builtin_compound_sets, load_builtin_compounds, load_compound_set
from .model import GripLimit, TyreModel
from .state import TyreState

__all__ = [
    "CompoundFamily", "CompoundSet", "GripLimit", "TyreCompound", "TyreModel",
    "TyreState", "builtin_compound_sets", "load_builtin_compounds",
    "load_compound_set",
]
