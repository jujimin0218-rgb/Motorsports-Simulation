"""The track segment -- the atomic unit of the track model.

A segment describes a short stretch of the racing surface.  Its geometry is
**static**: it is built once and shared by every car in the race, which is what
makes a twenty-car simulation affordable.  Anything that changes during a
session (rubber, marbles, standing water, grip evolution) lives in
:mod:`f1_race_engine.track.surface` instead, in a parallel array that the
track evolution model mutates.  Keeping the two apart is what allows Phase 10
to add weather without touching the track geometry at all.

Curvature is stored at both ends and varies **linearly** in between.  That is
not a detail: it means a corner's entry and exit are true clothoid transitions,
the curvature of the whole lap is continuous by construction (project rule 8),
and the geometry can be integrated in closed form.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Any

from ..core.interpolation import clamp, lerp
from ..core.units import Curvature, Metres, Radians, radius_from_curvature


class SurfaceType(str, Enum):
    """The kind of surface under the car.

    Inherits from ``str`` so the value serialises to plain JSON without a
    custom encoder.
    """

    ASPHALT = "asphalt"
    ABRASIVE_ASPHALT = "abrasive_asphalt"
    SMOOTH_ASPHALT = "smooth_asphalt"
    CONCRETE = "concrete"
    PAINTED = "painted"


class KerbType(str, Enum):
    """Kerbing available at the edge of the segment."""

    NONE = "none"
    FLAT = "flat"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    SAUSAGE = "sausage"


class SegmentKind(str, Enum):
    """Where in the corner sequence a segment sits.

    Used by the speed profile (Phase 3) and the driver model (Phase 4) to tell
    turn-in from mid-corner from exit without re-deriving it from curvature.
    """

    STRAIGHT = "straight"
    CORNER_ENTRY = "corner_entry"
    CORNER = "corner"
    CORNER_EXIT = "corner_exit"


@dataclass(frozen=True, slots=True)
class TrackSegment:
    """One immutable stretch of track.

    Attributes
    ----------
    index:
        Position in the track's segment list.
    distance:
        Distance of the segment **start** from the start/finish line, m.
    length:
        Segment length, m.
    curvature_start, curvature_end:
        Signed curvature at each end, 1/m.  Positive is a left-hand corner,
        negative a right-hand corner, zero a straight.
    elevation_start, elevation_end:
        Height above the track datum at each end, m.
    banking:
        Cross-slope at the segment midpoint, radians.  Signed like curvature:
        positive banking supports a left-hand corner, so banking helps when its
        sign matches the curvature's.
    surface_grip:
        Static grip multiplier of the surface itself (1.0 = reference asphalt).
        Session-dependent grip is applied on top by
        :class:`~f1_race_engine.track.surface.TrackConditions`.
    roughness:
        0 (glass-smooth) to 1 (heavily abrasive).  Feeds tyre wear from Phase 5.
    track_width:
        Usable width at this point, m.  Drives overtaking difficulty (Phase 9).
    sector:
        Timing sector, 1-based.
    corner_id / corner_name:
        Identify the corner this segment belongs to; ``None`` on a straight.
    drs_zone:
        Index of the DRS activation zone covering this segment, else ``None``.
    kerb:
        Kerbing available here.
    kind:
        Straight / corner entry / corner / corner exit.
    x, y, heading:
        Plan-view position and heading at the segment **start**.  Carried so
        that a 3D or SVG client can draw the track without re-integrating the
        curvature (project rule 44).

    Note
    ----
    Fields with a hard boundary -- ``surface_type``, ``surface_grip``,
    ``roughness``, ``track_width``, ``sector``, ``drs_zone``, ``kerb`` -- are
    **sampled at the segment midpoint**.  They are exact for plotting and for
    aggregate statistics, but a segment straddling a boundary can only carry
    one of the two values.  Physics must therefore query
    :meth:`~f1_race_engine.track.model.Track.state_at`, which resolves those
    fields from their own maps at the exact distance and so gives the same
    answer at any sampling resolution.
    """

    index: int
    distance: Metres
    length: Metres
    curvature_start: Curvature
    curvature_end: Curvature
    elevation_start: Metres
    elevation_end: Metres
    banking: Radians
    surface_grip: float
    surface_type: SurfaceType
    roughness: float
    track_width: Metres
    sector: int
    corner_id: int | None
    corner_name: str | None
    drs_zone: int | None
    kerb: KerbType
    kind: SegmentKind
    x: Metres
    y: Metres
    heading: Radians

    # -- derived geometry ----------------------------------------------------

    @property
    def end_distance(self) -> Metres:
        """Distance of the segment end from the start/finish line, m."""
        return self.distance + self.length

    @property
    def mid_distance(self) -> Metres:
        """Distance of the segment midpoint, m."""
        return self.distance + 0.5 * self.length

    @property
    def curvature(self) -> Curvature:
        """Mean curvature over the segment, 1/m.

        This is the value the cornering model uses when it treats the segment
        as a single step; :meth:`curvature_at` gives the exact profile.
        """
        return 0.5 * (self.curvature_start + self.curvature_end)

    @property
    def radius(self) -> Metres:
        """Mean radius, m.  ``inf`` on a straight."""
        return radius_from_curvature(self.curvature)

    @property
    def abs_curvature(self) -> Curvature:
        return abs(self.curvature)

    @property
    def corner_radius(self) -> Metres:
        """Unsigned mean radius, m.  ``inf`` on a straight."""
        return abs(self.radius)

    @property
    def tightest_radius(self) -> Metres:
        """Smallest radius reached anywhere inside the segment, m.

        Curvature is linear across a segment, so its extreme is at one end.
        Taking it from the ends rather than the midpoint is what makes a
        corner's minimum radius a fact about the *geometry* instead of about
        where the sampling happened to land: the peak curvature of a corner
        that changes radius sits exactly on an element boundary, and every
        element boundary is a segment boundary.
        """
        peak = max(abs(self.curvature_start), abs(self.curvature_end))
        return radius_from_curvature(peak)

    @property
    def curvature_change(self) -> Curvature:
        """Curvature change across the segment, 1/m."""
        return self.curvature_end - self.curvature_start

    @property
    def curvature_rate(self) -> float:
        """Rate of curvature change, 1/m^2 -- the clothoid sharpness."""
        if self.length <= 0.0:
            return 0.0
        return self.curvature_change / self.length

    @property
    def heading_change(self) -> Radians:
        """Heading change across the segment, radians.

        With curvature linear in arc length this integral is exact:
        ``0.5 * (k0 + k1) * L``.
        """
        return self.curvature * self.length

    @property
    def heading_end(self) -> Radians:
        return self.heading + self.heading_change

    @property
    def elevation(self) -> Metres:
        """Elevation at the segment midpoint, m."""
        return 0.5 * (self.elevation_start + self.elevation_end)

    @property
    def elevation_change(self) -> Metres:
        return self.elevation_end - self.elevation_start

    @property
    def gradient(self) -> float:
        """Mean slope dz/ds (dimensionless).  Positive is uphill."""
        if self.length <= 0.0:
            return 0.0
        return self.elevation_change / self.length

    @property
    def gradient_percent(self) -> float:
        return self.gradient * 100.0

    @property
    def is_corner(self) -> bool:
        return self.kind is not SegmentKind.STRAIGHT

    @property
    def is_straight(self) -> bool:
        return self.kind is SegmentKind.STRAIGHT

    @property
    def has_drs(self) -> bool:
        return self.drs_zone is not None

    # -- interpolation within the segment ------------------------------------

    def local_fraction(self, distance: Metres) -> float:
        """Position of ``distance`` within the segment, clamped to ``[0, 1]``."""
        if self.length <= 0.0:
            return 0.0
        return clamp((distance - self.distance) / self.length, 0.0, 1.0)

    def curvature_at(self, distance: Metres) -> Curvature:
        """Exact curvature at ``distance`` (linear within the segment)."""
        return lerp(self.curvature_start, self.curvature_end, self.local_fraction(distance))

    def elevation_at(self, distance: Metres) -> Metres:
        """Elevation at ``distance``, m."""
        return lerp(self.elevation_start, self.elevation_end, self.local_fraction(distance))

    def heading_at(self, distance: Metres) -> Radians:
        """Heading at ``distance``, radians.

        Integrating a linear curvature gives a quadratic heading, which is
        exactly the Euler-spiral (clothoid) form.
        """
        s = self.local_fraction(distance) * self.length
        return self.heading + self.curvature_start * s + 0.5 * self.curvature_rate * s * s

    def contains(self, distance: Metres) -> bool:
        """Is ``distance`` inside this segment? (start inclusive, end exclusive)"""
        return self.distance <= distance < self.end_distance

    # -- serialisation -------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Plain-data form, used for export and for the SVG/3D clients."""
        return {
            "index": self.index,
            "distance": self.distance,
            "length": self.length,
            "curvature_start": self.curvature_start,
            "curvature_end": self.curvature_end,
            "curvature": self.curvature,
            "radius": None if math.isinf(self.radius) else self.radius,
            "elevation_start": self.elevation_start,
            "elevation_end": self.elevation_end,
            "gradient": self.gradient,
            "banking": self.banking,
            "surface_grip": self.surface_grip,
            "surface_type": self.surface_type.value,
            "roughness": self.roughness,
            "track_width": self.track_width,
            "sector": self.sector,
            "corner_id": self.corner_id,
            "corner_name": self.corner_name,
            "drs_zone": self.drs_zone,
            "kerb": self.kerb.value,
            "kind": self.kind.value,
            "x": self.x,
            "y": self.y,
            "heading": self.heading,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TrackSegment:
        """Rebuild a segment from :meth:`to_dict` output."""
        return cls(
            index=int(data["index"]),
            distance=float(data["distance"]),
            length=float(data["length"]),
            curvature_start=float(data["curvature_start"]),
            curvature_end=float(data["curvature_end"]),
            elevation_start=float(data["elevation_start"]),
            elevation_end=float(data["elevation_end"]),
            banking=float(data["banking"]),
            surface_grip=float(data["surface_grip"]),
            surface_type=SurfaceType(data["surface_type"]),
            roughness=float(data["roughness"]),
            track_width=float(data["track_width"]),
            sector=int(data["sector"]),
            corner_id=None if data.get("corner_id") is None else int(data["corner_id"]),
            corner_name=data.get("corner_name"),
            drs_zone=None if data.get("drs_zone") is None else int(data["drs_zone"]),
            kerb=KerbType(data["kerb"]),
            kind=SegmentKind(data["kind"]),
            x=float(data["x"]),
            y=float(data["y"]),
            heading=float(data["heading"]),
        )
