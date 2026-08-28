"""Tyre state.

One instance per car (Phase 2 treats the four tyres as a set; per-corner state
arrives with the suspension model in Phase 12).

Phase 2 left this deliberately inert -- :meth:`TyreState.grip_multiplier`
returned exactly 1.0 -- with the promise that Phase 5 would fill in that one
method and the fields it reads, and nothing downstream would have to change.
That is what happened: the physics still asks the tyre for one number, and the
number is now the product of three real effects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..core.config import TyreThermalConfig, TyreWearConfig
from ..core.state import MutableState
from .compound import TyreCompound
from .degradation import thermal_damage_increment, wear_grip_factor
from .temperature import thermal_grip_factor, update_temperatures
from .wear import wear_increment

__all__ = ["TyreState"]


@dataclass
class TyreState(MutableState):
    """Condition of the tyres currently fitted."""

    compound: TyreCompound = field(default_factory=lambda: TyreCompound("Medium", "M"))

    age_laps: float = 0.0
    """Laps completed on this set."""

    age_distance: float = 0.0
    """Distance covered on this set, m."""

    wear: float = 0.0
    """Tread used, 0 (new) to 1 (worn out).  Driven from Phase 5."""

    surface_temperature: float | None = None
    """Tread surface temperature, degC.

    Defaults to the compound's own optimum, so a freshly constructed state is a
    tyre in its working window -- the right idealisation for a limit lap or a
    benchmark.  A set coming out of the blankets at the start of a stint is
    colder than that; :meth:`fit` sets it accordingly."""

    carcass_temperature: float | None = None
    """Carcass bulk temperature, degC.  Defaults just below the surface."""

    pressure: float = 152_000.0
    """Inflation pressure, Pa (about 22 psi cold)."""

    thermal_damage: float = 0.0
    """Grip permanently lost to overheating, 0 to 1.  Does not recover when
    the tyre cools -- a cooked set stays cooked."""

    peak_surface_temperature: float = 0.0
    """Hottest the tread has been on this set, degC.  Kept for the stint
    report: it is usually the clearest explanation of why a set went away."""

    grip: float = 1.0
    """The condition-derived multiplier on the compound's peak friction.

    Stored rather than derived on demand.  The physics asks for this number
    thousands of times a lap and it only changes when the tyre does, so it is
    computed once per step -- by :meth:`refresh`, which is the only place that
    knows the calibration -- and simply read everywhere else."""

    def __post_init__(self) -> None:
        if self.surface_temperature is None:
            self.surface_temperature = self.compound.optimal_temperature
        if self.carcass_temperature is None:
            self.carcass_temperature = self.surface_temperature - 5.0
        self.peak_surface_temperature = max(
            self.peak_surface_temperature, self.surface_temperature
        )
        self.refresh()

    def snapshot(self) -> dict[str, Any]:
        return {
            "compound": self.compound.code,
            "age_laps": self.age_laps,
            "age_distance": self.age_distance,
            "wear": self.wear,
            "surface_temperature": self.surface_temperature,
            "carcass_temperature": self.carcass_temperature,
            "pressure": self.pressure,
            "thermal_damage": self.thermal_damage,
            "peak_surface_temperature": self.peak_surface_temperature,
            "grip_multiplier": self.grip,
        }

    def refresh(
        self,
        thermal_config: TyreThermalConfig | None = None,
        wear_config: TyreWearConfig | None = None,
    ) -> float:
        """Recompute :attr:`grip` from the tyre's present condition.

        The product of three independent effects, each owned by its own module:

        * being inside or outside the temperature window;
        * how much tread has gone;
        * how much of the tyre has been permanently cooked.

        Everything downstream -- the grip model, the speed profile, the lap
        simulation -- reads the one number this produces and nothing else.
        """
        self.grip = (
            thermal_grip_factor(self.compound, self.surface_temperature, thermal_config)
            * wear_grip_factor(self.wear, wear_config)
            * (1.0 - self.thermal_damage)
        )
        return self.grip

    def grip_multiplier(self) -> float:
        """The current multiplier on the compound's peak friction."""
        return self.grip

    @property
    def is_worn_out(self) -> bool:
        return self.wear >= 1.0

    @property
    def in_working_window(self) -> bool:
        return (
            abs(self.surface_temperature - self.compound.optimal_temperature)
            <= self.compound.temperature_window
        )

    def update(
        self,
        *,
        friction_force: float,
        speed: float,
        distance: float,
        dt: float,
        air_temperature: float,
        track_temperature: float,
        tyre_management: float = 0.85,
        thermal_config: TyreThermalConfig | None = None,
        wear_config: TyreWearConfig | None = None,
    ) -> None:
        """Advance temperature, wear and damage over one step, in place.

        Called once per segment by the lap simulation.  Mutating rather than
        returning a copy is deliberate: a race is twenty cars times thousands of
        segments times dozens of laps, and allocating a state object for each
        would dominate the runtime.
        """
        thermal = thermal_config or TyreThermalConfig()
        step = update_temperatures(
            surface_temperature=self.surface_temperature,
            carcass_temperature=self.carcass_temperature,
            friction_force=friction_force,
            speed=speed,
            air_temperature=air_temperature,
            track_temperature=track_temperature,
            dt=dt,
            hysteresis=self.compound.wear_rate**thermal.hysteresis_exponent,
            config=thermal,
        )
        self.surface_temperature = step.surface_temperature
        self.carcass_temperature = step.carcass_temperature
        self.peak_surface_temperature = max(
            self.peak_surface_temperature, step.surface_temperature
        )

        self.wear = min(
            1.0,
            self.wear
            + wear_increment(
                self.compound,
                friction_force=friction_force,
                distance=distance,
                surface_temperature=self.surface_temperature,
                tyre_management=tyre_management,
                config=wear_config,
            ),
        )
        self.thermal_damage = min(
            (wear_config or TyreWearConfig()).max_thermal_damage,
            self.thermal_damage
            + thermal_damage_increment(
                self.surface_temperature,
                self.compound.optimal_temperature,
                self.compound.temperature_window,
                dt,
                config=wear_config,
            ),
        )
        self.age_distance += distance
        self.refresh(thermal, wear_config)

    def fit(self, compound: TyreCompound, *, temperature: float | None = None) -> None:
        """Fit a fresh set of ``compound``.

        ``temperature`` defaults to a blanket-warmed tyre a little below its
        working window, which is what a car leaves the pit box on.
        """
        self.compound = compound
        self.age_laps = 0.0
        self.age_distance = 0.0
        self.wear = 0.0
        self.thermal_damage = 0.0
        start = (
            compound.optimal_temperature - compound.temperature_window
            if temperature is None
            else temperature
        )
        self.surface_temperature = start
        self.carcass_temperature = start - 10.0
        self.peak_surface_temperature = start
        self.refresh()

    @property
    def is_wet_weather(self) -> bool:
        return self.compound.is_wet_weather

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"TyreState({self.compound.code}, {self.age_laps:.1f} laps, "
            f"wear {self.wear:.0%}, {self.surface_temperature:.0f}C, "
            f"grip {self.grip:.3f})"
        )
