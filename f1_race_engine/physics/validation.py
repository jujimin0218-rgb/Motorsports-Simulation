"""Automatic physics sanity checks (project rules 39 and 40).

    "물리적으로 명백히 이상한 결과가 나오면 다음 단계로 넘어가지 않는다."

Two kinds of check, and both matter.

**Directional checks** assert the relationships the physics must obey, without
caring about exact values: more speed must mean more downforce, more mass must
mean less acceleration, more grip must mean more cornering, a tighter radius
must mean a lower corner speed.  These are rule 39's list and rule 40's Tests
C, D and E, and they are what catches a sign error or a term dropped from a
force balance.

**Envelope checks** assert that the numbers land where a real Formula 1 car
lands.  A model can be perfectly self-consistent and still produce a car that
corners at 12 g; only comparison against reality catches that.

Both run against any vehicle, so a new car specification is checked the moment
it is loaded rather than after it has quietly distorted a season of results.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import ClassVar

from ..core.config import PhysicsValidationConfig, SimulationConfig
from ..core.errors import PhysicsValidationError
from ..core.units import kph_to_ms, ms_to_kph
from ..core.validation import Severity, ValidationIssue
from ..core.validation import ValidationReport as BaseValidationReport
from ..environment.conditions import AmbientConditions
from ..tyres.compound import TyreCompound
from ..tyres.state import TyreState
from ..vehicle.model import Vehicle
from .benchmark import benchmark_vehicle
from .lateral import corner_speed_limit, max_lateral_acceleration
from .longitudinal import max_acceleration, max_deceleration

__all__ = [
    "PHYSICS_CHECKS",
    "PhysicsReport",
    "validate_vehicle",
]

from dataclasses import dataclass


@dataclass(frozen=True)
class PhysicsReport(BaseValidationReport):
    """Validation findings for one vehicle."""

    kind: ClassVar[str] = "Physics validation"
    error_type: ClassVar[type[Exception]] = PhysicsValidationError


Check = Callable[
    [Vehicle, AmbientConditions, PhysicsValidationConfig], list[ValidationIssue]
]

_TEST_SPEEDS = (20.0, 40.0, 60.0, 80.0)


def _issue(check: str, severity: Severity, message: str) -> ValidationIssue:
    return ValidationIssue(check=check, severity=severity, message=message)


# ---------------------------------------------------------------------------
# Directional checks -- project rule 39
# ---------------------------------------------------------------------------


def check_downforce_rises_with_speed(
    vehicle: Vehicle, ambient: AmbientConditions, cfg: PhysicsValidationConfig
) -> list[ValidationIssue]:
    """Aero: speed up, downforce up -- and as the square of speed."""
    issues: list[ValidationIssue] = []
    rho = ambient.air_density
    values = [
        vehicle.aero.downforce(speed, rho, vehicle.wing_level) for speed in _TEST_SPEEDS
    ]
    for (v0, f0), (v1, f1) in zip(zip(_TEST_SPEEDS, values), zip(_TEST_SPEEDS[1:], values[1:])):
        if f1 <= f0:
            issues.append(
                _issue(
                    "aero_downforce",
                    Severity.ERROR,
                    f"downforce did not increase from {v0:.0f} to {v1:.0f} m/s "
                    f"({f0:.0f} -> {f1:.0f} N)",
                )
            )
    ratio = values[1] / values[0] if values[0] > 0 else 0.0
    expected = (_TEST_SPEEDS[1] / _TEST_SPEEDS[0]) ** 2
    if abs(ratio - expected) > 1e-6:
        issues.append(
            _issue(
                "aero_downforce",
                Severity.ERROR,
                f"downforce does not scale with v^2: doubling speed changed it by "
                f"{ratio:.4f}x, expected {expected:.4f}x",
            )
        )
    issues.append(
        _issue(
            "aero_downforce",
            Severity.INFO,
            f"downforce at 300 km/h: {vehicle.aero.downforce(kph_to_ms(300), rho, vehicle.wing_level):.0f} N "
            f"({vehicle.aero.downforce(kph_to_ms(300), rho, vehicle.wing_level) / 9.80665:.0f} kg)",
        )
    )
    return issues


def check_drag_rises_with_speed(
    vehicle: Vehicle, ambient: AmbientConditions, cfg: PhysicsValidationConfig
) -> list[ValidationIssue]:
    """Aero: speed up, drag up."""
    issues: list[ValidationIssue] = []
    rho = ambient.air_density
    values = [vehicle.aero.drag(speed, rho, vehicle.wing_level) for speed in _TEST_SPEEDS]
    for (v0, f0), (v1, f1) in zip(zip(_TEST_SPEEDS, values), zip(_TEST_SPEEDS[1:], values[1:])):
        if f1 <= f0:
            issues.append(
                _issue(
                    "aero_drag",
                    Severity.ERROR,
                    f"drag did not increase from {v0:.0f} to {v1:.0f} m/s "
                    f"({f0:.0f} -> {f1:.0f} N)",
                )
            )
    return issues


def check_wing_trade_off(
    vehicle: Vehicle, ambient: AmbientConditions, cfg: PhysicsValidationConfig
) -> list[ValidationIssue]:
    """More wing must buy cornering and cost straight-line speed.

    This is what makes different circuits want different cars without any
    per-track correction (project rule 2.3).  If it ever stopped holding, every
    circuit would want the same setup.
    """
    issues: list[ValidationIssue] = []
    rho = ambient.air_density
    low = vehicle.with_wing(0.0)
    high = vehicle.with_wing(1.0)

    if high.downforce_area() <= low.downforce_area():
        issues.append(
            _issue("wing_trade_off", Severity.ERROR, "more wing did not add downforce")
        )
    if high.drag_area() <= low.drag_area():
        issues.append(
            _issue("wing_trade_off", Severity.ERROR, "more wing did not add drag")
        )

    low_top = benchmark_vehicle(low, ambient, corner_radii=()).top_speed
    high_top = benchmark_vehicle(high, ambient, corner_radii=()).top_speed

    # A 100 m corner keeps both configurations grip limited, which is where the
    # comparison means something: in a corner either car could take flat out,
    # downforce is not the constraint and the two would tie.
    fast_corner = 1.0 / 100.0
    low_speed = corner_speed_limit(low, fast_corner, rho, max_speed=low_top)
    high_speed = corner_speed_limit(high, fast_corner, rho, max_speed=high_top)
    if high_speed <= low_speed:
        issues.append(
            _issue(
                "wing_trade_off",
                Severity.ERROR,
                f"more wing did not raise the speed through a 100 m corner "
                f"({ms_to_kph(low_speed):.1f} -> {ms_to_kph(high_speed):.1f} km/h)",
            )
        )

    if high_top >= low_top:
        issues.append(
            _issue(
                "wing_trade_off",
                Severity.ERROR,
                f"more wing did not cost top speed "
                f"({ms_to_kph(low_top):.1f} -> {ms_to_kph(high_top):.1f} km/h)",
            )
        )
    else:
        issues.append(
            _issue(
                "wing_trade_off",
                Severity.INFO,
                f"wing range spans {ms_to_kph(low_top):.0f}-{ms_to_kph(high_top):.0f} km/h "
                f"top speed and {ms_to_kph(low_speed):.0f}-{ms_to_kph(high_speed):.0f} km/h "
                f"through a 100 m corner",
            )
        )
    return issues


def check_mass_reduces_acceleration(
    vehicle: Vehicle, ambient: AmbientConditions, cfg: PhysicsValidationConfig
) -> list[ValidationIssue]:
    """Mass up, acceleration down (project rule 39) -- and cornering with it."""
    issues: list[ValidationIssue] = []
    rho = ambient.air_density
    light = vehicle.total_mass()
    heavy = light + 100.0

    for speed in (kph_to_ms(80.0), kph_to_ms(200.0)):
        light_a = max_acceleration(vehicle, speed, rho, mass=light)
        heavy_a = max_acceleration(vehicle, speed, rho, mass=heavy)
        if heavy_a >= light_a:
            issues.append(
                _issue(
                    "mass_acceleration",
                    Severity.ERROR,
                    f"adding 100 kg did not reduce acceleration at "
                    f"{ms_to_kph(speed):.0f} km/h ({light_a:.3f} -> {heavy_a:.3f} m/s^2)",
                )
            )

    light_corner = corner_speed_limit(vehicle, 1.0 / 100.0, rho, mass=light)
    heavy_corner = corner_speed_limit(vehicle, 1.0 / 100.0, rho, mass=heavy)
    if heavy_corner >= light_corner:
        issues.append(
            _issue(
                "mass_cornering",
                Severity.ERROR,
                f"adding 100 kg did not reduce cornering speed "
                f"({ms_to_kph(light_corner):.2f} -> {ms_to_kph(heavy_corner):.2f} km/h)",
            )
        )
    return issues


def check_power_improves_acceleration(
    vehicle: Vehicle, ambient: AmbientConditions, cfg: PhysicsValidationConfig
) -> list[ValidationIssue]:
    """Rule 40, Test E: more engine power, better acceleration.

    Checked at a speed where the car is power limited rather than traction
    limited -- at a standing start more power only spins the wheels, which is
    itself the correct behaviour.
    """
    issues: list[ValidationIssue] = []
    rho = ambient.air_density
    stronger_spec = replace(
        vehicle.spec,
        power_unit=replace(
            vehicle.spec.power_unit,
            max_power=vehicle.spec.power_unit.max_power * 1.15,
        ),
    )
    stronger = vehicle.with_spec(stronger_spec)

    speed = kph_to_ms(250.0)
    base = max_acceleration(vehicle, speed, rho)
    boosted = max_acceleration(stronger, speed, rho)
    if boosted <= base:
        issues.append(
            _issue(
                "power_acceleration",
                Severity.ERROR,
                f"15% more power did not improve acceleration at 250 km/h "
                f"({base:.3f} -> {boosted:.3f} m/s^2)",
            )
        )

    base_top = benchmark_vehicle(vehicle, ambient, corner_radii=()).top_speed
    boosted_top = benchmark_vehicle(stronger, ambient, corner_radii=()).top_speed
    if boosted_top <= base_top:
        issues.append(
            _issue(
                "power_top_speed",
                Severity.ERROR,
                f"15% more power did not raise top speed "
                f"({ms_to_kph(base_top):.1f} -> {ms_to_kph(boosted_top):.1f} km/h)",
            )
        )
    return issues


def check_grip_improves_cornering(
    vehicle: Vehicle, ambient: AmbientConditions, cfg: PhysicsValidationConfig
) -> list[ValidationIssue]:
    """Rule 40, Test D: more tyre grip, more cornering capability."""
    issues: list[ValidationIssue] = []
    rho = ambient.air_density
    base_state = TyreState()
    grippy = TyreState(
        compound=replace(
            base_state.compound,
            peak_friction=base_state.compound.peak_friction * 1.10,
        )
    )

    for speed in (kph_to_ms(80.0), kph_to_ms(250.0)):
        base = max_lateral_acceleration(vehicle, speed, rho, tyre_state=base_state)
        better = max_lateral_acceleration(vehicle, speed, rho, tyre_state=grippy)
        if better <= base:
            issues.append(
                _issue(
                    "grip_cornering",
                    Severity.ERROR,
                    f"10% more tyre grip did not improve cornering at "
                    f"{ms_to_kph(speed):.0f} km/h ({base:.3f} -> {better:.3f} m/s^2)",
                )
            )

    base_speed = corner_speed_limit(vehicle, 1.0 / 80.0, rho, tyre_state=base_state)
    better_speed = corner_speed_limit(vehicle, 1.0 / 80.0, rho, tyre_state=grippy)
    if better_speed <= base_speed:
        issues.append(
            _issue(
                "grip_cornering",
                Severity.ERROR,
                f"10% more tyre grip did not raise the speed through an 80 m corner "
                f"({ms_to_kph(base_speed):.2f} -> {ms_to_kph(better_speed):.2f} km/h)",
            )
        )

    base_brake = max_deceleration(vehicle, kph_to_ms(200.0), rho, tyre_state=base_state)
    better_brake = max_deceleration(vehicle, kph_to_ms(200.0), rho, tyre_state=grippy)
    if better_brake <= base_brake:
        issues.append(
            _issue(
                "grip_braking",
                Severity.ERROR,
                "10% more tyre grip did not improve braking at 200 km/h",
            )
        )
    return issues


def check_radius_reduces_corner_speed(
    vehicle: Vehicle, ambient: AmbientConditions, cfg: PhysicsValidationConfig
) -> list[ValidationIssue]:
    """Rule 39, Track: a tighter corner must be slower."""
    issues: list[ValidationIssue] = []
    rho = ambient.air_density
    radii = (25.0, 50.0, 100.0, 200.0)
    speeds = [corner_speed_limit(vehicle, 1.0 / r, rho) for r in radii]
    for (r0, s0), (r1, s1) in zip(zip(radii, speeds), zip(radii[1:], speeds[1:])):
        if s1 <= s0:
            issues.append(
                _issue(
                    "corner_radius",
                    Severity.ERROR,
                    f"a {r1:.0f} m corner is not faster than a {r0:.0f} m one "
                    f"({ms_to_kph(s0):.1f} vs {ms_to_kph(s1):.1f} km/h)",
                )
            )
    straight = corner_speed_limit(vehicle, 0.0, rho, max_speed=120.0)
    if straight < 120.0:
        issues.append(
            _issue(
                "corner_radius",
                Severity.ERROR,
                "a straight was reported as speed limited by cornering",
            )
        )
    return issues


def check_load_sensitivity(
    vehicle: Vehicle, ambient: AmbientConditions, cfg: PhysicsValidationConfig
) -> list[ValidationIssue]:
    """The tyre must lose friction coefficient, but gain force, under load."""
    issues: list[ValidationIssue] = []
    compound: TyreCompound = TyreState().compound
    loads = (4000.0, 8000.0, 16000.0, 32000.0)
    coefficients = [compound.friction_coefficient(load) for load in loads]
    forces = [mu * load for mu, load in zip(coefficients, loads)]

    for (n0, m0), (n1, m1) in zip(zip(loads, coefficients), zip(loads[1:], coefficients[1:])):
        if m1 >= m0:
            issues.append(
                _issue(
                    "load_sensitivity",
                    Severity.ERROR,
                    f"friction coefficient did not fall from {n0:.0f} to {n1:.0f} N "
                    f"({m0:.4f} -> {m1:.4f})",
                )
            )
    for (n0, f0), (n1, f1) in zip(zip(loads, forces), zip(loads[1:], forces[1:])):
        if f1 <= f0:
            issues.append(
                _issue(
                    "load_sensitivity",
                    Severity.ERROR,
                    f"total grip force did not rise from {n0:.0f} to {n1:.0f} N "
                    f"({f0:.0f} -> {f1:.0f} N)",
                )
            )
    return issues


def check_friction_ellipse(
    vehicle: Vehicle, ambient: AmbientConditions, cfg: PhysicsValidationConfig
) -> list[ValidationIssue]:
    """Braking and cornering must compete for one friction budget."""
    issues: list[ValidationIssue] = []
    rho = ambient.air_density
    speed = kph_to_ms(200.0)
    free = max_lateral_acceleration(vehicle, speed, rho)
    limit = vehicle.tyre_model.grip_limit(
        TyreState().compound, vehicle.total_mass() * 9.80665
    )
    braking = max_lateral_acceleration(
        vehicle, speed, rho, longitudinal_force_used=0.7 * limit.capacity
    )
    if braking >= free:
        issues.append(
            _issue(
                "friction_ellipse",
                Severity.ERROR,
                f"using longitudinal grip did not reduce lateral capability "
                f"({free:.3f} -> {braking:.3f} m/s^2)",
            )
        )
    return issues


def check_braking_improves_with_speed(
    vehicle: Vehicle, ambient: AmbientConditions, cfg: PhysicsValidationConfig
) -> list[ValidationIssue]:
    """Downforce must make an F1 car brake harder from high speed than low."""
    issues: list[ValidationIssue] = []
    rho = ambient.air_density
    slow = max_deceleration(vehicle, kph_to_ms(80.0), rho)
    fast = max_deceleration(vehicle, kph_to_ms(280.0), rho)
    if fast <= slow:
        issues.append(
            _issue(
                "braking_vs_speed",
                Severity.ERROR,
                f"braking was not stronger at 280 km/h than at 80 km/h "
                f"({slow / 9.80665:.2f} g vs {fast / 9.80665:.2f} g)",
            )
        )
    return issues


def check_axle_grip_is_consistent(
    vehicle: Vehicle, ambient: AmbientConditions, cfg: PhysicsValidationConfig
) -> list[ValidationIssue]:
    """Two axles must not have more grip between them than the whole car.

    Friction coefficient falls with load, so asking about half a car's load
    returns a higher coefficient than asking about all of it.  If the axle
    solvers and the lateral model do not agree on what a load is spread over,
    that difference becomes free grip: a car could brake or launch harder than
    its own friction circle allows, purely because a different function asked
    the question.  Split evenly, the two must add up exactly.
    """
    issues: list[ValidationIssue] = []
    compound = TyreState().compound
    model = vehicle.tyre_model
    for load in (8_000.0, 20_000.0, 35_000.0):
        car = model.grip_limit(compound, load).capacity
        axles = 2.0 * model.grip_limit(compound, load / 2.0, tyres=2).capacity
        if car <= 0.0:
            continue
        error = abs(axles - car) / car
        if error > 1e-6:
            issues.append(
                _issue(
                    "axle_grip_basis",
                    Severity.ERROR,
                    f"at {load:.0f} N the two axles offer {axles:.0f} N between "
                    f"them but the whole car offers {car:.0f} N "
                    f"({error * 100:.2f}% apart)",
                )
            )
    return issues


def check_brake_bias_matters(
    vehicle: Vehicle, ambient: AmbientConditions, cfg: PhysicsValidationConfig
) -> list[ValidationIssue]:
    """Braking must be limited by an axle, not by the car as a lump.

    The bias is fixed while the car is stopping, so sending too much effort to
    either axle wastes the other one's grip and the car stops more slowly.  If
    bias made no difference, braking would be being charged against the total
    load -- which quietly assumes a bias that chases the load transfer around,
    and overstates high-speed braking by a wide margin.
    """
    issues: list[ValidationIssue] = []
    rho = ambient.air_density
    speed = kph_to_ms(280.0)
    biases = (0.40, 0.50, 0.57, 0.68, 0.78)
    results: list[tuple[float, float]] = []
    for bias in biases:
        try:
            car = vehicle.with_spec(
                replace(
                    vehicle.spec,
                    brakes=replace(vehicle.spec.brakes, brake_bias_front=bias),
                )
            )
        except Exception:  # a spec may legitimately restrict the range
            continue
        results.append((bias, max_deceleration(car, speed, rho)))

    if len(results) < 3:
        return issues

    best_bias, best = max(results, key=lambda item: item[1])
    worst_bias, worst = min(results, key=lambda item: item[1])
    if best <= worst * 1.001:
        issues.append(
            _issue(
                "brake_bias",
                Severity.ERROR,
                "brake bias made no difference to braking, so braking is not "
                "limited by either axle",
            )
        )
        return issues

    if best_bias in (results[0][0], results[-1][0]):
        issues.append(
            _issue(
                "brake_bias",
                Severity.WARNING,
                f"the best brake bias tried ({best_bias:.2f} front) is at the end "
                f"of the range, so the car's own bias is not near its optimum",
            )
        )
    issues.append(
        _issue(
            "brake_bias",
            Severity.INFO,
            f"brake bias is worth {(best - worst) / 9.80665:.2f} g at 280 km/h; "
            f"best {best_bias:.2f} front at {best / 9.80665:.2f} g, "
            f"worst {worst_bias:.2f} at {worst / 9.80665:.2f} g",
        )
    )
    return issues


def check_air_density_effects(
    vehicle: Vehicle, ambient: AmbientConditions, cfg: PhysicsValidationConfig
) -> list[ValidationIssue]:
    """Denser air must mean more downforce and a lower top speed."""
    issues: list[ValidationIssue] = []
    cold = AmbientConditions(air_temperature=5.0, relative_humidity=0.2)
    hot = AmbientConditions(air_temperature=40.0, relative_humidity=0.6)
    if cold.air_density <= hot.air_density:
        issues.append(
            _issue(
                "air_density",
                Severity.ERROR,
                f"cold air is not denser than hot air "
                f"({cold.air_density:.4f} vs {hot.air_density:.4f} kg/m^3)",
            )
        )
        return issues

    cold_top = benchmark_vehicle(vehicle, cold, corner_radii=()).top_speed
    hot_top = benchmark_vehicle(vehicle, hot, corner_radii=()).top_speed
    cold_corner = corner_speed_limit(
        vehicle, 1.0 / 100.0, cold.air_density, max_speed=cold_top
    )
    hot_corner = corner_speed_limit(
        vehicle, 1.0 / 100.0, hot.air_density, max_speed=hot_top
    )
    if cold_corner <= hot_corner:
        issues.append(
            _issue(
                "air_density",
                Severity.ERROR,
                "denser air did not improve cornering speed",
            )
        )
    if cold_top >= hot_top:
        issues.append(
            _issue(
                "air_density",
                Severity.ERROR,
                "denser air did not reduce top speed",
            )
        )
    else:
        issues.append(
            _issue(
                "air_density",
                Severity.INFO,
                f"5 degC to 40 degC moves top speed by "
                f"{ms_to_kph(hot_top - cold_top):+.1f} km/h and 100 m corner speed by "
                f"{ms_to_kph(hot_corner - cold_corner):+.1f} km/h",
            )
        )
    return issues


def check_fuel_mass_effect(
    vehicle: Vehicle, ambient: AmbientConditions, cfg: PhysicsValidationConfig
) -> list[ValidationIssue]:
    """A full fuel load must make the car slower (project rule 23)."""
    issues: list[ValidationIssue] = []
    rho = ambient.air_density
    empty = vehicle.mass.total_mass(0.0)
    full = vehicle.mass.total_mass(110.0)

    empty_a = max_acceleration(vehicle, kph_to_ms(150.0), rho, mass=empty)
    full_a = max_acceleration(vehicle, kph_to_ms(150.0), rho, mass=full)
    if full_a >= empty_a:
        issues.append(
            _issue(
                "fuel_mass",
                Severity.ERROR,
                "a full fuel load did not reduce acceleration",
            )
        )
    empty_corner = corner_speed_limit(vehicle, 1.0 / 100.0, rho, mass=empty)
    full_corner = corner_speed_limit(vehicle, 1.0 / 100.0, rho, mass=full)
    if full_corner >= empty_corner:
        issues.append(
            _issue(
                "fuel_mass",
                Severity.ERROR,
                "a full fuel load did not reduce cornering speed",
            )
        )
    else:
        issues.append(
            _issue(
                "fuel_mass",
                Severity.INFO,
                f"110 kg of fuel costs {ms_to_kph(empty_corner - full_corner):.2f} km/h "
                f"through a 100 m corner",
            )
        )
    return issues


# ---------------------------------------------------------------------------
# Envelope checks -- does it land where a real car lands?
# ---------------------------------------------------------------------------


def check_performance_envelope(
    vehicle: Vehicle, ambient: AmbientConditions, cfg: PhysicsValidationConfig
) -> list[ValidationIssue]:
    """Compare the measured envelope against a real Formula 1 car."""
    issues: list[ValidationIssue] = []
    benchmark = benchmark_vehicle(vehicle, ambient, corner_radii=())

    def envelope(
        name: str, value: float, low: float, high: float, unit: str, scale: float = 1.0
    ) -> None:
        if value < low:
            issues.append(
                _issue(
                    "performance_envelope",
                    Severity.ERROR,
                    f"{name} {value * scale:.2f} {unit} is below the plausible "
                    f"minimum {low * scale:.2f} {unit}",
                )
            )
        elif value > high:
            issues.append(
                _issue(
                    "performance_envelope",
                    Severity.ERROR,
                    f"{name} {value * scale:.2f} {unit} is above the plausible "
                    f"maximum {high * scale:.2f} {unit}",
                )
            )

    envelope(
        "top speed", benchmark.top_speed, cfg.min_top_speed, cfg.max_top_speed,
        "km/h", 3.6,
    )
    envelope(
        "peak lateral acceleration", benchmark.peak_lateral_g,
        cfg.min_peak_lateral_g, cfg.max_peak_lateral_g, "g",
    )
    envelope(
        "peak braking", benchmark.peak_braking_g,
        cfg.min_peak_braking_g, cfg.max_peak_braking_g, "g",
    )
    envelope(
        "standing acceleration", benchmark.standing_acceleration_g,
        cfg.min_standing_acceleration_g, cfg.max_standing_acceleration_g, "g",
    )

    low_speed_lateral = (
        max_lateral_acceleration(vehicle, kph_to_ms(60.0), ambient.air_density) / 9.80665
    )
    if low_speed_lateral > cfg.max_low_speed_lateral_g:
        issues.append(
            _issue(
                "performance_envelope",
                Severity.ERROR,
                f"lateral acceleration at 60 km/h is {low_speed_lateral:.2f} g, above "
                f"{cfg.max_low_speed_lateral_g:.2f} g -- there is almost no downforce "
                f"at that speed, so this is mechanical grip alone",
            )
        )

    issues.append(
        _issue(
            "performance_envelope",
            Severity.INFO,
            f"top speed {ms_to_kph(benchmark.top_speed):.1f} km/h, "
            f"peak lateral {benchmark.peak_lateral_g:.2f} g, "
            f"peak braking {benchmark.peak_braking_g:.2f} g, "
            f"standing {benchmark.standing_acceleration_g:.2f} g",
        )
    )
    return issues


def check_launch_is_traction_limited(
    vehicle: Vehicle, ambient: AmbientConditions, cfg: PhysicsValidationConfig
) -> list[ValidationIssue]:
    """From rest, the tyres -- not the engine -- must be the limit.

    If a standing start were power limited, the car would be under-powered by a
    wide margin, and adding power would improve the launch, which is not how a
    Formula 1 start works.
    """
    issues: list[ValidationIssue] = []
    rho = ambient.air_density
    stronger = vehicle.with_spec(
        replace(
            vehicle.spec,
            power_unit=replace(
                vehicle.spec.power_unit,
                max_power=vehicle.spec.power_unit.max_power * 1.5,
                peak_wheel_torque=vehicle.spec.power_unit.peak_wheel_torque * 1.5,
            ),
        )
    )
    base = max_acceleration(vehicle, 0.5, rho)
    boosted = max_acceleration(stronger, 0.5, rho)
    if boosted > base * 1.02:
        issues.append(
            _issue(
                "traction_limit",
                Severity.WARNING,
                f"50% more power improved the standing start by "
                f"{(boosted / base - 1) * 100:.1f}% -- the launch is power limited "
                f"rather than traction limited",
            )
        )
    return issues


#: The registered checks, run in order.  Append to extend.
PHYSICS_CHECKS: list[Check] = [
    check_downforce_rises_with_speed,
    check_drag_rises_with_speed,
    check_wing_trade_off,
    check_mass_reduces_acceleration,
    check_power_improves_acceleration,
    check_grip_improves_cornering,
    check_radius_reduces_corner_speed,
    check_load_sensitivity,
    check_friction_ellipse,
    check_axle_grip_is_consistent,
    check_brake_bias_matters,
    check_braking_improves_with_speed,
    check_air_density_effects,
    check_fuel_mass_effect,
    check_performance_envelope,
    check_launch_is_traction_limited,
]


def validate_vehicle(
    vehicle: Vehicle,
    ambient: AmbientConditions | None = None,
    config: SimulationConfig | PhysicsValidationConfig | None = None,
    *,
    checks: list[Check] | None = None,
) -> PhysicsReport:
    """Run every registered physics check against ``vehicle``."""
    conditions = ambient or AmbientConditions()
    if isinstance(config, SimulationConfig):
        cfg = config.physics_validation
    else:
        cfg = config or PhysicsValidationConfig()
    issues: list[ValidationIssue] = []
    for check in checks if checks is not None else PHYSICS_CHECKS:
        issues.extend(check(vehicle, conditions, cfg))
    return PhysicsReport(subject=vehicle.name, issues=tuple(issues))
