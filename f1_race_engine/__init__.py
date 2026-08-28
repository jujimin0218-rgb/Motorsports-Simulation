"""F1 race simulation engine.

A physics-based Formula 1 simulator.  Lap times are the *result* of simulating
a car driving a real distance-based track model -- never a random draw and
never a per-track correction (project rules 2.1 to 2.4).

Current status: **Phase 5 (tyres, fuel and energy)** -- core infrastructure, the
track model, a car that obeys a real force balance, a lap time that is the
integral of a speed profile, a driver who steps that car around the circuit and
leaves telemetry behind, and consumables that change underneath all of it: tyres
that heat and wear from the work they do, fuel burned from the engine's work,
and an energy store that has to recover what it deploys.  See
``docs/ARCHITECTURE.md`` for the full plan and ``docs/PHASE5.md`` for what this
phase delivers.
"""

from __future__ import annotations

__version__ = "0.5.0"

from .core import (
    EventBus,
    RngHub,
    SimulationConfig,
    default_config,
    load_config,
    save_config,
)
from .driver import Driver, DriverAttributes, DriverInput
from .driver.io import builtin_driver_names, load_builtin_driver, load_driver_lineup
from .environment import AmbientConditions
from .physics import (
    LapTimeResult,
    PerformanceLimits,
    SpeedProfile,
    compute_lap_time,
    compute_speed_profile,
    corner_speed_limit,
    format_lap_result,
    longitudinal_forces,
    max_acceleration,
    max_deceleration,
    max_lateral_acceleration,
)
from .physics.benchmark import benchmark_vehicle, format_benchmark
from .physics.lap_validation import validate_lap
from .physics.setup_search import optimal_wing_level, wing_level_sweep
from .physics.validation import validate_vehicle
from .simulation import LapResult, LapSimulator, Telemetry, simulate_lap
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
from .vehicle.ers import ErsProperties, ErsState
from .vehicle.fuel import FuelProperties
from .vehicle.io import builtin_vehicle_names, load_builtin_vehicle

__all__ = [
    "AmbientConditions",
    "CompoundSet",
    "Driver",
    "DriverAttributes",
    "DriverInput",
    "ErsProperties",
    "ErsState",
    "EventBus",
    "FuelProperties",
    "LapResult",
    "LapSimulator",
    "LapTimeResult",
    "PerformanceLimits",
    "RngHub",
    "SpeedProfile",
    "Telemetry",
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
    "builtin_driver_names",
    "compute_lap_time",
    "compute_speed_profile",
    "builtin_compound_sets",
    "builtin_track_names",
    "builtin_vehicle_names",
    "corner_speed_limit",
    "default_config",
    "format_benchmark",
    "format_lap_result",
    "load_builtin_compounds",
    "load_builtin_driver",
    "load_builtin_vehicle",
    "load_driver_lineup",
    "load_config",
    "load_track",
    "longitudinal_forces",
    "max_acceleration",
    "max_deceleration",
    "max_lateral_acceleration",
    "optimal_wing_level",
    "save_config",
    "simulate_lap",
    "track_report",
    "validate_lap",
    "validate_track",
    "validate_vehicle",
    "wing_level_sweep",
]
