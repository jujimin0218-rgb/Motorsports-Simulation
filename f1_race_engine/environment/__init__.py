"""Environment: the atmosphere and track conditions a session runs in.

Phase 2 needs air density for the aerodynamic model.  Wind, rain, temperature
evolution and track evolution join in Phase 10 behind the same interface.
"""

from __future__ import annotations

from .conditions import AmbientConditions, air_density, saturation_vapour_pressure

__all__ = ["AmbientConditions", "air_density", "saturation_vapour_pressure"]
