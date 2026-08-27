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

    wet_grip_sensitivity: float = 0.55
    """Strength of the wet-grip reduction at the reference water depth."""

    reference_water_depth: float = 0.002
    """Water depth, m, at which ``wet_grip_sensitivity`` applies (2 mm)."""

    min_grip_multiplier: float = 0.25
    """Floor on the combined multiplier, so grip can never reach zero."""

    def validate(self) -> None:
        require_non_negative(
            "track_conditions.rubber_grip_gain", self.rubber_grip_gain
        )
        require_range(
            "track_conditions.marble_grip_penalty", self.marble_grip_penalty, 0.0, 1.0
        )
        require_non_negative(
            "track_conditions.wet_grip_sensitivity", self.wet_grip_sensitivity
        )
        require_positive(
            "track_conditions.reference_water_depth", self.reference_water_depth
        )
        require_range(
            "track_conditions.min_grip_multiplier", self.min_grip_multiplier, 0.0, 1.0
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
