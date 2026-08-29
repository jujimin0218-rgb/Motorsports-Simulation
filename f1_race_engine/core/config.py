"""Configuration tree for the simulation.

Project rule 37: physical constants and calibration parameters must not be
scattered as literals through the code.  Every tunable number lives in a frozen
dataclass here, so the model can be re-calibrated against real telemetry by
editing data, never code.

The tree is built from :class:`ConfigNode`, which provides recursive
``to_dict`` / ``from_dict`` / ``merged`` for free.  Adding a subsystem in a
later phase means adding one dataclass and one field on
:class:`SimulationConfig`; nothing that already exists needs to change.

Unknown keys are rejected rather than ignored.  During calibration a silently
dropped typo ("aero_efficency") would look like a parameter that has no effect,
which is far more expensive to debug than an immediate error.
"""

from __future__ import annotations

import json
import types
import typing
from collections.abc import Mapping
from dataclasses import dataclass, field, fields, is_dataclass, replace
from pathlib import Path
from typing import Any, TypeVar, Union, get_args, get_origin

from .errors import ConfigError
from .units import STANDARD_GRAVITY, ISA_SEA_LEVEL_AIR_DENSITY, deg_to_rad

TNode = TypeVar("TNode", bound="ConfigNode")


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def require_positive(name: str, value: float) -> None:
    """Raise :class:`ConfigError` unless ``value > 0``."""
    if not value > 0.0:
        raise ConfigError(f"{name} must be positive, got {value!r}")


def require_non_negative(name: str, value: float) -> None:
    """Raise :class:`ConfigError` unless ``value >= 0``."""
    if value < 0.0:
        raise ConfigError(f"{name} must be non-negative, got {value!r}")


def require_range(name: str, value: float, low: float, high: float) -> None:
    """Raise :class:`ConfigError` unless ``low <= value <= high``."""
    if not low <= value <= high:
        raise ConfigError(f"{name} must lie in [{low}, {high}], got {value!r}")


def require_ordered(low_name: str, low: float, high_name: str, high: float) -> None:
    """Raise :class:`ConfigError` unless ``low <= high``."""
    if low > high:
        raise ConfigError(
            f"{low_name} ({low}) must not exceed {high_name} ({high})"
        )


# ---------------------------------------------------------------------------
# Base node
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConfigNode:
    """Base class for every configuration section.

    Subclasses are frozen dataclasses.  Override :meth:`validate` to enforce
    parameter ranges; it runs automatically on construction, so an invalid
    config can never reach the physics.
    """

    def __post_init__(self) -> None:
        self.validate()

    # -- hooks ---------------------------------------------------------------

    def validate(self) -> None:
        """Check parameter ranges.  Override in subclasses."""

    # -- serialisation -------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Recursively convert to plain JSON-compatible data."""
        result: dict[str, Any] = {}
        for f in fields(self):
            result[f.name] = _to_plain(getattr(self, f.name))
        return result

    @classmethod
    def from_dict(cls: type[TNode], data: Mapping[str, Any]) -> TNode:
        """Build an instance from plain data, rejecting unknown keys."""
        if not isinstance(data, Mapping):
            raise ConfigError(
                f"{cls.__name__} expects a mapping, got {type(data).__name__}"
            )
        hints = typing.get_type_hints(cls)
        known = {f.name for f in fields(cls)}
        unknown = set(data) - known
        if unknown:
            raise ConfigError(
                f"unknown {cls.__name__} key(s): {', '.join(sorted(unknown))}; "
                f"known keys: {', '.join(sorted(known))}"
            )
        kwargs: dict[str, Any] = {}
        for name, value in data.items():
            kwargs[name] = _coerce(value, hints[name], f"{cls.__name__}.{name}")
        return cls(**kwargs)

    def merged(self: TNode, overrides: Mapping[str, Any]) -> TNode:
        """Return a copy with ``overrides`` deep-merged in.

        Nested sections may be given either as plain dicts (merged key by key)
        or as ready-made :class:`ConfigNode` instances (replaced wholesale).
        """
        if not isinstance(overrides, Mapping):
            raise ConfigError(
                f"overrides for {type(self).__name__} must be a mapping, "
                f"got {type(overrides).__name__}"
            )
        known = {f.name for f in fields(self)}
        unknown = set(overrides) - known
        if unknown:
            raise ConfigError(
                f"unknown {type(self).__name__} key(s): {', '.join(sorted(unknown))}"
            )
        hints = typing.get_type_hints(type(self))
        changes: dict[str, Any] = {}
        for name, value in overrides.items():
            current = getattr(self, name)
            if isinstance(current, ConfigNode) and isinstance(value, Mapping):
                changes[name] = current.merged(value)
            else:
                changes[name] = _coerce(
                    value, hints[name], f"{type(self).__name__}.{name}"
                )
        return replace(self, **changes)

    # -- convenience ---------------------------------------------------------

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=False)

    def describe(self, prefix: str = "") -> str:
        """Render the section as flat ``key = value`` lines, for logs."""
        lines: list[str] = []
        for f in fields(self):
            value = getattr(self, f.name)
            key = f"{prefix}{f.name}"
            if isinstance(value, ConfigNode):
                lines.append(value.describe(prefix=f"{key}."))
            else:
                lines.append(f"{key} = {value!r}")
        return "\n".join(lines)


def _to_plain(value: Any) -> Any:
    if isinstance(value, ConfigNode):
        return value.to_dict()
    if isinstance(value, tuple):
        return [_to_plain(v) for v in value]
    if isinstance(value, list):
        return [_to_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _to_plain(v) for k, v in value.items()}
    return value


def _coerce(value: Any, hint: Any, path: str) -> Any:
    """Convert plain data to the type declared by ``hint``."""
    origin = get_origin(hint)

    # Optional[X] / X | None / unions
    if origin is Union or origin is types.UnionType:
        args = [a for a in get_args(hint) if a is not type(None)]
        if value is None:
            if len(args) < len(get_args(hint)):
                return None
            raise ConfigError(f"{path} may not be null")
        last_error: Exception | None = None
        for arg in args:
            try:
                return _coerce(value, arg, path)
            except ConfigError as exc:  # try the next member of the union
                last_error = exc
        raise ConfigError(f"{path}: {last_error}")

    if origin in (tuple, list):
        args = get_args(hint)
        if not isinstance(value, (list, tuple)):
            raise ConfigError(f"{path} must be a list, got {type(value).__name__}")
        if len(args) == 2 and args[1] is Ellipsis:
            items = [_coerce(v, args[0], f"{path}[]") for v in value]
        elif args:
            if len(args) != len(value):
                raise ConfigError(
                    f"{path} expects {len(args)} item(s), got {len(value)}"
                )
            items = [_coerce(v, a, f"{path}[{i}]") for i, (v, a) in enumerate(zip(value, args))]
        else:
            items = list(value)
        return tuple(items) if origin is tuple else items

    if isinstance(hint, type) and issubclass(hint, ConfigNode):
        if isinstance(value, hint):
            return value
        return hint.from_dict(value)

    if hint is bool:
        if not isinstance(value, bool):
            raise ConfigError(f"{path} must be a bool, got {type(value).__name__}")
        return value

    if hint is int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigError(f"{path} must be an int, got {type(value).__name__}")
        return value

    if hint is float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ConfigError(f"{path} must be a number, got {type(value).__name__}")
        return float(value)

    if hint is str:
        if not isinstance(value, str):
            raise ConfigError(f"{path} must be a string, got {type(value).__name__}")
        return value

    if isinstance(hint, type) and is_dataclass(hint):
        return hint(**value) if isinstance(value, Mapping) else value

    return value


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PhysicsConfig(ConfigNode):
    """Universal physical constants and numerical guards.

    Only quantities that are genuinely global live here.  Anything that belongs
    to a subsystem (aero coefficients, tyre grip, engine torque) belongs to that
    subsystem's own config section, added in a later phase.
    """

    gravity: float = STANDARD_GRAVITY
    """Gravitational acceleration, m/s^2."""

    reference_air_density: float = ISA_SEA_LEVEL_AIR_DENSITY
    """Baseline air density, kg/m^3.  The environment model scales this with
    temperature, pressure and altitude from Phase 10 onward."""

    epsilon: float = 1.0e-9
    """Generic numerical tolerance for float comparisons."""

    min_integration_speed: float = 0.5
    """Speed floor, m/s, used when integrating ``dt = ds / v`` so that a car at
    rest cannot produce an infinite time step (project rule 26)."""

    def validate(self) -> None:
        require_positive("physics.gravity", self.gravity)
        require_positive("physics.reference_air_density", self.reference_air_density)
        require_positive("physics.epsilon", self.epsilon)
        require_positive("physics.min_integration_speed", self.min_integration_speed)


@dataclass(frozen=True)
class TrackBuildConfig(ConfigNode):
    """Controls how track definitions are turned into segments.

    Resolution is adaptive (project rule 7): straights are sampled coarsely,
    corner transitions finely.

    Everything here controls **sampling only**.  The circuit's geometry --
    corner radii, transition lengths, width, surface grip -- belongs to the
    track definition, not to this config, precisely so that changing the
    resolution cannot change the track.  ``tests/test_resolution.py`` enforces
    that separation.
    """

    straight_segment_length: float = 25.0
    """Target segment length on a straight, m."""

    corner_segment_length: float = 6.0
    """Target segment length through a constant-radius arc, m."""

    min_segment_length: float = 1.0
    """Hard floor on segment length, m.  Rule 7 requires 1 m to be reachable."""

    max_segment_length: float = 30.0
    """Hard ceiling on segment length, m."""

    max_heading_change_per_segment_deg: float = 2.5
    """Refinement criterion: no segment may turn the car by more than this."""

    max_curvature_change_per_segment: float = 0.0025
    """Refinement criterion: bound on the curvature change across a segment,
    1/m.  This is what puts extra resolution into corner entry and exit."""

    geometry_quadrature_intervals: int = 8
    """Simpson sub-intervals per segment when integrating the plan-view
    centreline.  Higher values tighten geometric closure at negligible cost."""

    def validate(self) -> None:
        require_positive("track_build.straight_segment_length", self.straight_segment_length)
        require_positive("track_build.corner_segment_length", self.corner_segment_length)
        require_positive("track_build.min_segment_length", self.min_segment_length)
        require_positive("track_build.max_segment_length", self.max_segment_length)
        require_ordered(
            "track_build.min_segment_length",
            self.min_segment_length,
            "track_build.max_segment_length",
            self.max_segment_length,
        )
        require_positive(
            "track_build.max_heading_change_per_segment_deg",
            self.max_heading_change_per_segment_deg,
        )
        require_positive(
            "track_build.max_curvature_change_per_segment",
            self.max_curvature_change_per_segment,
        )
        if self.geometry_quadrature_intervals < 2 or self.geometry_quadrature_intervals % 2:
            raise ConfigError(
                "track_build.geometry_quadrature_intervals must be an even "
                f"integer >= 2, got {self.geometry_quadrature_intervals}"
            )

    @property
    def max_heading_change_per_segment(self) -> float:
        """The heading-change refinement criterion in radians."""
        return deg_to_rad(self.max_heading_change_per_segment_deg)


@dataclass(frozen=True)
class TrackValidationConfig(ConfigNode):
    """Thresholds for the track validation suite (project rules 8 and 39)."""

    min_corner_radius: float = 6.0
    """Below this radius (m) a corner is rejected as non-physical."""

    warn_corner_radius: float = 10.0
    """Below this radius (m) a corner is flagged as suspiciously tight.
    Monaco's Fairmont hairpin sits near 9 m, so this is a warning, not an
    error."""

    curvature_continuity_tolerance: float = 1.0e-9
    """Maximum allowed curvature jump between neighbouring segments, 1/m.
    Segments carry linear curvature, so a well-formed track is continuous to
    floating-point precision; anything larger means broken data."""

    max_curvature_change_rate: float = 0.02
    """Maximum |dk/ds| within a segment, 1/m^2.  Catches turn-in that is far
    sharper than any real circuit."""

    curvature_spike_sigma: float = 8.0
    """Standard deviations above the mean |dk/ds| before a segment is
    reported as an isolated spike."""

    max_gradient: float = 0.25
    """Maximum |dz/ds|.  Eau Rouge runs near 0.18."""

    max_banking_deg: float = 35.0
    """Maximum track banking magnitude, degrees."""

    min_track_width: float = 6.0
    max_track_width: float = 30.0
    min_surface_grip: float = 0.3
    max_surface_grip: float = 1.6

    heading_closure_tolerance_deg: float = 1.0
    """A closed circuit must turn through a whole number of full turns."""

    position_closure_warning_fraction: float = 0.01
    position_closure_error_fraction: float = 0.05
    """Plan-view closure error, as a fraction of lap length, at which the
    geometry is warned about or rejected."""

    elevation_closure_tolerance: float = 1.0
    """Maximum elevation mismatch, m, between the end and start of a lap."""

    min_segment_length: float = 0.25
    max_segment_length: float = 60.0
    min_lap_length: float = 1000.0
    max_lap_length: float = 12000.0

    require_sectors: bool = True
    require_drs_zones: bool = False

    def validate(self) -> None:
        require_positive("track_validation.min_corner_radius", self.min_corner_radius)
        require_ordered(
            "track_validation.min_corner_radius",
            self.min_corner_radius,
            "track_validation.warn_corner_radius",
            self.warn_corner_radius,
        )
        require_positive(
            "track_validation.curvature_continuity_tolerance",
            self.curvature_continuity_tolerance,
        )
        require_positive(
            "track_validation.max_curvature_change_rate", self.max_curvature_change_rate
        )
        require_positive(
            "track_validation.curvature_spike_sigma", self.curvature_spike_sigma
        )
        require_positive("track_validation.max_gradient", self.max_gradient)
        require_positive("track_validation.max_banking_deg", self.max_banking_deg)
        require_ordered(
            "track_validation.min_track_width",
            self.min_track_width,
            "track_validation.max_track_width",
            self.max_track_width,
        )
        require_ordered(
            "track_validation.min_surface_grip",
            self.min_surface_grip,
            "track_validation.max_surface_grip",
            self.max_surface_grip,
        )
        require_ordered(
            "track_validation.position_closure_warning_fraction",
            self.position_closure_warning_fraction,
            "track_validation.position_closure_error_fraction",
            self.position_closure_error_fraction,
        )
        require_ordered(
            "track_validation.min_segment_length",
            self.min_segment_length,
            "track_validation.max_segment_length",
            self.max_segment_length,
        )
        require_ordered(
            "track_validation.min_lap_length",
            self.min_lap_length,
            "track_validation.max_lap_length",
            self.max_lap_length,
        )


@dataclass(frozen=True)
class TrackConditionsConfig(ConfigNode):
    """How session conditions modify the static surface grip.

    Every coefficient here is neutral at zero condition, so a green, dry track
    behaves exactly like its static definition.  Track evolution and weather
    (Phase 10) drive the condition values; these parameters decide what those
    values are worth, and they are meant to be calibrated against real session
    data rather than guessed once and forgotten.
    """

    rubber_grip_gain: float = 0.06
    """Grip gained at fully rubbered-in conditions (+6%)."""

    marble_grip_penalty: float = 0.25
    """Grip lost on a fully marbled surface (-25%)."""

    wet_surface_penalty: float = 0.18
    """Grip a *wet road* costs, once it is properly wet (-18%).

    This is the asphalt, not the tyre: a wet surface has a lower friction
    coefficient than a dry one even with no standing water on it, and that
    applies to every tyre equally.  What standing water does on top of it is a
    question about tread pattern, and lives in ``wet`` and
    :mod:`f1_race_engine.tyres.wet`."""

    reference_water_depth: float = 0.0002
    """Depth, m, beyond which the surface is simply wet and gets no wetter.

    Two tenths of a millimetre.  A damp track has most of the penalty already;
    the danger in deeper water is aquaplaning, which is the tyre's problem."""

    rubber_wash_rate: float = 0.35
    """Share of the rubber laid into the racing line that a fully wet track
    washes away per minute of rain."""

    min_grip_multiplier: float = 0.25
    """Floor on the combined multiplier, so grip can never reach zero."""

    def validate(self) -> None:
        require_non_negative(
            "track_conditions.rubber_grip_gain", self.rubber_grip_gain
        )
        require_range(
            "track_conditions.wet_surface_penalty", self.wet_surface_penalty, 0.0, 1.0
        )
        require_positive(
            "track_conditions.reference_water_depth", self.reference_water_depth
        )
        require_non_negative(
            "track_conditions.rubber_wash_rate", self.rubber_wash_rate
        )
        require_range(
            "track_conditions.marble_grip_penalty", self.marble_grip_penalty, 0.0, 1.0
        )
        require_range(
            "track_conditions.min_grip_multiplier", self.min_grip_multiplier, 0.0, 1.0
        )


@dataclass(frozen=True)
class WeatherConfig(ConfigNode):
    """How the weather moves (project rule 30).

    Everything here is a *rate* or a *time constant*, never a schedule.  A
    session's weather is drawn from these by the seeded RNG, so the same seed
    gives the same rain at the same moment and a different seed gives a
    different afternoon.
    """

    step: float = 30.0
    """Seconds of session time per weather update.  Weather moves on a scale of
    minutes, so resolving it finer costs time and buys nothing."""

    temperature_relaxation: float = 1_800.0
    """Time constant, s, for air temperature returning to the forecast mean."""

    temperature_volatility: float = 0.35
    """Standard deviation, K, of the air temperature's random walk per step."""

    track_relaxation: float = 900.0
    """Time constant, s, for the track surface chasing its target temperature.

    Asphalt has thermal mass: it lags the air by a quarter of an hour, which is
    why a cloud passing over cools the track long after it has gone."""

    solar_gain: float = 16.0
    """Kelvin the track runs above air temperature in full sun."""

    rain_track_cooling: float = 14.0
    """Kelvin the track loses in heavy rain, on top of losing the sun."""

    rain_air_cooling: float = 4.0
    """Kelvin the air loses in heavy rain.  Rain pulls the temperature the air
    is relaxing towards downwards rather than pushing the air itself, so a
    long shower cools the session by a bounded amount and it comes back."""

    shower_onset_per_hour: float = 0.0
    """Baseline rate, per hour, at which a shower starts.  The forecast's rain
    probability scales this; it is here so a dry-forecast session can still be
    given a chance of a surprise."""

    mean_shower_duration: float = 900.0
    """Average length of a shower, s.  Ending is a Poisson process, so showers
    have no fixed length -- some pass in three minutes and some settle in."""

    intensity_relaxation: float = 120.0
    """Time constant, s, for rain intensity moving towards its target.  Rain
    arrives and clears over a couple of minutes rather than instantly."""

    wind_relaxation: float = 600.0
    wind_volatility: float = 0.4
    """Standard deviation, m/s, of the wind speed's random walk per step."""

    wind_direction_volatility: float = 0.04
    """Standard deviation, radians, of the wind direction's drift per step."""

    def validate(self) -> None:
        require_positive("weather.step", self.step)
        require_positive("weather.temperature_relaxation", self.temperature_relaxation)
        require_non_negative(
            "weather.temperature_volatility", self.temperature_volatility
        )
        require_positive("weather.track_relaxation", self.track_relaxation)
        require_non_negative("weather.solar_gain", self.solar_gain)
        require_non_negative("weather.rain_track_cooling", self.rain_track_cooling)
        require_non_negative("weather.rain_air_cooling", self.rain_air_cooling)
        require_non_negative(
            "weather.shower_onset_per_hour", self.shower_onset_per_hour
        )
        require_positive("weather.mean_shower_duration", self.mean_shower_duration)
        require_positive("weather.intensity_relaxation", self.intensity_relaxation)
        require_positive("weather.wind_relaxation", self.wind_relaxation)
        require_non_negative("weather.wind_volatility", self.wind_volatility)
        require_non_negative(
            "weather.wind_direction_volatility", self.wind_direction_volatility
        )


@dataclass(frozen=True)
class TrackEvolutionConfig(ConfigNode):
    """How a track surface changes while a session runs (rule 30).

    Rubber, marbles and standing water all evolve from what is happening on
    track -- cars running, rain falling -- rather than from the clock.
    """

    rubber_per_car_lap: float = 0.006
    """Share of the remaining rubber deficit laid into the racing line by one
    car completing one lap.  Saturating, so the first runs do most of the work
    and a track is nearly in after a couple of hundred car-laps."""

    marbles_per_car_lap: float = 0.004
    """Marbles swept off the line by one car completing one lap.  They collect
    *beside* the racing line, so they cost nothing until a car leaves it."""

    rain_accumulation: float = 1.4e-5
    """Water depth gained, m/s, at full rain intensity -- about 50 mm an hour,
    which is torrential."""

    drainage_rate: float = 0.002
    """Share of the standing water that drains away per second on a level
    surface.  Proportional to depth, because deeper water flows away faster,
    which is what gives a circuit an equilibrium depth in steady rain rather
    than an ever-rising flood."""

    gradient_drainage: float = 0.05
    """Extra drainage, per second per unit of gradient.  A sloping section
    sheds water and the bottom of a dip holds it, which is why the wet patch on
    a circuit is always in the same place and nobody had to mark it."""

    dry_threshold: float = 1.0e-5
    """Depth, m, below which a segment counts as dry.

    A hundredth of a millimetre is a damp patch, not standing water, and
    without a threshold a segment that has drained stays nominally wet forever
    because floating-point numbers do not reach zero."""

    drying_per_car_lap: float = 0.004
    """Share of the standing water thrown off the racing line by one car
    completing one lap.

    This is what makes a drying line: the cars dry the track themselves, and
    only where they run."""

    def validate(self) -> None:
        require_non_negative(
            "track_evolution.rubber_per_car_lap", self.rubber_per_car_lap
        )
        require_non_negative(
            "track_evolution.marbles_per_car_lap", self.marbles_per_car_lap
        )
        require_non_negative(
            "track_evolution.rain_accumulation", self.rain_accumulation
        )
        require_non_negative("track_evolution.drainage_rate", self.drainage_rate)
        require_non_negative(
            "track_evolution.gradient_drainage", self.gradient_drainage
        )
        require_non_negative(
            "track_evolution.drying_per_car_lap", self.drying_per_car_lap
        )
        require_non_negative("track_evolution.dry_threshold", self.dry_threshold)


@dataclass(frozen=True)
class AeroConfig(ConfigNode):
    """Aerodynamic model parameters.

    The *car's* aero numbers -- lift and drag area -- live in its spec, because
    they describe that car.  What lives here is how the model treats them.
    """

    drs_drag_reduction: float = 0.13
    """Fraction of drag area removed when DRS is open.

    Regulated, so it is a property of the formula rather than of one team's
    car.  The aero model applies it; deciding *whether* DRS may be open is a
    race-core decision in Phase 9."""

    drs_downforce_loss: float = 0.10
    """Fraction of rear downforce lost when DRS is open.  Opening the flap
    costs grip as well as saving drag -- which is why DRS is a straight-line
    tool and not a corner one."""

    ground_effect_reference_speed: float = 40.0
    """Speed, m/s, below which the floor is treated as fully stalled in the
    simplified low-speed correction.  Phase 12 replaces this with a ride-height
    and porpoising model."""

    low_speed_downforce_floor: float = 0.0
    """Fraction of peak downforce still available as speed approaches zero.
    Zero is the honest simplification: downforce scales with v^2."""

    def validate(self) -> None:
        require_range("aero.drs_drag_reduction", self.drs_drag_reduction, 0.0, 0.9)
        require_range("aero.drs_downforce_loss", self.drs_downforce_loss, 0.0, 1.0)
        require_positive(
            "aero.ground_effect_reference_speed", self.ground_effect_reference_speed
        )
        require_range(
            "aero.low_speed_downforce_floor", self.low_speed_downforce_floor, 0.0, 1.0
        )


@dataclass(frozen=True)
class TyreConfig(ConfigNode):
    """Tyre model parameters.

    Compound-specific numbers (peak friction, load sensitivity, wear rate) are
    data and live in the compound files.  These are the shape of the model.
    """

    combined_grip_exponent: float = 2.0
    """Exponent of the friction ellipse: ``(Fx/F)^n + (Fy/F)^n = 1``.
    2.0 is the classic ellipse; racing tyres measure slightly above it."""

    min_normal_load: float = 100.0
    """Load floor, N, used when evaluating load sensitivity.  The power law
    diverges at zero load, and an unloaded tyre carries no force anyway."""

    def validate(self) -> None:
        require_range("tyres.combined_grip_exponent", self.combined_grip_exponent, 1.0, 4.0)
        require_positive("tyres.min_normal_load", self.min_normal_load)


@dataclass(frozen=True)
class PowertrainConfig(ConfigNode):
    """Powertrain and traction model parameters."""

    drivetrain_efficiency: float = 0.97
    """Fraction of crank power that reaches the road, mechanically.

    Gearbox and final drive friction only.  The other loss a drivetrain has --
    the time with no drive at all while a gear is changed -- is charged where
    it is actually paid, in :class:`~f1_race_engine.vehicle.gearbox.Gearbox`,
    because it costs a short gear a real share of itself and a top gear held
    down a straight nothing."""

    min_tractive_speed: float = 1.0
    """Speed floor, m/s, when converting power to force (``F = P / v``).
    Below it the torque limit governs anyway, and the division would blow up."""

    longitudinal_load_transfer: bool = True
    """Whether to shift vertical load between the axles under acceleration and
    braking.

    Quasi-static only: ``dN = m * a * h_cg / wheelbase``.  It is enabled because
    a rear-drive car's traction is decided by rear axle load, and ignoring the
    transfer understates standing-start acceleration by around 15%.  The full
    dynamic treatment -- suspension, damping, lateral transfer, pitch -- is
    Phase 12."""

    traction_solver_iterations: int = 8
    """Load transfer makes traction implicit (grip depends on load depends on
    acceleration depends on grip).  At most this many fixed-point passes settle
    it."""

    traction_solver_tolerance: float = 1e-5
    """Relative change below which the traction solve is finished.

    The iteration converges from below at a rate of roughly
    ``mu * h_cg / wheelbase``, so it is done long before the iteration cap --
    and the profile passes call it tens of thousands of times a lap, which
    makes stopping early the difference between a race that runs and one that
    does not."""

    def validate(self) -> None:
        require_range(
            "powertrain.drivetrain_efficiency", self.drivetrain_efficiency, 0.5, 1.0
        )
        require_positive("powertrain.min_tractive_speed", self.min_tractive_speed)
        if self.traction_solver_iterations < 1:
            raise ConfigError(
                "powertrain.traction_solver_iterations must be at least 1"
            )
        require_non_negative(
            "powertrain.traction_solver_tolerance", self.traction_solver_tolerance
        )


@dataclass(frozen=True)
class EnvironmentConfig(ConfigNode):
    """Default ambient conditions for a session."""

    air_temperature: float = 25.0
    track_temperature: float = 35.0
    pressure: float = 101_325.0
    relative_humidity: float = 0.4

    def validate(self) -> None:
        require_range("environment.air_temperature", self.air_temperature, -60.0, 70.0)
        require_range("environment.track_temperature", self.track_temperature, -60.0, 90.0)
        require_positive("environment.pressure", self.pressure)
        require_range("environment.relative_humidity", self.relative_humidity, 0.0, 1.0)


@dataclass(frozen=True)
class SpeedProfileConfig(ConfigNode):
    """Numerics for the quasi-steady-state speed profile."""

    max_passes: int = 8
    """Maximum forward/backward sweeps around the lap.

    A lap is a closed loop, so a braking zone can begin before the start/finish
    line and constrain speeds behind it.  Sweeping repeatedly until nothing
    changes is what makes the profile independent of where the lap is cut."""

    convergence_tolerance: float = 1.0e-4
    """Largest speed change, m/s, that still counts as converged."""

    corrector_steps: int = 1
    """Midpoint corrector passes on each energy update.

    ``v1^2 = v0^2 + 2*a*ds`` is exact for constant acceleration, but ``a``
    varies with speed.  Re-evaluating it at the midpoint speed makes each step
    second-order accurate, which is what lets a straight be sampled coarsely
    without biasing the lap time."""

    corner_speed_tolerance: float = 1.0e-3
    """Bisection tolerance, m/s, for the cornering limit."""

    minimum_speed: float = 3.0
    """Speed floor, m/s.  A corner that comes out slower than this is either
    a data error or a pit lane; the floor keeps ``dt = ds / v`` finite."""

    speed_ceiling: float = 150.0
    """Upper bound, m/s, for the cornering-limit search."""

    def validate(self) -> None:
        if self.max_passes < 1:
            raise ConfigError("speed_profile.max_passes must be at least 1")
        if self.corrector_steps < 0:
            raise ConfigError("speed_profile.corrector_steps must be non-negative")
        require_positive(
            "speed_profile.convergence_tolerance", self.convergence_tolerance
        )
        require_positive(
            "speed_profile.corner_speed_tolerance", self.corner_speed_tolerance
        )
        require_positive("speed_profile.minimum_speed", self.minimum_speed)
        require_ordered(
            "speed_profile.minimum_speed", self.minimum_speed,
            "speed_profile.speed_ceiling", self.speed_ceiling,
        )


@dataclass(frozen=True)
class TyreThermalConfig(ConfigNode):
    """The tyre temperature model (project rule 21).

    A tyre is heated by the work it does and cooled by the air and the track,
    and it only works properly inside a window.  Every coefficient below was
    calibrated by running the model until a stint settles where real Formula 1
    tyres settle -- surface around 95-110 degC in operation, reaching the
    window after a lap or two.
    """

    surface_heat_capacity: float = 30_000.0
    """Thermal mass of the tread, J/K, for all four tyres.

    Not the outermost skin but the tread block that actually participates on a
    timescale of seconds -- roughly four tyres' worth of rubber.  It sets how
    far the tread swings between the coolest point of a straight and the
    hottest point of a corner, which on a real car is a few tens of degrees."""

    carcass_heat_capacity: float = 60_000.0
    """Thermal mass of the carcass, J/K.  Far larger, so it lags the surface --
    which is why a tyre can be up to temperature on the outside and cold
    underneath after one lap."""

    work_coefficient: float = 0.115
    """Fraction of frictional power that ends up in the tread.

    Most of the energy at the contact patch goes into the road surface and the
    air; only a share heats the rubber.  Calibrated so a medium compound driven
    hard settles just below its own optimum: a compound is designed around the
    temperature it will see, and leaving a little headroom is what lets pushing
    harder warm a tyre *into* its window rather than straight out of it."""

    hysteresis_exponent: float = 0.5
    """How much more heat a softer compound makes, as a power of its wear rate.

    Softer rubber has more hysteresis loss, so it heats faster and runs hotter.
    Combined with a softer compound's higher optimum, that is why softs come in
    quickly and then overheat where hards never do."""

    convection_base: float = 180.0
    """Still-air cooling, W/K."""

    convection_speed: float = 12.0
    """Extra cooling per m/s of airflow, W/K."""

    track_conduction: float = 260.0
    """Conduction between tread and track surface, W/K."""

    water_conduction: float = 2_400.0
    """Extra conduction into standing water, W/K.

    Water carries heat away an order of magnitude better than air does, which
    is why a wet tyre stays in its (much lower) window and why a wet-weather
    tyre on a drying line destroys itself in a couple of laps."""

    internal_conduction: float = 900.0
    """Conduction between tread and carcass, W/K."""

    running_temperature_distance: float = 2_500.0
    """Distance, m, the tread temperature is averaged over for *planning*.

    A lap is planned before it is driven, so it has to be planned from some
    temperature, and the one at the timing line is a poor choice: it is a
    single instant of a quantity that swings tens of degrees within a lap.
    Planning from it closes a feedback loop with a one-lap delay -- a hot
    reading makes the whole next lap slow, which cools the tyre, which makes
    the lap after that fast again -- and on a circuit that works the tread hard
    the loop gain reaches one and the lap times oscillate instead of settling.

    Averaging over something like a lap is both the fix and the better model of
    what a driver actually goes out on: how the tyre has been behaving, not
    what it read at one point on the road."""

    grip_falloff: float = 0.10
    """Grip lost at one window half-width away from the optimum.

    Set from what being out of the window costs on the road rather than
    guessed: 15 K under is worth about a second and a quarter a lap, and the
    40 K of a set straight out of the blankets about eleven -- which is an out
    lap.
    The loss grows with the square of the offset, so the first few degrees
    cost almost nothing and the last few cost a great deal."""

    min_thermal_grip: float = 0.55
    """Floor on the temperature grip factor -- a stone-cold or destroyed tyre
    still has some grip."""

    def validate(self) -> None:
        require_positive("tyre_thermal.surface_heat_capacity", self.surface_heat_capacity)
        require_positive("tyre_thermal.carcass_heat_capacity", self.carcass_heat_capacity)
        require_non_negative("tyre_thermal.work_coefficient", self.work_coefficient)
        require_non_negative("tyre_thermal.hysteresis_exponent", self.hysteresis_exponent)
        require_non_negative("tyre_thermal.convection_base", self.convection_base)
        require_non_negative("tyre_thermal.convection_speed", self.convection_speed)
        require_non_negative("tyre_thermal.track_conduction", self.track_conduction)
        require_non_negative("tyre_thermal.water_conduction", self.water_conduction)
        require_positive("tyre_thermal.internal_conduction", self.internal_conduction)
        require_range("tyre_thermal.grip_falloff", self.grip_falloff, 0.0, 1.0)
        require_range("tyre_thermal.min_thermal_grip", self.min_thermal_grip, 0.1, 1.0)
        require_positive(
            "tyre_thermal.running_temperature_distance",
            self.running_temperature_distance,
        )


@dataclass(frozen=True)
class TyreWearConfig(ConfigNode):
    """Tyre wear and degradation (project rule 22).

    Not a fixed penalty per lap.  Wear accumulates from the work the tyre
    actually does -- sliding energy, scaled by load, temperature and compound --
    so a driver who looks after the tyres genuinely makes them last, and a hot
    circuit destroys them faster than a cool one.
    """

    reference_wear_energy: float = 1.10e9
    """Frictional energy, J, that wears a reference compound out completely.

    Set from stint length rather than guessed: on the reference circuit a soft
    lasts around 90 km, a medium 150 and a hard 220, which is where Formula 1
    stints sit.  It is the one number that scales all three, so the compounds'
    own wear rates decide the ratios between them and this decides the level."""

    thermal_wear_exponent: float = 2.4
    """How sharply wear accelerates above the working window.  Overheating a
    tyre is far worse than merely using it."""

    in_window_wear_gain: float = 0.5
    """Extra wear at the top of the working window, as a fraction.

    A tyre run at the hot edge of its window wears half again as fast as one at
    its optimum -- real, and not nothing.  What it must not do is wear
    *several* times as fast, which is what charging the whole excess at the
    exponent above does: the window is the range the tyre is built to work
    across, and a compound sitting comfortably inside it should not be billed
    as though it were overheating.  Getting this wrong makes the softer
    compound, which naturally runs nearer its own hot edge, look two or three
    times less durable than its wear rate says -- and by a different factor at
    every circuit."""

    management_range: float = 0.55
    """How much a driver's tyre management can change the wear rate.  A perfect
    manager wears at ``1 - management_range`` of the reference."""

    grip_loss_at_full_wear: float = 0.14
    """Grip lost when the tread is completely gone.

    Calibrated against the degradation teams quote rather than guessed: a
    medium loses about 0.10 s a lap over a stint, a hard 0.06 and a soft 0.20.
    This one number scales all three, so it is set from the medium and the
    others follow from how much harder they work and how hot they run."""

    grip_loss_exponent: float = 1.6
    """Above 1, so a tyre holds up and then falls away rather than fading
    linearly -- which is what a real degradation curve looks like."""

    thermal_damage_rate: float = 0.020
    """Permanent grip lost per lap-equivalent spent far above the window.
    Once a tyre is cooked it does not recover when it cools down."""

    max_thermal_damage: float = 0.18

    def validate(self) -> None:
        require_positive("tyre_wear.reference_wear_energy", self.reference_wear_energy)
        require_positive("tyre_wear.thermal_wear_exponent", self.thermal_wear_exponent)
        require_non_negative("tyre_wear.in_window_wear_gain", self.in_window_wear_gain)
        require_range("tyre_wear.management_range", self.management_range, 0.0, 0.95)
        require_range(
            "tyre_wear.grip_loss_at_full_wear", self.grip_loss_at_full_wear, 0.0, 0.9
        )
        require_positive("tyre_wear.grip_loss_exponent", self.grip_loss_exponent)
        require_non_negative("tyre_wear.thermal_damage_rate", self.thermal_damage_rate)
        require_range("tyre_wear.max_thermal_damage", self.max_thermal_damage, 0.0, 0.9)


@dataclass(frozen=True)
class WakeConfig(ConfigNode):
    """The air behind another car (rule 29).

    The downforce side is set from what following *costs on the road*, because
    that is the thing anyone can check.  Losing one per cent of downforce is
    worth 0.09-0.13 s a lap here depending on the circuit, and in a modern race
    a car half a second behind loses something like half a second a lap while a
    car a second behind loses two or three tenths.  Any bigger and a DRS train
    could not form at all -- cars would drop out of the tow as fast as they
    reached it -- and DRS trains are the defining feature of the era.

    That lands between the two figures the FIA published for the ground-effect
    regulations (a 2022 car losing 18% of its downforce at ten metres and 4% at
    twenty), which is where a 2024 car belongs: the teams recovered much of the
    wake performance the rules took away, but not all of it.

    The tow is set from the other observable: a car sitting right behind another
    gains 10-15 km/h on a long straight, and a qualifying tow at a power circuit
    is worth three or four tenths.
    """

    peak_downforce_loss: float = 0.13
    """Downforce lost when running right behind another car."""

    downforce_scale: float = 0.70
    """Time constant, s, of the dirty-air decay."""

    peak_drag_saving: float = 0.14
    """Drag saved sitting right behind another car."""

    drag_scale: float = 0.60
    """Time constant, s, of the tow's decay.  Shorter than the downforce one:
    the hole in the air closes up faster than the turbulence settles down."""

    tow_needs_a_straight: bool = True
    """Whether the tow only counts where the cars are lined up.

    Two cars are nose to tail down a straight and side by side through a
    corner, so the hole in the air is only useful in one of those places.  The
    dirty air is not so fussy -- turbulence fills the corner too."""

    range: float = 3.0
    """Gap, s, beyond which a car is in clean air."""

    minimum_downforce: float = 0.60
    """Floor on the downforce multiplier, so a car glued to a gearbox is
    struggling rather than undriveable.  The default peak never reaches it;
    it is a guard on a hand-edited config, not part of the calibration."""

    def validate(self) -> None:
        require_range("wake.peak_downforce_loss", self.peak_downforce_loss, 0.0, 1.0)
        require_positive("wake.downforce_scale", self.downforce_scale)
        require_range("wake.peak_drag_saving", self.peak_drag_saving, 0.0, 1.0)
        require_positive("wake.drag_scale", self.drag_scale)
        require_positive("wake.range", self.range)
        require_range("wake.minimum_downforce", self.minimum_downforce, 0.1, 1.0)


@dataclass(frozen=True)
class OvertakingConfig(ConfigNode):
    """When a following car gets past (rule 29)."""

    minimum_gap: float = 0.35
    """Closest, in seconds, a car will run behind another without passing.

    Not a collision radius: it is how close a driver can follow through a
    corner before the dirty air takes away the grip they would need to stay
    there.  A car that catches this gap and cannot pass sits in it."""

    car_length: float = 5.6
    """Metres of overlap needed to be alongside rather than behind."""

    defence_margin: float = 12.0
    """How much quicker an attacker has to be, in m/s, per unit of racecraft
    the defender has on them.

    A defender takes the line the attacker wants, so being marginally faster is
    not enough: the attacker has to arrive with a speed advantage that cannot be
    covered.  Two equally matched drivers meet at zero, and a car quicker than
    the one defending it needs less."""

    drs_detection_gap: float = 1.0
    """Gap, s, at the detection point that entitles a car to open DRS."""

    drs_detection_offset: float = 150.0
    """How far before a DRS zone the gap is measured, m.  Being within a
    second at the detection point and not at the zone is a real thing that
    happens, and it needs the two to be different places."""

    interaction_steps: int = 40
    """How many times a lap the field is re-synchronised while racing.

    Cars have to move forward together for "who is in front" to mean anything:
    a car overtaken a third of the way round has to know about it before it
    reaches the line.  Forty steps is about one and a half seconds of racing
    between resynchronisations, which is finer than the wake model can tell
    apart and far finer than a position change."""

    off_line_penalty: float = 1.0
    """How much of the off-line surface an overtaking car has to use, 0 to 1.

    Passing means leaving the racing line, where the marbles are.  That is what
    makes a move cost something even when it works."""

    passing_speed: float = 25.0
    """Slowest, m/s, at which a move can be completed.

    Getting alongside means carrying more speed than the car in front into a
    place with room for two, and a hairpin taken at walking pace has neither."""

    passing_radius: float = 400.0
    """Straightest corner, m, that still counts as somewhere to pass.

    Above this the road is effectively straight: the end of a straight and the
    braking zone at the end of it, which is where a car carrying more speed
    ends up alongside."""

    commitment_gap: float = 4.0
    """How close, in car lengths, an attacker has to be before it is committed.

    Inside this the driver is out of the tow and into the move, which means off
    the racing line -- so it is also where the marbles start costing them."""

    def validate(self) -> None:
        require_positive("overtaking.minimum_gap", self.minimum_gap)
        if self.interaction_steps < 1:
            raise ConfigError("overtaking.interaction_steps must be at least 1")
        require_positive("overtaking.car_length", self.car_length)
        require_non_negative("overtaking.defence_margin", self.defence_margin)
        require_non_negative("overtaking.passing_speed", self.passing_speed)
        require_positive("overtaking.passing_radius", self.passing_radius)
        require_positive("overtaking.commitment_gap", self.commitment_gap)
        require_positive("overtaking.drs_detection_gap", self.drs_detection_gap)
        require_non_negative(
            "overtaking.drs_detection_offset", self.drs_detection_offset
        )
        require_range(
            "overtaking.off_line_penalty", self.off_line_penalty, 0.0, 1.0
        )


@dataclass(frozen=True)
class WetConfig(ConfigNode):
    """How standing water and tread pattern decide grip (rule 30).

    The surface penalty for a wet road lives in ``track_conditions``; this is
    only the part that depends on which tyre is fitted.
    """

    reference_clearance_speed: float = 40.0
    """Speed, m/s, at which a compound clears its rated water depth."""

    clearance_exponent: float = 1.0
    """How fast clearance falls with speed.  One means the tread evacuates a
    fixed volume per unit time, so the depth it can cope with is inversely
    proportional to how quickly the road goes past."""

    aquaplaning_depth: float = 0.0005
    """Unevacuated depth, m, that halves grip.  Half a millimetre of water
    under the contact patch is already most of the way to floating."""

    residual_film_fraction: float = 0.06
    """Film a tread leaves behind at exactly its rated depth, as a fraction of
    what it can clear.

    Evacuation is a rate, not a switch.  Without this a tyre is perfect right
    up to its limit and then falls off a cliff, so an intermediate in 0.2 mm of
    water and one in 2 mm lap identically -- which is not what a wet race looks
    like from the pit wall."""

    residual_film_exponent: float = 3.0
    """How the residual film grows as the demand approaches the tread's
    capacity.  Above one, so light rain costs almost nothing and the loss
    arrives as the tread runs out of room."""

    min_wet_grip: float = 0.12
    """Floor, so a car that aquaplanes is out of control rather than out of
    physics."""

    def validate(self) -> None:
        require_positive(
            "wet.reference_clearance_speed", self.reference_clearance_speed
        )
        require_positive("wet.clearance_exponent", self.clearance_exponent)
        require_positive("wet.aquaplaning_depth", self.aquaplaning_depth)
        require_range(
            "wet.residual_film_fraction", self.residual_film_fraction, 0.0, 1.0
        )
        require_positive("wet.residual_film_exponent", self.residual_film_exponent)
        require_range("wet.min_wet_grip", self.min_wet_grip, 0.0, 1.0)


@dataclass(frozen=True)
class FuelConfig(ConfigNode):
    """Fuel consumption (project rule 23)."""

    lower_heating_value: float = 43.0e6
    """Energy in a kilogram of fuel, J/kg."""

    thermal_efficiency: float = 0.50
    """Crank work out per unit of fuel energy in.  A current Formula 1 power
    unit is the most efficient racing engine ever built, at about 50%."""

    idle_flow: float = 0.008
    """Fuel burned per second regardless of load, kg/s."""

    def validate(self) -> None:
        require_positive("fuel.lower_heating_value", self.lower_heating_value)
        require_range("fuel.thermal_efficiency", self.thermal_efficiency, 0.1, 0.7)
        require_non_negative("fuel.idle_flow", self.idle_flow)


@dataclass(frozen=True)
class ErsConfig(ConfigNode):
    """Energy recovery (project rule 24).

    ERS is never a lap-time bonus.  It is an energy store with a capacity, a
    deployment limit and a harvest rate, and it runs out -- which is exactly
    what makes deploying it a decision rather than a gift.
    """

    deployment_efficiency: float = 0.96
    """Electrical energy out of the store to mechanical work at the wheels."""

    harvest_efficiency: float = 0.90
    """Braking work recovered into the store."""

    thermal_recovery_fraction: float = 0.10
    """Share of engine power the turbine can turn back into stored energy."""

    minimum_deploy_speed: float = 15.0
    """Below this speed, m/s, deployment only spins the wheels."""

    def validate(self) -> None:
        require_range(
            "ers.deployment_efficiency", self.deployment_efficiency, 0.5, 1.0
        )
        require_range("ers.harvest_efficiency", self.harvest_efficiency, 0.3, 1.0)
        require_range(
            "ers.thermal_recovery_fraction", self.thermal_recovery_fraction, 0.0, 1.0
        )
        require_non_negative("ers.minimum_deploy_speed", self.minimum_deploy_speed)


@dataclass(frozen=True)
class DriverConfig(ConfigNode):
    """How driver ability turns into lap time.

    Every number here was calibrated by measurement, not chosen.  On the
    reference circuit, using 94% of the available grip costs 0.86% of lap time;
    99% costs 0.17%.  Formula 1's best-to-worst one-lap spread in equal
    machinery is around 1%, so the whole driver field has to live inside a very
    narrow band of commitment -- which is itself the interesting result.
    """

    max_commitment_deficit: float = 0.30
    """Grip a driver with an attribute of 0 leaves unused.

    ``utilisation = 1 - (1 - attribute) * max_commitment_deficit``.  Calibrated
    against the measured cost of commitment: with Formula 1 drivers spanning
    attributes of about 0.80 to 0.98, this gives a one-lap spread near 0.6 s on
    a 68 s lap and teammate gaps of 0.1-0.3 s, which is what the real thing
    looks like."""

    consistency_sigma: float = 0.12
    """Commitment scatter of a completely inconsistent driver, scaled by
    ``(1 - consistency)``.

    Drawn one-sided -- a driver can fall short of the limit but never exceed
    it -- so inconsistency costs average pace as well as adding scatter, which
    is the real effect.  Calibrated to give a mid-field driver a lap-to-lap
    standard deviation near 0.1-0.2 s and a metronome under 0.02 s."""

    corner_sigma_fraction: float = 0.55
    """Share of the variation that lands per corner rather than per lap.
    A driver is not uniformly good or bad on a lap -- some corners go better
    than others, and that is what makes a lap time distribution rather than a
    single offset."""

    mistake_rate: float = 0.30
    """Chance per corner, per lap, that a driver with zero risk management and
    zero consistency makes a mistake.

    Scaled by the *product* of both shortfalls, so a driver has to be weak on
    each to be genuinely error-prone.  Calibrated so a rookie makes a visible
    error every few laps and the grid's benchmark roughly once in a hundred."""

    mistake_severity: float = 0.22
    """Fraction of apex speed lost in a full mistake.  Real lock-ups and runs
    wide cost a few tenths, which this produces through the driving rather
    than by adding time to the result."""

    min_commitment: float = 0.5
    """Floor on commitment, so no combination of noise can stop the car."""

    reaction_floor: float = 0.18
    """Fastest a human reacts to the start lights, s.  Below this is a jump
    start, not a good one."""

    reaction_range: float = 0.35
    """Extra reaction time, s, a driver with no racecraft at all takes."""

    reaction_sigma: float = 0.06
    """Scatter, s, on a reaction before the driver's consistency narrows it."""

    def validate(self) -> None:
        require_positive("driver.reaction_floor", self.reaction_floor)
        require_non_negative("driver.reaction_range", self.reaction_range)
        require_non_negative("driver.reaction_sigma", self.reaction_sigma)
        require_range(
            "driver.max_commitment_deficit", self.max_commitment_deficit, 0.0, 0.5
        )
        require_non_negative("driver.consistency_sigma", self.consistency_sigma)
        require_range(
            "driver.corner_sigma_fraction", self.corner_sigma_fraction, 0.0, 1.0
        )
        require_range("driver.mistake_rate", self.mistake_rate, 0.0, 1.0)
        require_range("driver.mistake_severity", self.mistake_severity, 0.0, 1.0)
        require_range("driver.min_commitment", self.min_commitment, 0.1, 1.0)


@dataclass(frozen=True)
class SuspensionConfig(ConfigNode):
    """How the car carries load across itself.

    The lateral counterpart of the longitudinal transfer the powertrain section
    owns, and it matters for the same reason: friction coefficient falls with
    load, so **splitting** a given load unevenly across four tyres buys less
    grip than sharing it evenly.  Cornering therefore costs the car grip simply
    by loading the outside of it, and the cost grows with lateral acceleration.

    That is what makes a wide car with a low centre of gravity corner better
    than a narrow tall one carrying the same downforce, and it is why roll
    stiffness is a setup decision rather than a comfort one.
    """

    lateral_load_transfer: bool = True
    """Whether cornering moves load onto the outside tyres.

    On, because leaving it out overstates cornering grip by a couple of percent
    at 4 g and rather more beyond that, and because with it out the car's track
    width and centre-of-gravity height do nothing at all."""

    roll_stiffness_front: float = 0.55
    """Share of the lateral transfer taken by the front axle.

    Above the static weight distribution, which is what gives a car mild
    understeer at the limit -- the safe balance every road-legal and most
    racing setups are built around.  It is what an anti-roll bar change
    actually alters, and it is charged for: the grip penalty is concave, so an
    axle taking more than its share of the transfer loses more than the other
    end gains back, and *any* distribution away from the load split costs the
    car total grip.

    Which is the useful result, because it says a bar is not free lap time.
    Swinging it from a matched 0.45 to a stiff-front 0.70 costs 0.16 s a lap
    here, and the reason a team does it anyway is the balance it buys -- the
    part that needs the slip-angle model Phase 12 does not have yet."""

    def validate(self) -> None:
        require_range(
            "suspension.roll_stiffness_front", self.roll_stiffness_front, 0.2, 0.8
        )


@dataclass(frozen=True)
class ReliabilityConfig(ConfigNode):
    """What breaks, and how often (project rule 35).

    Failures are a **hazard per unit distance**, never a per-lap coin flip.
    That distinction is the whole model: a rate per kilometre gives the same
    expected number of failures whether it is evaluated once a lap or once a
    metre, and it makes a long circuit genuinely harder on a car than a short
    one without anything saying so.

    The rates below are per 1000 km and sum to about 0.22, which over a 305 km
    race is a 6.5% chance of a mechanical retirement per car -- roughly half of
    Formula 1's total retirement rate, the other half being contact.  The
    split between systems follows where modern failures actually happen: the
    power unit is the biggest single contributor by a distance.
    """

    power_unit_rate: float = 0.092
    """Power unit failures per 1000 km."""

    gearbox_rate: float = 0.040
    hydraulics_rate: float = 0.033
    cooling_rate: float = 0.024
    brake_rate: float = 0.020
    suspension_rate: float = 0.013

    stress_exponent: float = 2.0
    """How sharply a hazard rises with how hard the system is being worked.

    Above one, so a power unit run at its limit is far more likely to let go
    than one being managed -- which is what makes turning the engine down a
    real decision rather than a slower one."""

    max_stress_factor: float = 4.0
    """Ceiling on the stress multiplier, so a pathological input cannot make a
    failure certain."""

    reference_ambient: float = 25.0
    """Air temperature, degC, the cooling hazard is quoted at."""

    cooling_sensitivity: float = 0.06
    """Extra cooling hazard per degree above the reference.  Hot races break
    more cars, and the effect is large: 15 degrees nearly doubles it."""

    stops_on_circuit_share: float = 0.50
    """Share of failures that leave the car where it has to be recovered.

    A driver warned that something is going is usually able to get the car to a
    safe place; sometimes there is no warning, or nowhere to go.  Which of
    those happened is what decides whether a failure is a footnote or the thing
    that reshuffles the race, so it is drawn rather than assumed."""

    reference_fuel_per_km: float = 0.33
    """Fuel a reference lap burns per kilometre, kg.  What the power unit's
    stress is measured against, so a car turned down genuinely lasts longer."""

    reference_harvest_per_km: float = 550_000.0
    """Energy a reference lap recovers per kilometre, J.  Recovery happens
    under braking, so it is the honest proxy for how hard the brakes are being
    worked -- and it makes a heavy-braking circuit harder on them."""

    def validate(self) -> None:
        for name in (
            "power_unit_rate", "gearbox_rate", "hydraulics_rate",
            "cooling_rate", "brake_rate", "suspension_rate",
        ):
            require_non_negative(f"reliability.{name}", getattr(self, name))
        require_positive("reliability.stress_exponent", self.stress_exponent)
        require_range("reliability.max_stress_factor", self.max_stress_factor, 1.0, 20.0)
        require_non_negative(
            "reliability.cooling_sensitivity", self.cooling_sensitivity
        )
        require_range(
            "reliability.stops_on_circuit_share", self.stops_on_circuit_share, 0.0, 1.0
        )
        require_positive(
            "reliability.reference_fuel_per_km", self.reference_fuel_per_km
        )
        require_positive(
            "reliability.reference_harvest_per_km", self.reference_harvest_per_km
        )


@dataclass(frozen=True)
class IncidentConfig(ConfigNode):
    """Contact, spins and what they cost.

    Calibrated against Formula 1's retirement split: about 4% of car-races end
    in contact and rather more end in damage that costs time without ending the
    race.  Contact is a hazard *per lap spent fighting somebody*, not per lap,
    because a car in clean air does not hit anybody.
    """

    combat_contact_rate: float = 0.0115
    """Chance of contact per lap spent within fighting distance of another car.

    Set from the outcome rather than guessed: a car spends about eleven laps of
    a race fighting somebody, two thirds of contact ends a race, and Formula 1
    loses about 6% of its starters to contact.  That fixes this number."""

    combat_gap: float = 1.2
    """Time gap, s, inside which two cars count as fighting."""

    first_lap_multiplier: float = 6.0
    """How much more likely contact is on the opening lap.

    Twenty cars arriving at the first corner together is where a
    disproportionate share of a season's contact happens, and no amount of
    per-lap averaging reproduces that."""

    racecraft_range: float = 0.7
    """How much a driver's racecraft and risk management can change the odds.
    A perfect pair is ``1 - racecraft_range`` as likely to make contact."""

    spin_rate: float = 0.35
    """Chance that a driver mistake bad enough to cost real time becomes a spin
    or an excursion rather than just a scruffy corner."""

    retirement_share: float = 0.30
    """Share of contacts that end a car's race outright."""

    blocking_share: float = 0.35
    """Share of contacts that leave a car or debris where it has to be
    recovered -- which is what brings out a flag."""

    debris_share: float = 0.60
    """Share of contact a car drives away from that still leaves debris.

    A front wing shed at speed has to be picked up whether or not its owner
    retired, and that is the most common reason a modern race is neutralised."""

    damage_drag_penalty: float = 0.18
    """Drag area added by a damaged front wing, as a fraction."""

    damage_downforce_loss: float = 0.22
    """Downforce lost with a damaged front wing, as a fraction."""

    def validate(self) -> None:
        require_non_negative("incidents.combat_contact_rate", self.combat_contact_rate)
        require_positive("incidents.combat_gap", self.combat_gap)
        require_range("incidents.first_lap_multiplier", self.first_lap_multiplier, 1.0, 40.0)
        require_range("incidents.racecraft_range", self.racecraft_range, 0.0, 0.95)
        require_range("incidents.spin_rate", self.spin_rate, 0.0, 1.0)
        require_range("incidents.retirement_share", self.retirement_share, 0.0, 1.0)
        require_range("incidents.blocking_share", self.blocking_share, 0.0, 1.0)
        require_range("incidents.debris_share", self.debris_share, 0.0, 1.0)
        require_non_negative(
            "incidents.damage_drag_penalty", self.damage_drag_penalty
        )
        require_range(
            "incidents.damage_downforce_loss", self.damage_downforce_loss, 0.0, 1.0
        )


@dataclass(frozen=True)
class RaceControlConfig(ConfigNode):
    """When the race is neutralised, and what that does to it.

    Nothing here decides *whether* something happens -- incidents do that.
    This is only what race control does about one, and the shares below are
    what it does in practice: most stopped cars are recovered under a local
    yellow, a good many need a virtual safety car, fewer need the real one, and
    a handful of races a season are stopped altogether.
    """

    vsc_share: float = 0.35
    """Share of recoverable incidents that bring out a virtual safety car."""

    safety_car_share: float = 0.29
    """Share that bring out the safety car itself."""

    red_flag_share: float = 0.09
    """Share that stop the race.

    The three shares are set from how often a season sees each: with about one
    and a half cars a race stopping somewhere they have to be recovered from,
    these give a safety car in a little over 40% of races, a virtual one in
    half, and a red flag in one in seven -- which is what the calendar does.
    What is left over is recovered under a local yellow, which is the most
    common answer of all."""

    vsc_laps: tuple[int, int] = (1, 3)
    """Shortest and longest a virtual safety car lasts, laps."""

    safety_car_laps: tuple[int, int] = (3, 6)

    safety_car_pace: float = 1.55
    """Lap time behind the safety car, as a multiple of a green lap.

    A safety car lap is not a slow racing lap; it is a different activity.
    1.55 is where a modern Formula 1 safety car lap sits."""

    vsc_pace: float = 1.38
    """Lap time under a virtual safety car, as a multiple of a green lap.
    Race control sets a delta the drivers must stay above; this is it."""

    safety_car_pit_saving: float = 0.55
    """Share of a green-flag stop's cost that disappears under the safety car.

    The reason a safety car reshuffles a race: the road the pit lane replaces
    is being covered slowly, so replacing it costs much less."""

    vsc_pit_saving: float = 0.40

    tyre_work_share: float = 0.45
    """Share of a racing lap's tyre work a car behind the safety car still does.

    Not zero, and that matters: a driver behind the safety car weaves and
    brakes precisely to keep temperature in the tyres, because a restart on
    cold ones is where races are lost.  Coasting the whole neutralisation
    instead leaves the field so cold that the first green lap is thirty seconds
    off the pace, which is not what a restart looks like."""

    bunching_gap: float = 1.1
    """Gap, s, the field is compressed to behind the safety car."""

    restart_gap: float = 0.6
    """Extra gap, s, per position at the restart, before racing resumes."""

    minimum_green_laps: int = 2
    """Laps of green running before another neutralisation can start, so one
    incident does not produce a cascade of overlapping flags."""

    red_flag_restart_laps: int = 1
    """Laps run behind the safety car after a red-flag restart."""

    def validate(self) -> None:
        total = self.vsc_share + self.safety_car_share + self.red_flag_share
        if total > 1.0:
            raise ConfigError(
                f"race_control shares sum to {total:.2f}; they are shares of one "
                f"incident and cannot exceed 1.0"
            )
        for name in ("vsc_share", "safety_car_share", "red_flag_share"):
            require_range(f"race_control.{name}", getattr(self, name), 0.0, 1.0)
        for name in ("vsc_laps", "safety_car_laps"):
            low, high = getattr(self, name)
            if low < 1 or high < low:
                raise ConfigError(f"race_control.{name} must be an increasing pair of positive laps")
        require_range("race_control.safety_car_pace", self.safety_car_pace, 1.0, 3.0)
        require_range("race_control.vsc_pace", self.vsc_pace, 1.0, 3.0)
        require_range(
            "race_control.safety_car_pit_saving", self.safety_car_pit_saving, 0.0, 1.0
        )
        require_range("race_control.vsc_pit_saving", self.vsc_pit_saving, 0.0, 1.0)
        require_range("race_control.tyre_work_share", self.tyre_work_share, 0.0, 1.0)
        require_positive("race_control.bunching_gap", self.bunching_gap)
        require_non_negative("race_control.restart_gap", self.restart_gap)
        if self.minimum_green_laps < 0:
            raise ConfigError("race_control.minimum_green_laps must not be negative")
        if self.red_flag_restart_laps < 0:
            raise ConfigError("race_control.red_flag_restart_laps must not be negative")


@dataclass(frozen=True)
class PhysicsValidationConfig(ConfigNode):
    """Bounds for the automatic physics sanity checks (project rule 39).

    These are plausibility envelopes for a modern Formula 1 car, not targets.
    A model that leaves them has gone wrong in a way that is cheaper to catch
    here than three phases later.
    """

    min_top_speed: float = 75.0
    max_top_speed: float = 110.0
    """Top speed envelope, m/s (270-396 km/h)."""

    min_peak_lateral_g: float = 3.5
    max_peak_lateral_g: float = 7.0
    """Peak sustained lateral acceleration envelope, g."""

    min_peak_braking_g: float = 3.5
    max_peak_braking_g: float = 7.0

    min_standing_acceleration_g: float = 0.7
    max_standing_acceleration_g: float = 1.8
    """Longitudinal acceleration from rest, g -- traction limited."""

    max_low_speed_lateral_g: float = 3.0
    """A car with no downforce yet must not be pulling high-speed numbers."""

    def validate(self) -> None:
        require_ordered(
            "physics_validation.min_top_speed", self.min_top_speed,
            "physics_validation.max_top_speed", self.max_top_speed,
        )
        require_ordered(
            "physics_validation.min_peak_lateral_g", self.min_peak_lateral_g,
            "physics_validation.max_peak_lateral_g", self.max_peak_lateral_g,
        )
        require_ordered(
            "physics_validation.min_peak_braking_g", self.min_peak_braking_g,
            "physics_validation.max_peak_braking_g", self.max_peak_braking_g,
        )
        require_ordered(
            "physics_validation.min_standing_acceleration_g",
            self.min_standing_acceleration_g,
            "physics_validation.max_standing_acceleration_g",
            self.max_standing_acceleration_g,
        )


@dataclass(frozen=True)
class RandomnessConfig(ConfigNode):
    """Seeding for the central RNG (project rule 36)."""

    seed: int = 20260812

    def validate(self) -> None:
        if self.seed < 0:
            raise ConfigError(f"randomness.seed must be non-negative, got {self.seed}")


@dataclass(frozen=True)
class SimulationConfig(ConfigNode):
    """Root of the configuration tree.

    Later phases extend this by adding sections -- ``aero``, ``tyres``,
    ``power_unit``, ``race`` -- each with a default, so existing config files
    keep loading unchanged.
    """

    version: str = "0.1.0"
    randomness: RandomnessConfig = field(default_factory=RandomnessConfig)
    physics: PhysicsConfig = field(default_factory=PhysicsConfig)
    track_build: TrackBuildConfig = field(default_factory=TrackBuildConfig)
    track_validation: TrackValidationConfig = field(default_factory=TrackValidationConfig)
    track_conditions: TrackConditionsConfig = field(default_factory=TrackConditionsConfig)
    environment: EnvironmentConfig = field(default_factory=EnvironmentConfig)
    weather: WeatherConfig = field(default_factory=WeatherConfig)
    track_evolution: TrackEvolutionConfig = field(
        default_factory=TrackEvolutionConfig
    )
    aero: AeroConfig = field(default_factory=AeroConfig)
    tyres: TyreConfig = field(default_factory=TyreConfig)
    powertrain: PowertrainConfig = field(default_factory=PowertrainConfig)
    speed_profile: SpeedProfileConfig = field(default_factory=SpeedProfileConfig)
    driver: DriverConfig = field(default_factory=DriverConfig)
    tyre_thermal: TyreThermalConfig = field(default_factory=TyreThermalConfig)
    tyre_wear: TyreWearConfig = field(default_factory=TyreWearConfig)
    wet: WetConfig = field(default_factory=WetConfig)
    wake: WakeConfig = field(default_factory=WakeConfig)
    overtaking: OvertakingConfig = field(default_factory=OvertakingConfig)
    fuel: FuelConfig = field(default_factory=FuelConfig)
    ers: ErsConfig = field(default_factory=ErsConfig)
    suspension: SuspensionConfig = field(default_factory=SuspensionConfig)
    reliability: ReliabilityConfig = field(default_factory=ReliabilityConfig)
    incidents: IncidentConfig = field(default_factory=IncidentConfig)
    race_control: RaceControlConfig = field(default_factory=RaceControlConfig)
    physics_validation: PhysicsValidationConfig = field(
        default_factory=PhysicsValidationConfig
    )


# ---------------------------------------------------------------------------
# Loading and saving
# ---------------------------------------------------------------------------


def default_config() -> SimulationConfig:
    """Return a fresh default configuration."""
    return SimulationConfig()


def load_config(path: str | Path) -> SimulationConfig:
    """Load a configuration from a JSON file."""
    file_path = Path(path)
    try:
        raw = json.loads(file_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"config file not found: {file_path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"config file {file_path} is not valid JSON: {exc}") from exc
    return SimulationConfig.from_dict(raw)


def save_config(config: SimulationConfig, path: str | Path) -> None:
    """Write a configuration to a JSON file."""
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(config.to_json() + "\n", encoding="utf-8")


def config_from_overrides(overrides: Mapping[str, Any] | None = None) -> SimulationConfig:
    """Return the default config with ``overrides`` deep-merged in."""
    base = SimulationConfig()
    if not overrides:
        return base
    return base.merged(overrides)
