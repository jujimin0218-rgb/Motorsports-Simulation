"""Environment: the atmosphere and track conditions a session runs in.

Air density for the aerodynamic model, weather that moves through a session on
its own, and a track surface that rubbers in, floods and dries out from what
actually happens on it.
"""

from __future__ import annotations

from .conditions import (
    AmbientConditions,
    air_density,
    headwind_component,
    saturation_vapour_pressure,
)
from .evolution import TrackEvolution
from .weather import Forecast, WeatherModel, WeatherState

__all__ = [
    "AmbientConditions",
    "Forecast",
    "TrackEvolution",
    "WeatherModel",
    "WeatherState",
    "air_density",
    "headwind_component",
    "saturation_vapour_pressure",
]
