"""Automatic checks on the speed profile and the lap (project rules 39, 40).

Phase 2's suite validated the car standing on its own.  This one validates the
car *driving a circuit*, which is where a different class of mistake lives: a
profile that accelerates through an apex, a braking zone that ends after the
corner it was for, sector times that do not add up, or a lap that is quietly
independent of how much power the engine makes.

Rule 40's **Test C -- a faster car gives a faster lap** first becomes testable
here, because until Phase 3 there was no lap.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import ClassVar

from ..core.config import SimulationConfig
from ..core.errors import PhysicsValidationError
from ..core.units import ms_to_kph
from ..core.validation import Severity, ValidationIssue
from ..core.validation import ValidationReport as BaseValidationReport
from ..environment.conditions import AmbientConditions
from ..track.model import Track
from ..tyres.state import TyreState
from ..vehicle.model import Vehicle
from .lap_time import LapTimeResult, compute_lap_time
from .setup_search import wing_level_sweep

__all__ = ["LAP_CHECKS", "LapContext", "LapReport", "validate_lap"]


@dataclass(frozen=True)
class LapReport(BaseValidationReport):
    """Validation findings for one car on one circuit."""

    kind: ClassVar[str] = "Lap validation"
    error_type: ClassVar[type[Exception]] = PhysicsValidationError


@dataclass(frozen=True, slots=True)
class LapContext:
    """Everything a lap check needs, with the baseline lap computed once."""

    track: Track
    vehicle: Vehicle
    ambient: AmbientConditions
    baseline: LapTimeResult

    def lap_for(self, vehicle: Vehicle, **kwargs) -> LapTimeResult:
        return compute_lap_time(
            self.track, vehicle, self.ambient, analyse_zones=False, **kwargs
        )


Check = Callable[[LapContext], list[ValidationIssue]]


def _issue(check: str, severity: Severity, message: str) -> ValidationIssue:
    return ValidationIssue(check=check, severity=severity, message=message)


# ---------------------------------------------------------------------------
# The profile itself
# ---------------------------------------------------------------------------


def check_profile_respects_the_cornering_limit(
    context: LapContext,
) -> list[ValidationIssue]:
    """Nowhere on the lap may the car exceed what the tyres allow."""
    profile = context.baseline.profile
    issues: list[ValidationIssue] = []
    for index, (speed, limit) in enumerate(zip(profile.speed, profile.corner_limit)):
        if speed > limit + 1e-6:
            issues.append(
                _issue(
                    "profile_cornering_limit",
                    Severity.ERROR,
                    f"speed {ms_to_kph(speed):.2f} km/h exceeds the cornering limit "
                    f"{ms_to_kph(limit):.2f} km/h at {profile.distance[index]:.1f} m",
                )
            )
            break
    return issues


def check_profile_converged(context: LapContext) -> list[ValidationIssue]:
    """The forward/backward sweeps must have settled.

    An unconverged profile means a constraint has not finished propagating, and
    the lap time depends on where the lap happened to be cut.
    """
    profile = context.baseline.profile
    if not profile.converged:
        return [
            _issue(
                "profile_convergence",
                Severity.ERROR,
                f"the speed profile did not converge in {profile.passes} passes",
            )
        ]
    return [
        _issue(
            "profile_convergence",
            Severity.INFO,
            f"converged in {profile.passes} pass(es)",
        )
    ]


def check_profile_is_periodic(context: LapContext) -> list[ValidationIssue]:
    """A lap is a loop, so the profile must join up with itself.

    The check that catches a forward or backward sweep that does not wrap: the
    speed arriving at the start/finish line has to be one the car could also be
    leaving it at.
    """
    profile = context.baseline.profile
    issues: list[ValidationIssue] = []
    start = profile.speed[0]
    approach = profile.speed[-1]
    limit = profile.corner_limit[0]
    if start > limit + 1e-6:
        issues.append(
            _issue(
                "profile_periodicity",
                Severity.ERROR,
                "the speed at the start/finish line exceeds the cornering limit "
                "there, so the sweeps did not wrap around the lap",
            )
        )
    issues.append(
        _issue(
            "profile_periodicity",
            Severity.INFO,
            f"start/finish line crossed at {ms_to_kph(start):.1f} km/h "
            f"(arriving at {ms_to_kph(approach):.1f} km/h)",
        )
    )
    return issues


def check_sector_times_add_up(context: LapContext) -> list[ValidationIssue]:
    """Sector times must sum to the lap time, exactly."""
    result = context.baseline
    total = sum(result.sector_times)
    if abs(total - result.lap_time) > 1e-6:
        return [
            _issue(
                "sector_times",
                Severity.ERROR,
                f"sector times total {total:.6f} s but the lap took "
                f"{result.lap_time:.6f} s",
            )
        ]
    if any(sector <= 0.0 for sector in result.sector_times):
        return [
            _issue("sector_times", Severity.ERROR, "a sector took no time at all")
        ]
    return []


def check_lap_is_plausible(context: LapContext) -> list[ValidationIssue]:
    """The lap must land where a Formula 1 lap of this circuit would."""
    result = context.baseline
    issues: list[ValidationIssue] = []
    average_kph = result.average_speed_kph
    if not 110.0 <= average_kph <= 265.0:
        issues.append(
            _issue(
                "lap_plausibility",
                Severity.ERROR,
                f"average speed {average_kph:.1f} km/h is outside the range real "
                f"Formula 1 circuits produce (110-265 km/h)",
            )
        )
    if result.minimum_speed >= result.top_speed:
        issues.append(
            _issue(
                "lap_plausibility",
                Severity.ERROR,
                "the lap has no speed variation at all",
            )
        )
    if not 0.0 < result.braking_fraction < 0.5:
        issues.append(
            _issue(
                "lap_plausibility",
                Severity.ERROR,
                f"{result.braking_fraction:.1%} of the lap is spent braking, which no "
                f"real circuit produces",
            )
        )
    issues.append(
        _issue(
            "lap_plausibility",
            Severity.INFO,
            f"{result.formatted} -- {average_kph:.1f} km/h average, "
            f"{result.full_throttle_fraction:.0%} full throttle, "
            f"{result.braking_fraction:.0%} braking",
        )
    )
    return issues


def check_braking_zones_serve_corners(context: LapContext) -> list[ValidationIssue]:
    """Every braking zone must end at a corner, not in the middle of a straight."""
    issues: list[ValidationIssue] = []
    zones = context.baseline.braking_zones
    if not zones:
        return [
            _issue(
                "braking_zones",
                Severity.WARNING,
                "the lap contains no braking at all",
            )
        ]
    for zone in zones:
        if zone.corner_id is None:
            issues.append(
                _issue(
                    "braking_zones",
                    Severity.WARNING,
                    f"the braking zone at {zone.start_distance:.0f} m ends on a "
                    f"straight rather than at a corner",
                )
            )
        if zone.exit_speed >= zone.entry_speed:
            issues.append(
                _issue(
                    "braking_zones",
                    Severity.ERROR,
                    f"the braking zone at {zone.start_distance:.0f} m does not slow "
                    f"the car down",
                )
            )
    issues.append(
        _issue(
            "braking_zones",
            Severity.INFO,
            f"{len(zones)} braking zone(s), heaviest "
            f"{max(z.peak_deceleration_g for z in zones):.2f} g",
        )
    )
    return issues


def check_corner_exits_are_traction_limited(
    context: LapContext,
) -> list[ValidationIssue]:
    """Leaving a slow corner must be a traction problem, not a power one.

    Project rule 17: corner exit and straight-line acceleration have to behave
    differently, and this is the read-out that says they do.
    """
    zones = context.baseline.acceleration_zones
    if not zones:
        return []
    slowest = min(zones, key=lambda zone: zone.entry_speed)
    if slowest.entry_speed < 40.0 and slowest.traction_limited_fraction <= 0.0:
        return [
            _issue(
                "corner_exit",
                Severity.WARNING,
                f"the exit of the slowest corner ({ms_to_kph(slowest.entry_speed):.0f} "
                f"km/h) is not traction limited anywhere, which suggests the rear "
                f"axle load or the torque ceiling is wrong",
            )
        ]
    return [
        _issue(
            "corner_exit",
            Severity.INFO,
            f"slowest corner exit at {ms_to_kph(slowest.entry_speed):.0f} km/h is "
            f"traction limited for its first {slowest.traction_limited_length:.0f} m, "
            f"then power limited for the remaining "
            f"{slowest.length - slowest.traction_limited_length:.0f} m",
        )
    ]


# ---------------------------------------------------------------------------
# Rule 40 -- a better car must produce a better lap
# ---------------------------------------------------------------------------


def check_more_power_gives_a_faster_lap(context: LapContext) -> list[ValidationIssue]:
    """Rule 40, Test C."""
    vehicle = context.vehicle
    stronger = vehicle.with_spec(
        replace(
            vehicle.spec,
            power_unit=replace(
                vehicle.spec.power_unit,
                max_power=vehicle.spec.power_unit.max_power * 1.10,
            ),
        )
    )
    base = context.baseline.lap_time
    boosted = context.lap_for(stronger).lap_time
    if boosted >= base:
        return [
            _issue(
                "test_c_power",
                Severity.ERROR,
                f"10% more power did not produce a faster lap "
                f"({base:.3f} s -> {boosted:.3f} s)",
            )
        ]
    return [
        _issue(
            "test_c_power",
            Severity.INFO,
            f"10% more power is worth {base - boosted:.3f} s per lap",
        )
    ]


def check_more_grip_gives_a_faster_lap(context: LapContext) -> list[ValidationIssue]:
    """Rule 40, Test D, applied to a whole lap."""
    grippy = TyreState()
    grippy.compound = replace(
        grippy.compound, peak_friction=grippy.compound.peak_friction * 1.05
    )
    base = context.baseline.lap_time
    better = context.lap_for(context.vehicle, tyre_state=grippy).lap_time
    if better >= base:
        return [
            _issue(
                "test_d_grip",
                Severity.ERROR,
                f"5% more tyre grip did not produce a faster lap "
                f"({base:.3f} s -> {better:.3f} s)",
            )
        ]
    return [
        _issue(
            "test_d_grip",
            Severity.INFO,
            f"5% more tyre grip is worth {base - better:.3f} s per lap",
        )
    ]


def check_more_mass_gives_a_slower_lap(context: LapContext) -> list[ValidationIssue]:
    """Rule 39, mass -- now measured where it actually matters."""
    base = context.baseline.lap_time
    heavy = context.lap_for(
        context.vehicle, mass=context.vehicle.total_mass() + 50.0
    ).lap_time
    if heavy <= base:
        return [
            _issue(
                "mass_lap_time",
                Severity.ERROR,
                f"50 kg more did not produce a slower lap "
                f"({base:.3f} s -> {heavy:.3f} s)",
            )
        ]
    return [
        _issue(
            "mass_lap_time",
            Severity.INFO,
            f"50 kg costs {heavy - base:.3f} s per lap "
            f"({(heavy - base) / 5.0:.3f} s per 10 kg)",
        )
    ]


def check_setup_matters(context: LapContext) -> list[ValidationIssue]:
    """The circuit must have an opinion about wing level.

    If every setting gave the same lap time, the downforce/drag trade-off would
    have collapsed and every circuit would want the same car -- which is exactly
    the failure project rule 2.3 exists to prevent.
    """
    sweep = wing_level_sweep(
        context.track, context.vehicle, context.ambient, levels=(0.0, 0.5, 1.0)
    )
    if sweep.spread < 0.10:
        return [
            _issue(
                "setup_sensitivity",
                Severity.ERROR,
                f"wing level changes the lap by only {sweep.spread:.3f} s, so the "
                f"downforce/drag trade-off is not working",
            )
        ]
    return [
        _issue(
            "setup_sensitivity",
            Severity.INFO,
            f"wing level is worth {sweep.spread:.3f} s across its range; this "
            f"circuit wants {sweep.best.wing_level:.2f}",
        )
    ]


#: The registered checks, run in order.  Append to extend.
LAP_CHECKS: list[Check] = [
    check_profile_respects_the_cornering_limit,
    check_profile_converged,
    check_profile_is_periodic,
    check_sector_times_add_up,
    check_lap_is_plausible,
    check_braking_zones_serve_corners,
    check_corner_exits_are_traction_limited,
    check_more_power_gives_a_faster_lap,
    check_more_grip_gives_a_faster_lap,
    check_more_mass_gives_a_slower_lap,
    check_setup_matters,
]


def validate_lap(
    track: Track,
    vehicle: Vehicle,
    ambient: AmbientConditions | None = None,
    config: SimulationConfig | None = None,
    *,
    checks: list[Check] | None = None,
    baseline: LapTimeResult | None = None,
) -> LapReport:
    """Run every registered lap check for ``vehicle`` around ``track``."""
    conditions = ambient or AmbientConditions()
    result = baseline or compute_lap_time(track, vehicle, conditions)
    context = LapContext(
        track=track, vehicle=vehicle, ambient=conditions, baseline=result
    )
    issues: list[ValidationIssue] = []
    for check in checks if checks is not None else LAP_CHECKS:
        issues.extend(check(context))
    return LapReport(
        subject=f"{vehicle.name} at {track.name}", issues=tuple(issues)
    )
