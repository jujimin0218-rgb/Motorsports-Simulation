"""Core infrastructure: units, configuration, randomness, state and events."""

from __future__ import annotations

from .config import (
    ConfigNode,
    PhysicsConfig,
    RandomnessConfig,
    SimulationConfig,
    TrackBuildConfig,
    TrackConditionsConfig,
    TrackValidationConfig,
    config_from_overrides,
    default_config,
    load_config,
    save_config,
)
from .errors import (
    ConfigError,
    F1EngineError,
    TrackBuildError,
    TrackDataError,
    TrackError,
    TrackValidationError,
    UnitError,
)
from .events import Event, EventBus, Subscription
from .interpolation import (
    ConstantProfile,
    ControlPoint,
    PiecewiseProfile,
    clamp,
    inverse_lerp,
    lerp,
    smoothstep,
)
from .rng import RandomStream, RngHub, RngSnapshot, derive_seed
from .state import (
    MutableState,
    SimulationClock,
    Snapshotable,
    SnapshotRecorder,
    StateSnapshot,
)

__all__ = [
    "ConfigError",
    "ConfigNode",
    "ConstantProfile",
    "ControlPoint",
    "Event",
    "EventBus",
    "F1EngineError",
    "MutableState",
    "PhysicsConfig",
    "PiecewiseProfile",
    "RandomStream",
    "RandomnessConfig",
    "RngHub",
    "RngSnapshot",
    "SimulationClock",
    "SimulationConfig",
    "Snapshotable",
    "SnapshotRecorder",
    "StateSnapshot",
    "Subscription",
    "TrackBuildConfig",
    "TrackBuildError",
    "TrackConditionsConfig",
    "TrackDataError",
    "TrackError",
    "TrackValidationConfig",
    "TrackValidationError",
    "UnitError",
    "clamp",
    "config_from_overrides",
    "default_config",
    "derive_seed",
    "inverse_lerp",
    "lerp",
    "load_config",
    "save_config",
    "smoothstep",
]
