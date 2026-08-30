"""Simulation: the layer where track, vehicle, driver and physics meet.

Project rule 4 keeps the physics core and the race core apart.  A lap belongs
to neither -- it needs the physics to move the car and the driver to decide what
to ask of it, but it knows nothing about positions, gaps or strategy.  So it
lives here, between them, and the race core (Phases 6-7) is built on top.
"""

from __future__ import annotations

from .lap import LapResult, LapSimulator, simulate_lap
from .telemetry import Telemetry, TelemetrySample

__all__ = [
    "LapResult", "LapSimulator", "Telemetry", "TelemetrySample", "simulate_lap",
]
