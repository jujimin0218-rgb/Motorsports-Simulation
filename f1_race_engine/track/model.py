"""The track model.

Project rule 5 states the central idea: a track is not a list of corners, it is
a mapping

.. code-block:: text

    distance -> track state

Everything downstream is built on that.  The speed profile walks distance and
asks for curvature; the lap simulation integrates ``dt = ds / v`` and asks for
gradient; the overtaking model asks for width and DRS.  None of them care how
finely the track happens to be sampled, which is why changing the resolution
cannot change the physics.

:class:`Track` is immutable and shared by every car on it.  Anything that
changes during a session lives in
:class:`~f1_race_engine.track.surface.TrackConditions`, which is passed to
:meth:`Track.state_at` when session-dependent grip is wanted.
"""

from __future__ import annotations

import bisect
import math
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..core.errors import TrackError
from ..core.interpolation import PiecewiseProfile
from ..core.units import Curvature, Metres, Radians, radius_from_curvature
from .banking import BankingProfile
from .curvature import CurvatureProfile, curvature_profile, summarise_corners
from .drs import DrsMap
from .elevation import ElevationProfile
from .geometry import Centerline, centerline_from_segments
from .segment import KerbType, SegmentKind, SurfaceType, TrackSegment

if TYPE_CHECKING:  # pragma: no cover
    from .definitions import TrackDefinition
    from .surface import KerbMap, SurfaceMap, TrackConditions

__all__ = ["Track", "TrackState"]


@dataclass(frozen=True, slots=True)
class TrackState:
    """The complete track environment at one distance around the lap.

    This is the only thing the physics sees of the circuit.  Adding a new
    track property later means adding a field here with a sensible default;
    every existing consumer keeps working.
    """

    distance: Metres
    curvature: Curvature
    radius: Metres
    gradient: float
    elevation: Metres
    banking: Radians
    grip: float
    """Effective grip: the static surface grip, multiplied by the session
    conditions when a :class:`TrackConditions` was supplied."""

    surface_type: SurfaceType
    roughness: float
    track_width: Metres
    sector: int
    corner_id: int | None
    corner_name: str | None
    drs_zone: int | None
    kerb: KerbType
    kind: SegmentKind
    segment_index: int
    x: Metres
    y: Metres
    heading: Radians
    # Session-dependent surface state; neutral until Phase 10 drives it.
    rubber: float = 0.0
    marbles: float = 0.0
    water_depth: float = 0.0

    @property
    def is_corner(self) -> bool:
        return self.kind is not SegmentKind.STRAIGHT

    @property
    def is_wet(self) -> bool:
        return self.water_depth > 0.0

    @property
    def has_drs(self) -> bool:
        return self.drs_zone is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "distance": self.distance,
            "curvature": self.curvature,
            "radius": None if math.isinf(self.radius) else self.radius,
            "gradient": self.gradient,
            "elevation": self.elevation,
            "banking": self.banking,
            "grip": self.grip,
            "surface_type": self.surface_type.value,
            "roughness": self.roughness,
            "track_width": self.track_width,
            "sector": self.sector,
            "corner_id": self.corner_id,
            "corner_name": self.corner_name,
            "drs_zone": self.drs_zone,
            "kerb": self.kerb.value,
            "kind": self.kind.value,
            "segment_index": self.segment_index,
            "x": self.x,
            "y": self.y,
            "heading": self.heading,
            "rubber": self.rubber,
            "marbles": self.marbles,
            "water_depth": self.water_depth,
        }


@dataclass(frozen=True)
class Track:
    """An immutable circuit, sampled into segments."""

    name: str
    segments: tuple[TrackSegment, ...]
    length: Metres
    country: str | None = None
    sector_boundaries: tuple[float, ...] = ()
    drs_map: DrsMap | None = None
    elevation_profile: ElevationProfile | None = None
    banking_profile: BankingProfile | None = None
    surface_map: "SurfaceMap | None" = None
    width_profile: "PiecewiseProfile | None" = None
    kerb_map: "KerbMap | None" = None
    metadata: dict[str, Any] = field(default_factory=dict)
    definition: "TrackDefinition | None" = field(default=None, repr=False)
    _starts: tuple[float, ...] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not self.segments:
            raise TrackError(f"track {self.name!r} has no segments")
        if self.length <= 0.0:
            raise TrackError(f"track {self.name!r} has non-positive length")
        object.__setattr__(
            self, "_starts", tuple(segment.distance for segment in self.segments)
        )

    # -- basic access --------------------------------------------------------

    def __len__(self) -> int:
        return len(self.segments)

    def __iter__(self) -> Iterator[TrackSegment]:
        return iter(self.segments)

    def __getitem__(self, index: int) -> TrackSegment:
        return self.segments[index]

    # -- distance handling ---------------------------------------------------

    def normalise_distance(self, distance: Metres) -> Metres:
        """Wrap ``distance`` into ``[0, length)``.

        Cars accumulate distance across laps, so every lookup wraps.
        """
        return distance % self.length

    def segment_index_at(self, distance: Metres) -> int:
        """Index of the segment containing ``distance`` (wrapping)."""
        wrapped = self.normalise_distance(distance)
        index = bisect.bisect_right(self._starts, wrapped) - 1
        if index < 0:
            return 0
        if index >= len(self.segments):
            return len(self.segments) - 1
        return index

    def segment_at(self, distance: Metres) -> TrackSegment:
        """The segment containing ``distance`` (wrapping)."""
        return self.segments[self.segment_index_at(distance)]

    def forward_distance(self, from_distance: Metres, to_distance: Metres) -> Metres:
        """Distance travelled going forwards from one point to another, m."""
        return (to_distance - from_distance) % self.length

    def gap_distance(self, ahead: Metres, behind: Metres) -> Metres:
        """Track distance from ``behind`` up to ``ahead``, m."""
        return self.forward_distance(behind, ahead)

    # -- the core query ------------------------------------------------------

    def state_at(
        self, distance: Metres, conditions: "TrackConditions | None" = None
    ) -> TrackState:
        """Resolve the full track state at ``distance``.

        Values that vary continuously within a segment -- curvature, elevation,
        heading -- are interpolated exactly, so the state is a smooth function
        of distance regardless of how coarsely the track was sampled.
        """
        wrapped = self.normalise_distance(distance)
        index = self.segment_index_at(wrapped)
        segment = self.segments[index]

        curvature = segment.curvature_at(wrapped)

        # Anything with a hard boundary -- surface regions, kerbs, DRS zones,
        # sectors -- is resolved from its own map at the exact distance rather
        # than read off the segment, whose value is only sampled at its
        # midpoint.  Without this, a query near a boundary would answer
        # differently depending on how finely the track happened to be sampled.
        surface_type = segment.surface_type
        static_grip = segment.surface_grip
        roughness = segment.roughness
        if self.surface_map is not None:
            surface_type, static_grip, roughness = self.surface_map.at(wrapped)

        grip = static_grip
        rubber = marbles = water = 0.0
        if conditions is not None:
            grip = static_grip * conditions.grip_multiplier(index)
            condition = conditions[index]
            rubber = condition.rubber
            marbles = condition.marbles
            water = condition.water_depth

        width = segment.track_width
        if self.width_profile is not None:
            width = self.width_profile.value(wrapped)

        kerb = segment.kerb
        if self.kerb_map is not None:
            kerb = self.kerb_map.at(wrapped)

        drs_zone = segment.drs_zone
        if self.drs_map is not None:
            drs_zone = self.drs_map.zone_index_at(wrapped)

        sector = self.sector_of(wrapped) if self.sector_boundaries else segment.sector

        gradient = segment.gradient
        elevation = segment.elevation_at(wrapped)
        if self.elevation_profile is not None:
            gradient = self.elevation_profile.gradient(wrapped)
            elevation = self.elevation_profile.elevation(wrapped)

        banking = segment.banking
        if self.banking_profile is not None:
            banking = self.banking_profile.banking(wrapped)

        return TrackState(
            distance=wrapped,
            curvature=curvature,
            radius=radius_from_curvature(curvature),
            gradient=gradient,
            elevation=elevation,
            banking=banking,
            grip=grip,
            surface_type=surface_type,
            roughness=roughness,
            track_width=width,
            sector=sector,
            corner_id=segment.corner_id,
            corner_name=segment.corner_name,
            drs_zone=drs_zone,
            kerb=kerb,
            kind=segment.kind,
            segment_index=index,
            x=segment.x,
            y=segment.y,
            heading=segment.heading_at(wrapped),
            rubber=rubber,
            marbles=marbles,
            water_depth=water,
        )

    # -- sectors -------------------------------------------------------------

    @property
    def sector_count(self) -> int:
        return len(self.sector_boundaries) + 1

    def sector_of(self, distance: Metres) -> int:
        """1-based timing sector containing ``distance``."""
        wrapped = self.normalise_distance(distance)
        sector = 1
        for boundary in self.sector_boundaries:
            if wrapped >= boundary:
                sector += 1
            else:
                break
        return sector

    def sector_ranges(self) -> list[tuple[float, float]]:
        """``(start, end)`` distance of each sector, m."""
        edges = [0.0, *self.sector_boundaries, self.length]
        return [(edges[i], edges[i + 1]) for i in range(len(edges) - 1)]

    def sector_lengths(self) -> list[Metres]:
        return [end - start for start, end in self.sector_ranges()]

    # -- corners -------------------------------------------------------------

    @property
    def corners(self) -> dict[int, dict[str, float | str | None]]:
        """Per-corner statistics keyed by corner id."""
        return summarise_corners(self.segments)

    @property
    def corner_count(self) -> int:
        return len({s.corner_id for s in self.segments if s.corner_id is not None})

    def straight_sections(self, min_length: Metres = 100.0) -> list[tuple[float, float]]:
        """``(start, end)`` of every straight at least ``min_length`` long."""
        sections: list[tuple[float, float]] = []
        start: float | None = None
        for segment in self.segments:
            if segment.is_straight:
                if start is None:
                    start = segment.distance
            elif start is not None:
                if segment.distance - start >= min_length:
                    sections.append((start, segment.distance))
                start = None
        if start is not None and self.length - start >= min_length:
            sections.append((start, self.length))
        return sections

    @property
    def longest_straight(self) -> Metres:
        sections = self.straight_sections(min_length=0.0)
        return max((end - start for start, end in sections), default=0.0)

    # -- geometry ------------------------------------------------------------

    def centerline(self, *, samples_per_segment: int = 1) -> Centerline:
        """The plan-view centreline, for maps and debug plots."""
        return centerline_from_segments(
            self.segments, samples_per_segment=samples_per_segment
        )

    def curvature_profile(self, *, samples_per_segment: int = 1) -> CurvatureProfile:
        return curvature_profile(self.segments, samples_per_segment=samples_per_segment)

    @property
    def total_heading_change(self) -> Radians:
        """Signed total turning over one lap, radians.

        A closed circuit gives ``+/-2*pi``: this is exact, because each
        segment's contribution ``k_mean * L`` is exact for linear curvature.
        """
        return math.fsum(segment.heading_change for segment in self.segments)

    @property
    def turn_count(self) -> float:
        """Total turning expressed in whole laps of the loop."""
        return self.total_heading_change / math.tau

    @property
    def is_clockwise(self) -> bool:
        return self.total_heading_change < 0.0

    # -- resolution ----------------------------------------------------------

    @property
    def segment_lengths(self) -> list[Metres]:
        return [segment.length for segment in self.segments]

    def resolution_stats(self) -> dict[str, float]:
        lengths = self.segment_lengths
        return {
            "segments": float(len(lengths)),
            "min_length": min(lengths),
            "max_length": max(lengths),
            "mean_length": math.fsum(lengths) / len(lengths),
        }

    # -- summary -------------------------------------------------------------

    @property
    def elevation_gain(self) -> Metres:
        """Total climb over a lap, m."""
        return math.fsum(
            max(segment.elevation_change, 0.0) for segment in self.segments
        )

    @property
    def max_abs_gradient(self) -> float:
        return max((abs(segment.gradient) for segment in self.segments), default=0.0)

    @property
    def min_radius(self) -> Metres:
        return min(
            (segment.corner_radius for segment in self.segments if segment.is_corner),
            default=math.inf,
        )

    def to_dict(self, *, include_segments: bool = False) -> dict[str, Any]:
        """Structured export (project rule 45).

        Segments are omitted by default: a 1 m-resolution circuit is thousands
        of them, and most consumers want the summary.
        """
        payload: dict[str, Any] = {
            "name": self.name,
            "country": self.country,
            "length": self.length,
            "segment_count": len(self.segments),
            "corner_count": self.corner_count,
            "sector_boundaries": list(self.sector_boundaries),
            "sector_lengths": self.sector_lengths(),
            "total_heading_change": self.total_heading_change,
            "clockwise": self.is_clockwise,
            "min_radius": None if math.isinf(self.min_radius) else self.min_radius,
            "longest_straight": self.longest_straight,
            "elevation_gain": self.elevation_gain,
            "max_abs_gradient": self.max_abs_gradient,
            "resolution": self.resolution_stats(),
            "drs_zones": [] if self.drs_map is None else self.drs_map.to_dict(),
            "metadata": dict(self.metadata),
        }
        if include_segments:
            payload["segments"] = [segment.to_dict() for segment in self.segments]
        return payload

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"Track({self.name!r}, length={self.length:.1f} m, "
            f"segments={len(self.segments)}, corners={self.corner_count})"
        )
