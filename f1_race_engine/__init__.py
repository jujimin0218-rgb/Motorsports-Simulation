"""F1 race simulation engine.

A physics-based Formula 1 simulator.  Lap times are the *result* of simulating
a car driving a real distance-based track model -- never a random draw and
never a per-track correction (project rules 2.1 to 2.4).

Current status: **Phase 2 (basic vehicle physics)** -- core infrastructure, the
track model, and a car that obeys a real force balance.  See
``docs/ARCHITECTURE.md`` for the full plan and ``docs/PHASE2.md`` for what this
phase delivers.
"""

from __future__ import annotations

__version__ = "0.2.0"

from .core import (
    EventBus,
    RngHub,
    SimulationConfig,
    default_config,
    load_config,
    save_config,
)
from .environment import AmbientConditions
from .physics import (
    corner_speed_limit,
    longitudinal_forces,
    max_acceleration,
    max_deceleration,
    max_lateral_acceleration,
)
from .physics.benchmark import benchmark_vehicle, format_benchmark
from .physics.validation import validate_vehicle
from .track import (
    Track,
    TrackBuilder,
    TrackDefinition,
    TrackState,
    build_track,
    builtin_track_names,
    load_track,
    track_report,
    validate_track,
)
from .tyres import CompoundSet, TyreCompound, TyreModel, TyreState
from .tyres.io import builtin_compound_sets, load_builtin_compounds
from .vehicle import Vehicle, VehicleSetup, VehicleSpec, VehicleState
from .vehicle.io import builtin_vehicle_names, load_builtin_vehicle

__all__ = [
    "AmbientConditions",
    "CompoundSet",
    "EventBus",
    "RngHub",
    "SimulationConfig",
    "Track",
    "TrackBuilder",
    "TrackDefinition",
    "TrackState",
    "TyreCompound",
    "TyreModel",
    "TyreState",
    "Vehicle",
    "VehicleSetup",
    "VehicleSpec",
    "VehicleState",
    "__version__",
    "benchmark_vehicle",
    "build_track",
    "builtin_compound_sets",
    "builtin_track_names",
    "builtin_vehicle_names",
    "corner_speed_limit",
    "default_config",
    "format_benchmark",
    "load_builtin_compounds",
    "load_builtin_vehicle",
    "load_config",
    "load_track",
    "longitudinal_forces",
    "max_acceleration",
    "max_deceleration",
    "max_lateral_acceleration",
    "save_config",
    "track_report",
    "validate_track",
    "validate_vehicle",
]
