"""F1 race simulation engine.

A physics-based Formula 1 simulator.  Lap times are the *result* of simulating
a car driving a real distance-based track model -- never a random draw and
never a per-track correction (project rules 2.1 to 2.4).

Current status: **Phase 1 (foundation)** -- core infrastructure and the track
model.  See ``docs/ARCHITECTURE.md`` for the full plan and ``docs/PHASE1.md``
for what this phase delivers.
"""

from __future__ import annotations

__version__ = "0.1.0"

from .core import (
    EventBus,
    RngHub,
    SimulationConfig,
    default_config,
    load_config,
    save_config,
)
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

__all__ = [
    "EventBus",
    "RngHub",
    "SimulationConfig",
    "Track",
    "TrackBuilder",
    "TrackDefinition",
    "TrackState",
    "__version__",
    "build_track",
    "builtin_track_names",
    "default_config",
    "load_config",
    "load_track",
    "save_config",
    "track_report",
    "validate_track",
]
