"""Track validation.

Project rules 8 and 39: a track whose geometry is physically impossible must be
caught here, before any of it reaches the physics.  A curvature that jumps, a
lap that does not close, a sector that covers no track -- all of these produce
lap times that look plausible and are quietly wrong, which is the worst kind of
bug to chase later.

Checks are registered in :data:`TRACK_CHECKS`.  Adding a check is appending one
function; nothing else changes.  Each returns a list of
:class:`ValidationIssue`, and the caller decides what to do with them --
:meth:`ValidationReport.raise_for_errors` for a hard stop, or the formatted
report for a build log.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, ClassVar

from ..core.config import TrackValidationConfig
from ..core.errors import TrackValidationError
from ..core.units import rad_to_deg
from ..core.validation import Severity, ValidationIssue
from ..core.validation import ValidationReport as BaseValidationReport
from .model import Track

__all__ = [
    "Severity",
    "TRACK_CHECKS",
    "ValidationIssue",
    "ValidationReport",
    "validate_track",
]


@dataclass(frozen=True)
class ValidationReport(BaseValidationReport):
    """Validation findings for one track."""

    kind: ClassVar[str] = "Track validation"
    error_type: ClassVar[type[Exception]] = TrackValidationError

    @property
    def track_name(self) -> str:
        """The track these findings belong to."""
        return self.subject


Check = Callable[[Track, TrackValidationConfig], list[ValidationIssue]]


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def check_lap_length(track: Track, cfg: TrackValidationConfig) -> list[ValidationIssue]:
    """The lap must be a plausible circuit length, and the segments must add up."""
    issues: list[ValidationIssue] = []
    if not cfg.min_lap_length <= track.length <= cfg.max_lap_length:
        issues.append(
            ValidationIssue(
                "lap_length",
                Severity.ERROR,
                f"lap length {track.length:.1f} m is outside the plausible range "
                f"[{cfg.min_lap_length:.0f}, {cfg.max_lap_length:.0f}] m",
            )
        )
    total = math.fsum(segment.length for segment in track.segments)
    if abs(total - track.length) > 1e-6 * max(1.0, track.length):
        issues.append(
            ValidationIssue(
                "lap_length",
                Severity.ERROR,
                f"segments total {total:.6f} m but the track reports "
                f"{track.length:.6f} m",
            )
        )
    return issues


def check_distance_continuity(
    track: Track, cfg: TrackValidationConfig
) -> list[ValidationIssue]:
    """Segments must tile the lap exactly: contiguous, ordered, no gaps."""
    issues: list[ValidationIssue] = []
    segments = track.segments
    tolerance = 1e-6 * max(1.0, track.length)

    if abs(segments[0].distance) > tolerance:
        issues.append(
            ValidationIssue(
                "distance_continuity",
                Severity.ERROR,
                f"first segment starts at {segments[0].distance:.6f} m, not 0",
                distance=segments[0].distance,
                segment_index=0,
            )
        )
    for previous, current in zip(segments, segments[1:]):
        gap = current.distance - previous.end_distance
        if abs(gap) > tolerance:
            issues.append(
                ValidationIssue(
                    "distance_continuity",
                    Severity.ERROR,
                    f"{'gap' if gap > 0 else 'overlap'} of {abs(gap):.6f} m between "
                    f"segments {previous.index} and {current.index}",
                    distance=current.distance,
                    segment_index=current.index,
                )
            )
    end = segments[-1].end_distance
    if abs(end - track.length) > tolerance:
        issues.append(
            ValidationIssue(
                "distance_continuity",
                Severity.ERROR,
                f"last segment ends at {end:.6f} m, not at the lap length "
                f"{track.length:.6f} m",
                distance=end,
                segment_index=segments[-1].index,
            )
        )
    return issues


def check_segment_lengths(
    track: Track, cfg: TrackValidationConfig
) -> list[ValidationIssue]:
    """Every segment must have a sane, positive length."""
    issues: list[ValidationIssue] = []
    for segment in track.segments:
        if segment.length <= 0.0:
            issues.append(
                ValidationIssue(
                    "segment_length",
                    Severity.ERROR,
                    f"non-positive segment length {segment.length:.6f} m",
                    distance=segment.distance,
                    segment_index=segment.index,
                )
            )
        elif segment.length < cfg.min_segment_length:
            issues.append(
                ValidationIssue(
                    "segment_length",
                    Severity.WARNING,
                    f"segment length {segment.length:.3f} m is below the configured "
                    f"minimum {cfg.min_segment_length:.3f} m",
                    distance=segment.distance,
                    segment_index=segment.index,
                )
            )
        elif segment.length > cfg.max_segment_length:
            issues.append(
                ValidationIssue(
                    "segment_length",
                    Severity.WARNING,
                    f"segment length {segment.length:.3f} m exceeds the configured "
                    f"maximum {cfg.max_segment_length:.3f} m",
                    distance=segment.distance,
                    segment_index=segment.index,
                )
            )
    return issues


def check_curvature_continuity(
    track: Track, cfg: TrackValidationConfig
) -> list[ValidationIssue]:
    """Curvature must be continuous, including across the start/finish line.

    Segments carry linear curvature, so a correctly built track matches to
    floating-point precision at every joint.  Any real jump means a corner was
    defined without a transition, or imported data is broken.
    """
    issues: list[ValidationIssue] = []
    segments = track.segments
    tolerance = cfg.curvature_continuity_tolerance

    for previous, current in zip(segments, segments[1:]):
        jump = abs(current.curvature_start - previous.curvature_end)
        if jump > tolerance:
            issues.append(
                ValidationIssue(
                    "curvature_continuity",
                    Severity.ERROR,
                    f"curvature jumps by {jump:.6g} 1/m between segments "
                    f"{previous.index} and {current.index} "
                    f"({previous.curvature_end:.6g} -> {current.curvature_start:.6g})",
                    distance=current.distance,
                    segment_index=current.index,
                )
            )
    seam = abs(segments[0].curvature_start - segments[-1].curvature_end)
    if seam > tolerance:
        issues.append(
            ValidationIssue(
                "curvature_continuity",
                Severity.ERROR,
                f"curvature jumps by {seam:.6g} 1/m across the start/finish line "
                f"({segments[-1].curvature_end:.6g} -> "
                f"{segments[0].curvature_start:.6g})",
                distance=0.0,
                segment_index=0,
            )
        )
    return issues


def check_curvature_magnitude(
    track: Track, cfg: TrackValidationConfig
) -> list[ValidationIssue]:
    """Corner radii must be physically drivable."""
    issues: list[ValidationIssue] = []
    # Aggregate by corner and judge the corner on its *tightest* point.  A
    # corner's transition segments always have a larger radius than its arc, so
    # reporting the first segment encountered would let a mild warning about
    # the turn-in mask an impossible radius at the apex.
    tightest: dict[object, tuple[float, Any]] = {}
    for segment in track.segments:
        radius = segment.corner_radius
        if math.isinf(radius):
            continue
        key: object = (
            segment.corner_id
            if segment.corner_id is not None
            else ("unnamed", segment.index)
        )
        current = tightest.get(key)
        if current is None or radius < current[0]:
            tightest[key] = (radius, segment)

    for radius, segment in sorted(tightest.values(), key=lambda pair: pair[1].index):
        if radius < cfg.min_corner_radius:
            issues.append(
                ValidationIssue(
                    "curvature_magnitude",
                    Severity.ERROR,
                    f"radius {radius:.2f} m is below the minimum physical radius "
                    f"{cfg.min_corner_radius:.1f} m",
                    distance=segment.distance,
                    segment_index=segment.index,
                )
            )
        elif radius < cfg.warn_corner_radius:
            issues.append(
                ValidationIssue(
                    "curvature_magnitude",
                    Severity.WARNING,
                    f"radius {radius:.2f} m is unusually tight (below "
                    f"{cfg.warn_corner_radius:.1f} m)",
                    distance=segment.distance,
                    segment_index=segment.index,
                )
            )
    return issues


def check_curvature_rate(
    track: Track, cfg: TrackValidationConfig
) -> list[ValidationIssue]:
    """Turn-in must not be sharper than any real circuit."""
    issues: list[ValidationIssue] = []
    for segment in track.segments:
        rate = abs(segment.curvature_rate)
        if rate > cfg.max_curvature_change_rate:
            issues.append(
                ValidationIssue(
                    "curvature_rate",
                    Severity.WARNING,
                    f"curvature changes at {rate:.6g} 1/m^2, above the limit "
                    f"{cfg.max_curvature_change_rate:.6g} 1/m^2 -- the transition "
                    f"into this corner is unrealistically abrupt",
                    distance=segment.distance,
                    segment_index=segment.index,
                )
            )
    return issues


def check_curvature_spikes(
    track: Track, cfg: TrackValidationConfig
) -> list[ValidationIssue]:
    """Find isolated curvature spikes.

    A genuine transition is a *run* of segments that all share the same
    curvature rate, so a segment whose rate towers over both of its neighbours
    is a data glitch rather than a corner.  This is the check that matters when
    track geometry is imported from noisy GPS traces (project rule 43).
    """
    issues: list[ValidationIssue] = []
    segments = track.segments
    if len(segments) < 3:
        return issues
    floor = 0.05 * cfg.max_curvature_change_rate
    count = len(segments)
    for i in range(count):
        rate = abs(segments[i].curvature_rate)
        if rate <= floor:
            continue
        before = abs(segments[(i - 1) % count].curvature_rate)
        after = abs(segments[(i + 1) % count].curvature_rate)
        neighbour = max(before, after, floor)
        if rate > cfg.curvature_spike_sigma * neighbour:
            issues.append(
                ValidationIssue(
                    "curvature_spike",
                    Severity.WARNING,
                    f"isolated curvature spike: rate {rate:.6g} 1/m^2 against "
                    f"neighbours {before:.6g} / {after:.6g} 1/m^2",
                    distance=segments[i].distance,
                    segment_index=segments[i].index,
                )
            )
    return issues


def check_heading_closure(
    track: Track, cfg: TrackValidationConfig
) -> list[ValidationIssue]:
    """A closed circuit must turn through a whole number of full turns."""
    total = track.total_heading_change
    turns = total / math.tau
    nearest = round(turns)
    error_deg = abs(rad_to_deg(total - nearest * math.tau))
    issues: list[ValidationIssue] = [
        ValidationIssue(
            "heading_closure",
            Severity.INFO,
            f"total turning {rad_to_deg(total):.3f} deg "
            f"({turns:+.4f} full turns, {'clockwise' if total < 0 else 'anticlockwise'})",
        )
    ]
    if nearest == 0:
        issues.append(
            ValidationIssue(
                "heading_closure",
                Severity.ERROR,
                f"the layout turns through {rad_to_deg(total):.3f} deg in total, so it "
                f"never closes into a lap",
            )
        )
    elif error_deg > cfg.heading_closure_tolerance_deg:
        issues.append(
            ValidationIssue(
                "heading_closure",
                Severity.ERROR,
                f"total turning is {error_deg:.3f} deg away from {nearest} full "
                f"turn(s), above the tolerance {cfg.heading_closure_tolerance_deg} deg",
            )
        )
    return issues


def check_position_closure(
    track: Track, cfg: TrackValidationConfig
) -> list[ValidationIssue]:
    """The plan-view centreline should return to the start/finish line."""
    centerline = track.centerline()
    error = centerline.closure_error
    fraction = centerline.closure_error_fraction
    issues: list[ValidationIssue] = [
        ValidationIssue(
            "position_closure",
            Severity.INFO,
            f"plan-view closure error {error:.2f} m ({fraction:.3%} of lap length)",
        )
    ]
    if fraction > cfg.position_closure_error_fraction:
        issues.append(
            ValidationIssue(
                "position_closure",
                Severity.ERROR,
                f"closure error {error:.1f} m is {fraction:.2%} of the lap, above the "
                f"limit {cfg.position_closure_error_fraction:.2%} -- the corner radii "
                f"or straight lengths are inconsistent",
            )
        )
    elif fraction > cfg.position_closure_warning_fraction:
        issues.append(
            ValidationIssue(
                "position_closure",
                Severity.WARNING,
                f"closure error {error:.1f} m is {fraction:.2%} of the lap; the "
                f"geometry is approximate",
            )
        )
    return issues


def check_elevation(track: Track, cfg: TrackValidationConfig) -> list[ValidationIssue]:
    """Gradients must be drivable and the lap must return to its own height."""
    issues: list[ValidationIssue] = []
    for segment in track.segments:
        if abs(segment.gradient) > cfg.max_gradient:
            issues.append(
                ValidationIssue(
                    "elevation",
                    Severity.ERROR,
                    f"gradient {segment.gradient_percent:.1f}% exceeds the limit "
                    f"{cfg.max_gradient * 100:.1f}%",
                    distance=segment.distance,
                    segment_index=segment.index,
                )
            )
    mismatch = 0.0
    if track.elevation_profile is not None:
        mismatch = abs(track.elevation_profile.closure_mismatch)
    start_elevation = track.segments[0].elevation_start
    end_elevation = track.segments[-1].elevation_end
    mismatch = max(mismatch, abs(end_elevation - start_elevation))
    if mismatch > cfg.elevation_closure_tolerance:
        issues.append(
            ValidationIssue(
                "elevation",
                Severity.ERROR,
                f"elevation does not close: the lap ends {mismatch:.2f} m from where "
                f"it started (tolerance {cfg.elevation_closure_tolerance:.2f} m)",
            )
        )
    return issues


def check_banking(track: Track, cfg: TrackValidationConfig) -> list[ValidationIssue]:
    """Banking must stay within a plausible range."""
    issues: list[ValidationIssue] = []
    limit = cfg.max_banking_deg
    for segment in track.segments:
        banking_deg = rad_to_deg(segment.banking)
        if abs(banking_deg) > limit:
            issues.append(
                ValidationIssue(
                    "banking",
                    Severity.ERROR,
                    f"banking {banking_deg:.1f} deg exceeds the limit {limit:.1f} deg",
                    distance=segment.distance,
                    segment_index=segment.index,
                )
            )
    return issues


def check_track_width(track: Track, cfg: TrackValidationConfig) -> list[ValidationIssue]:
    """Track width must stay within a plausible range."""
    issues: list[ValidationIssue] = []
    for segment in track.segments:
        if not cfg.min_track_width <= segment.track_width <= cfg.max_track_width:
            issues.append(
                ValidationIssue(
                    "track_width",
                    Severity.ERROR,
                    f"track width {segment.track_width:.2f} m is outside "
                    f"[{cfg.min_track_width:.1f}, {cfg.max_track_width:.1f}] m",
                    distance=segment.distance,
                    segment_index=segment.index,
                )
            )
    return issues


def check_surface_grip(track: Track, cfg: TrackValidationConfig) -> list[ValidationIssue]:
    """Static surface grip must stay within a plausible range."""
    issues: list[ValidationIssue] = []
    for segment in track.segments:
        if not cfg.min_surface_grip <= segment.surface_grip <= cfg.max_surface_grip:
            issues.append(
                ValidationIssue(
                    "surface_grip",
                    Severity.ERROR,
                    f"surface grip {segment.surface_grip:.3f} is outside "
                    f"[{cfg.min_surface_grip:.2f}, {cfg.max_surface_grip:.2f}]",
                    distance=segment.distance,
                    segment_index=segment.index,
                )
            )
    return issues


def check_sectors(track: Track, cfg: TrackValidationConfig) -> list[ValidationIssue]:
    """Sectors must be ordered, inside the lap and non-empty."""
    issues: list[ValidationIssue] = []
    boundaries = track.sector_boundaries
    if not boundaries:
        if cfg.require_sectors:
            issues.append(
                ValidationIssue(
                    "sectors", Severity.ERROR, "no timing sectors are defined"
                )
            )
        return issues

    previous = 0.0
    for boundary in boundaries:
        if not 0.0 < boundary < track.length:
            issues.append(
                ValidationIssue(
                    "sectors",
                    Severity.ERROR,
                    f"sector boundary {boundary:.1f} m lies outside the lap "
                    f"(0 to {track.length:.1f} m)",
                    distance=boundary,
                )
            )
        if boundary <= previous:
            issues.append(
                ValidationIssue(
                    "sectors",
                    Severity.ERROR,
                    f"sector boundaries are not strictly increasing: {boundary:.1f} m "
                    f"follows {previous:.1f} m",
                    distance=boundary,
                )
            )
        previous = boundary

    for index, length in enumerate(track.sector_lengths(), start=1):
        if length <= 0.0:
            issues.append(
                ValidationIssue(
                    "sectors", Severity.ERROR, f"sector {index} has no length"
                )
            )
    if cfg.require_sectors and track.sector_count != 3:
        issues.append(
            ValidationIssue(
                "sectors",
                Severity.WARNING,
                f"{track.sector_count} timing sectors defined; Formula 1 uses 3",
            )
        )
    return issues


def check_drs_zones(track: Track, cfg: TrackValidationConfig) -> list[ValidationIssue]:
    """DRS zones must be inside the lap, ordered and non-overlapping."""
    issues: list[ValidationIssue] = []
    drs = track.drs_map
    if drs is None or len(drs) == 0:
        if cfg.require_drs_zones:
            issues.append(
                ValidationIssue("drs", Severity.ERROR, "no DRS zones are defined")
            )
        return issues

    for zone in drs:
        for value, label in (
            (zone.detection_distance, "detection point"),
            (zone.activation_start, "activation start"),
            (zone.activation_end, "activation end"),
        ):
            if not 0.0 <= value <= track.length:
                issues.append(
                    ValidationIssue(
                        "drs",
                        Severity.ERROR,
                        f"zone {zone.index} {label} at {value:.1f} m lies outside the "
                        f"lap (0 to {track.length:.1f} m)",
                        distance=value,
                    )
                )
        forward = (zone.activation_start - zone.detection_distance) % track.length
        if forward > 0.5 * track.length:
            issues.append(
                ValidationIssue(
                    "drs",
                    Severity.WARNING,
                    f"zone {zone.index}: the detection point at "
                    f"{zone.detection_distance:.1f} m is most of a lap before its "
                    f"activation at {zone.activation_start:.1f} m",
                    distance=zone.detection_distance,
                )
            )
    for first, second in drs.overlaps():
        issues.append(
            ValidationIssue(
                "drs",
                Severity.ERROR,
                f"DRS zones {first} and {second} overlap",
            )
        )
    return issues


def check_corner_continuity(
    track: Track, cfg: TrackValidationConfig
) -> list[ValidationIssue]:
    """Each corner's segments must be contiguous.

    A corner id appearing in two separate places means the layout was built
    with duplicate ids, which would confuse every downstream consumer that
    aggregates by corner (overtaking difficulty, sector analysis, the UI).
    """
    issues: list[ValidationIssue] = []
    seen: dict[int, int] = {}
    previous: int | None = None
    for segment in track.segments:
        corner_id = segment.corner_id
        if corner_id != previous and corner_id is not None:
            seen[corner_id] = seen.get(corner_id, 0) + 1
        previous = corner_id
    # The lap wraps: a corner spanning the start/finish line legitimately
    # appears at both ends.
    first_id = track.segments[0].corner_id
    last_id = track.segments[-1].corner_id
    for corner_id, runs in seen.items():
        allowed = 2 if (corner_id == first_id and corner_id == last_id) else 1
        if runs > allowed:
            issues.append(
                ValidationIssue(
                    "corner_continuity",
                    Severity.ERROR,
                    f"corner {corner_id} appears in {runs} separate places on the lap",
                )
            )
    return issues


#: The registered checks, run in order.  Append to extend.
TRACK_CHECKS: list[Check] = [
    check_lap_length,
    check_distance_continuity,
    check_segment_lengths,
    check_curvature_continuity,
    check_curvature_magnitude,
    check_curvature_rate,
    check_curvature_spikes,
    check_heading_closure,
    check_position_closure,
    check_elevation,
    check_banking,
    check_track_width,
    check_surface_grip,
    check_sectors,
    check_drs_zones,
    check_corner_continuity,
]


def validate_track(
    track: Track,
    config: TrackValidationConfig | None = None,
    *,
    checks: Iterable[Check] | None = None,
) -> ValidationReport:
    """Run every registered check against ``track``."""
    cfg = config or TrackValidationConfig()
    issues: list[ValidationIssue] = []
    for check in checks if checks is not None else TRACK_CHECKS:
        issues.extend(check(track, cfg))
    return ValidationReport(subject=track.name, issues=tuple(issues))
