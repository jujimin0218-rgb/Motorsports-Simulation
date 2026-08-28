"""F1 race simulation engine.

A physics-based Formula 1 simulator.  Lap times are the *result* of simulating
a car driving a real distance-based track model -- never a random draw and
never a per-track correction (project rules 2.1 to 2.4).

Current status: **Phase 9 (overtaking and defence)** -- everything from the
track model up: a car that obeys a real force balance, a lap time that is the
integral of a speed profile, a driver who steps that car around the circuit,
consumables that change underneath all of it, a whole race weekend with weather
that moves on its own and a strategist that prices its own pit stops -- and now
a field that can see each other, with dirty air, the tow, DRS, traffic that
costs time and overtakes that come out of the gap closing rather than out of a
dice roll.  See ``docs/ARCHITECTURE.md`` for the full plan.
"""

from __future__ import annotations

__version__ = "0.10.1"

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
from .environment import (
    AmbientConditions,
    Forecast,
    TrackEvolution,
    WeatherModel,
    WeatherState,
)
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
from .race import (
    Classification,
    Gap,
    LapRecord,
    PitLane,
    PitStop,
    QualifyingResult,
    QualifyingSession,
    RaceEntry,
    RaceResult,
    RaceSession,
    RaceStrategy,
    StrategyPlan,
    TimingTower,
    Weekend,
    WeekendResult,
    compound_for_conditions,
    pit_loss,
    plan_race,
)
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
    "Classification",
    "CompoundSet",
    "Driver",
    "DriverAttributes",
    "DriverInput",
    "ErsProperties",
    "ErsState",
    "EventBus",
    "Forecast",
    "FuelProperties",
    "Gap",
    "LapRecord",
    "LapResult",
    "LapSimulator",
    "LapTimeResult",
    "PerformanceLimits",
    "PitLane",
    "PitStop",
    "QualifyingResult",
    "QualifyingSession",
    "RaceEntry",
    "RaceResult",
    "RaceSession",
    "RaceStrategy",
    "RngHub",
    "SpeedProfile",
    "StrategyPlan",
    "Telemetry",
    "SimulationConfig",
    "TimingTower",
    "TrackEvolution",
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
    "WeatherModel",
    "WeatherState",
    "Weekend",
    "WeekendResult",
    "__version__",
    "benchmark_vehicle",
    "build_track",
    "builtin_driver_names",
    "compute_lap_time",
    "compound_for_conditions",
    "compute_speed_profile",
    "builtin_compound_sets",
    "builtin_track_names",
    "builtin_vehicle_names",
    "corner_speed_limit",
    "default_config",
    "pit_loss",
    "plan_race",
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
