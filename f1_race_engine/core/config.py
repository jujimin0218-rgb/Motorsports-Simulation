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

    drivetrain_efficiency: float = 0.95
    """Fraction of crank power that reaches the road."""

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
    acceleration depends on grip).  This many fixed-point passes settle it."""

    def validate(self) -> None:
        require_range(
            "powertrain.drivetrain_efficiency", self.drivetrain_efficiency, 0.5, 1.0
        )
        require_positive("powertrain.min_tractive_speed", self.min_tractive_speed)
        if self.traction_solver_iterations < 1:
            raise ConfigError(
                "powertrain.traction_solver_iterations must be at least 1"
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

    internal_conduction: float = 900.0
    """Conduction between tread and carcass, W/K."""

    grip_falloff: float = 0.16
    """Grip lost at one window half-width away from the optimum."""

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
        require_positive("tyre_thermal.internal_conduction", self.internal_conduction)
        require_range("tyre_thermal.grip_falloff", self.grip_falloff, 0.0, 1.0)
        require_range("tyre_thermal.min_thermal_grip", self.min_thermal_grip, 0.1, 1.0)


@dataclass(frozen=True)
class TyreWearConfig(ConfigNode):
    """Tyre wear and degradation (project rule 22).

    Not a fixed penalty per lap.  Wear accumulates from the work the tyre
    actually does -- sliding energy, scaled by load, temperature and compound --
    so a driver who looks after the tyres genuinely makes them last, and a hot
    circuit destroys them faster than a cool one.
    """

    reference_wear_energy: float = 1.35e9
    """Frictional energy, J, that wears a reference compound out completely."""

    thermal_wear_exponent: float = 2.4
    """How sharply wear accelerates above the working window.  Overheating a
    tyre is far worse than merely using it."""

    management_range: float = 0.55
    """How much a driver's tyre management can change the wear rate.  A perfect
    manager wears at ``1 - management_range`` of the reference."""

    grip_loss_at_full_wear: float = 0.22
    """Grip lost when the tread is completely gone."""

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
        require_range("tyre_wear.management_range", self.management_range, 0.0, 0.95)
        require_range(
            "tyre_wear.grip_loss_at_full_wear", self.grip_loss_at_full_wear, 0.0, 0.9
        )
        require_positive("tyre_wear.grip_loss_exponent", self.grip_loss_exponent)
        require_non_negative("tyre_wear.thermal_damage_rate", self.thermal_damage_rate)
        require_range("tyre_wear.max_thermal_damage", self.max_thermal_damage, 0.0, 0.9)


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

    def validate(self) -> None:
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
    aero: AeroConfig = field(default_factory=AeroConfig)
    tyres: TyreConfig = field(default_factory=TyreConfig)
    powertrain: PowertrainConfig = field(default_factory=PowertrainConfig)
    speed_profile: SpeedProfileConfig = field(default_factory=SpeedProfileConfig)
    driver: DriverConfig = field(default_factory=DriverConfig)
    tyre_thermal: TyreThermalConfig = field(default_factory=TyreThermalConfig)
    tyre_wear: TyreWearConfig = field(default_factory=TyreWearConfig)
    fuel: FuelConfig = field(default_factory=FuelConfig)
    ers: ErsConfig = field(default_factory=ErsConfig)
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
