"""The track builder: definitions in, segments out.

.. code-block:: text

    Definitions -> LayoutSpans -> Segmentation -> Overlay sampling -> Track

The three stages are kept separate because they answer different questions.

**Layout spans** turn each straight and corner into runs of *linear curvature*.
A corner becomes three spans -- entry transition, constant-radius arc, exit
transition -- whose combined turn angle is exactly the requested angle.  This
stage decides the circuit's shape and depends only on the definition.

**Segmentation** chooses how finely to sample each span (project rule 7).
Resolution is adaptive: a straight is cut into long segments, a corner
transition into short ones, because the criteria are expressed in *heading
change* and *curvature change* rather than in metres.  A hairpin therefore
lands near 1 m resolution on its own, without anybody asking for it.

**Overlay sampling** evaluates elevation, banking, surface, width, kerbs, DRS
and sectors at each segment, then integrates the plan-view geometry.

The split is what makes resolution independence hold: stage 1 fixes the
physics-relevant geometry, and stage 2 can only decide how densely it is
sampled.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..core.config import SimulationConfig, TrackBuildConfig
from ..core.errors import TrackBuildError
from ..core.interpolation import ConstantProfile, PiecewiseProfile, clamp
from ..core.units import Metres
from .banking import BankingProfile
from .definitions import (
    CornerDefinition,
    StraightDefinition,
    TrackDefaults,
    TrackDefinition,
)
from .drs import DrsMap
from .elevation import ElevationProfile
from .geometry import integrate_arc
from .model import Track
from .segment import SegmentKind, TrackSegment
from .surface import KerbMap, SurfaceMap, SurfaceRegion

__all__ = ["LayoutSpan", "TrackBuilder", "build_track"]


@dataclass(frozen=True, slots=True)
class LayoutSpan:
    """One run of linear curvature -- a straight, a transition, or an arc."""

    kind: SegmentKind
    length: Metres
    curvature_start: float
    curvature_end: float
    corner_id: int | None = None
    corner_name: str | None = None

    @property
    def heading_change(self) -> float:
        return 0.5 * (self.curvature_start + self.curvature_end) * self.length


class TrackBuilder:
    """Builds :class:`~f1_race_engine.track.model.Track` objects.

    The builder is stateless between calls, so one instance can build every
    circuit on the calendar.
    """

    def __init__(self, config: TrackBuildConfig | SimulationConfig | None = None) -> None:
        if isinstance(config, SimulationConfig):
            config = config.track_build
        self._config = config or TrackBuildConfig()

    @property
    def config(self) -> TrackBuildConfig:
        return self._config

    # -- stage 1: layout -> spans -------------------------------------------

    def layout_spans(self, definition: TrackDefinition) -> list[LayoutSpan]:
        """Expand the layout into runs of linear curvature."""
        defaults = definition.defaults
        spans: list[LayoutSpan] = []
        for element in definition.layout:
            if isinstance(element, StraightDefinition):
                spans.append(
                    LayoutSpan(
                        kind=SegmentKind.STRAIGHT,
                        length=element.length,
                        curvature_start=0.0,
                        curvature_end=0.0,
                    )
                )
            elif isinstance(element, CornerDefinition):
                spans.extend(self._corner_spans(element, defaults))
            else:  # pragma: no cover - guarded by the definition types
                raise TrackBuildError(
                    f"unsupported layout element: {type(element).__name__}"
                )
        return spans

    @staticmethod
    def _corner_spans(
        corner: CornerDefinition, defaults: TrackDefaults
    ) -> list[LayoutSpan]:
        curvature = corner.curvature
        curvature_end = corner.curvature_end
        entry, exit_ = corner.transitions(defaults)
        arc = corner.constant_arc_length(defaults)
        if arc < -1e-9:  # pragma: no cover - transitions are capped below 0.5
            raise TrackBuildError(
                f"corner {corner.label}: transitions ({entry + exit_:.1f} m) exceed "
                f"the corner length ({corner.pure_arc_length():.1f} m)"
            )
        spans: list[LayoutSpan] = []
        if entry > 0.0:
            spans.append(
                LayoutSpan(
                    kind=SegmentKind.CORNER_ENTRY,
                    length=entry,
                    curvature_start=0.0,
                    curvature_end=curvature,
                    corner_id=corner.corner_id,
                    corner_name=corner.name,
                )
            )
        if arc > 0.0:
            spans.append(
                LayoutSpan(
                    kind=SegmentKind.CORNER,
                    length=arc,
                    curvature_start=curvature,
                    curvature_end=curvature_end,
                    corner_id=corner.corner_id,
                    corner_name=corner.name,
                )
            )
        if exit_ > 0.0:
            spans.append(
                LayoutSpan(
                    kind=SegmentKind.CORNER_EXIT,
                    length=exit_,
                    curvature_start=curvature_end,
                    curvature_end=0.0,
                    corner_id=corner.corner_id,
                    corner_name=corner.name,
                )
            )
        return spans

    # -- stage 2: spans -> sampling counts ----------------------------------

    def segment_count(self, span: LayoutSpan) -> int:
        """How many segments to cut ``span`` into.

        Three criteria, whichever is tightest:

        1. a target length per segment (long on a straight, short in a corner);
        2. a cap on the heading change within one segment, which refines tight
           corners automatically;
        3. a cap on the curvature change within one segment, which refines
           corner entry and exit -- exactly where the physics changes fastest.
        """
        cfg = self._config
        if span.length <= 0.0:
            return 0

        target = (
            cfg.straight_segment_length
            if span.kind is SegmentKind.STRAIGHT
            else cfg.corner_segment_length
        )

        peak_curvature = max(abs(span.curvature_start), abs(span.curvature_end))
        if peak_curvature > 0.0:
            target = min(target, cfg.max_heading_change_per_segment / peak_curvature)

        curvature_change = abs(span.curvature_end - span.curvature_start)
        if curvature_change > 0.0:
            target = min(
                target,
                cfg.max_curvature_change_per_segment * span.length / curvature_change,
            )

        target = clamp(target, cfg.min_segment_length, cfg.max_segment_length)
        count = max(1, math.ceil(span.length / target - 1e-9))
        # Rounding the count up shortens every segment, which could push it
        # under the configured floor; cap the count so the floor really holds.
        max_count = max(1, math.floor(span.length / cfg.min_segment_length + 1e-9))
        return min(count, max_count)

    # -- stage 3: overlays and assembly -------------------------------------

    def build(self, definition: TrackDefinition) -> Track:
        """Build a :class:`Track` from ``definition``."""
        spans = self.layout_spans(definition)
        lap_length = math.fsum(span.length for span in spans)
        if lap_length <= 0.0:
            raise TrackBuildError(f"track {definition.name!r} has zero length")

        # Range-check overlays first: a control point outside the lap must be
        # reported as the data error it is, not as a downstream profile failure.
        self._check_overlay_ranges(definition, lap_length)

        elevation = self._elevation_profile(definition, lap_length)
        banking = self._banking_profile(definition, lap_length)
        surface = self._surface_map(definition)
        width = self._width_profile(definition, lap_length)
        kerbs = self._kerb_map(definition)
        drs = self._drs_map(definition, lap_length)
        sectors = definition.sectors

        segments: list[TrackSegment] = []
        distance = 0.0
        x = y = heading = 0.0
        index = 0
        quadrature = self._config.geometry_quadrature_intervals

        for span in spans:
            count = self.segment_count(span)
            if count == 0:
                continue
            step = span.length / count
            for i in range(count):
                start_fraction = i / count
                end_fraction = (i + 1) / count
                k_start = _lerp(span.curvature_start, span.curvature_end, start_fraction)
                k_end = _lerp(span.curvature_start, span.curvature_end, end_fraction)
                mid = distance + 0.5 * step
                surface_type, grip, roughness = surface.at(mid)

                segments.append(
                    TrackSegment(
                        index=index,
                        distance=distance,
                        length=step,
                        curvature_start=k_start,
                        curvature_end=k_end,
                        elevation_start=elevation.elevation(distance),
                        elevation_end=elevation.elevation(distance + step),
                        banking=banking.banking(mid),
                        surface_grip=grip,
                        surface_type=surface_type,
                        roughness=roughness,
                        track_width=width.value(mid),
                        sector=sectors.sector_of(mid) if sectors.boundaries else 1,
                        corner_id=span.corner_id,
                        corner_name=span.corner_name,
                        drs_zone=drs.zone_index_at(mid),
                        kerb=kerbs.at(mid),
                        kind=span.kind,
                        x=x,
                        y=y,
                        heading=heading,
                    )
                )
                x, y, heading = integrate_arc(
                    x, y, heading, k_start, k_end, step, intervals=quadrature
                )
                distance += step
                index += 1

        if definition.defaults.geometry == "centreline":
            segments = _apply_racing_line(segments)

        return Track(
            name=definition.name,
            country=definition.country,
            segments=tuple(segments),
            length=lap_length,
            sector_boundaries=tuple(sectors.boundaries),
            drs_map=drs,
            elevation_profile=elevation,
            banking_profile=banking,
            surface_map=surface,
            width_profile=width,
            kerb_map=kerbs,
            metadata=dict(definition.metadata),
            definition=definition,
        )

    # -- overlay construction ------------------------------------------------

    @staticmethod
    def _elevation_profile(
        definition: TrackDefinition, lap_length: Metres
    ) -> ElevationProfile:
        points = definition.elevation.control_points
        if not points:
            return ElevationProfile.flat(lap_length)
        return ElevationProfile.from_control_points(
            points, lap_length, method=definition.elevation.method
        )

    @staticmethod
    def _banking_profile(
        definition: TrackDefinition, lap_length: Metres
    ) -> BankingProfile:
        points = list(definition.banking.control_points)
        # A corner may declare its banking inline; expand those to control
        # points at the corner's midpoint, with flat track on either side.
        for start, end, element in definition.element_distances():
            if isinstance(element, CornerDefinition) and element.banking is not None:
                mid = 0.5 * (start + end)
                points.append((mid, element.banking))
        if not points:
            return BankingProfile.flat(lap_length)
        return BankingProfile.from_control_points_deg(
            sorted(points), lap_length, method=definition.banking.method
        )

    @staticmethod
    def _surface_map(definition: TrackDefinition) -> SurfaceMap:
        defaults = definition.defaults
        regions = [
            SurfaceRegion(
                start=region.start,
                end=region.end,
                surface_type=region.surface_type,
                grip=defaults.surface_grip if region.grip is None else region.grip,
                roughness=(
                    defaults.roughness if region.roughness is None else region.roughness
                ),
                name=region.name,
            )
            for region in definition.surface.regions
        ]
        return SurfaceMap(
            regions,
            default_type=defaults.surface_type,
            default_grip=defaults.surface_grip,
            default_roughness=defaults.roughness,
        )

    @staticmethod
    def _width_profile(
        definition: TrackDefinition, lap_length: Metres
    ) -> PiecewiseProfile:
        points = definition.width.control_points
        if not points:
            return ConstantProfile(definition.defaults.track_width)
        if len(points) == 1:
            return ConstantProfile(points[0][1])
        return PiecewiseProfile(
            points, method=definition.width.method, period=lap_length  # type: ignore[arg-type]
        )

    @staticmethod
    def _kerb_map(definition: TrackDefinition) -> KerbMap:
        return KerbMap(
            ((r.start, r.end, r.kerb) for r in definition.kerbs.regions),
            default=definition.defaults.kerb,
        )

    @staticmethod
    def _drs_map(definition: TrackDefinition, lap_length: Metres) -> DrsMap:
        return DrsMap(definition.drs.zones, lap_length)

    @staticmethod
    def _check_overlay_ranges(definition: TrackDefinition, lap_length: Metres) -> None:
        """Reject overlays that reference distances outside the lap.

        Caught here rather than in validation because an out-of-range overlay
        means the *data* is wrong, and building a track from it would silently
        drop the overlay instead of reporting the mistake.
        """
        tolerance = 1e-6 * max(1.0, lap_length)

        def check(distance: float, what: str) -> None:
            if not -tolerance <= distance <= lap_length + tolerance:
                raise TrackBuildError(
                    f"{definition.name}: {what} at {distance:.1f} m lies outside the "
                    f"lap (0 to {lap_length:.1f} m)"
                )

        for point in definition.elevation.control_points:
            check(point[0], "elevation control point")
        for point in definition.banking.control_points:
            check(point[0], "banking control point")
        for point in definition.width.control_points:
            check(point[0], "width control point")
        for region in definition.surface.regions:
            check(region.start, f"surface region {region.name or ''} start")
            check(region.end, f"surface region {region.name or ''} end")
        for kerb_region in definition.kerbs.regions:
            check(kerb_region.start, "kerb region start")
            check(kerb_region.end, "kerb region end")
        for zone in definition.drs.zones:
            check(zone.detection_distance, f"DRS zone {zone.index} detection")
            check(zone.activation_start, f"DRS zone {zone.index} activation start")
            check(zone.activation_end, f"DRS zone {zone.index} activation end")
        previous = 0.0
        for boundary in definition.sectors.boundaries:
            check(boundary, "sector boundary")
            if boundary <= previous:
                raise TrackBuildError(
                    f"{definition.name}: sector boundaries must strictly increase, "
                    f"got {boundary:.1f} m after {previous:.1f} m"
                )
            previous = boundary


def _apply_racing_line(segments: list[TrackSegment]) -> list[TrackSegment]:
    """Solve the line a car drives and hang it on the segments.

    Only for a circuit whose geometry is a surveyed centreline.  A hand-authored
    circuit already has the radii of the line, so solving another one on top
    would straighten a corner twice.
    """
    from dataclasses import replace as _replace

    from .racing_line import solve_racing_line

    if len(segments) < 8:
        return segments

    # The solver works on evenly spaced samples; the builder already produces
    # them, so a segment's midpoint curvature is the sample.
    step = sum(segment.length for segment in segments) / len(segments)
    curvature = [
        0.5 * (segment.curvature_start + segment.curvature_end)
        for segment in segments
    ]
    widths = [segment.track_width for segment in segments]
    line = solve_racing_line(curvature, widths, step)

    count = len(segments)
    return [
        _replace(
            segment,
            line_curvature_start=0.5 * (line.curvature[i - 1] + line.curvature[i]),
            line_curvature_end=0.5
            * (line.curvature[i] + line.curvature[(i + 1) % count]),
            line_offset_start=0.5 * (line.offset[i - 1] + line.offset[i]),
            line_offset_end=0.5 * (line.offset[i] + line.offset[(i + 1) % count]),
        )
        for i, segment in enumerate(segments)
    ]


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def build_track(
    definition: TrackDefinition,
    config: TrackBuildConfig | SimulationConfig | None = None,
) -> Track:
    """Convenience wrapper around :meth:`TrackBuilder.build`."""
    return TrackBuilder(config).build(definition)
