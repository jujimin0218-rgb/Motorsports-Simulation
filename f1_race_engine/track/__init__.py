"""The track model: distance -> track state.

The circuit is the foundation the rest of the engine stands on (project rule
5).  A track is built from a :class:`~f1_race_engine.track.definitions.
TrackDefinition` by the :class:`~f1_race_engine.track.builder.TrackBuilder`,
validated, and then queried by distance.
"""

from __future__ import annotations

from .banking import BankingProfile
from .builder import LayoutSpan, TrackBuilder, build_track
from .curvature import (
    CornerSpeedClass,
    CurvatureProfile,
    classify_corner,
    curvature_profile,
    nominal_corner_speed,
)
from .definitions import (
    BankingDefinition,
    CornerDefinition,
    CornerDirection,
    DrsDefinition,
    ElevationDefinition,
    KerbDefinition,
    KerbRegion,
    LayoutElement,
    SectorDefinition,
    StraightDefinition,
    SurfaceDefinition,
    SurfaceRegionDefinition,
    TrackDefaults,
    TrackDefinition,
    WidthDefinition,
)
from .drs import DrsMap, DrsZone
from .elevation import ElevationProfile
from .geometry import Centerline, PlanPoint, centerline_from_segments
from .io import (
    builtin_track_names,
    definition_from_dict,
    definition_to_dict,
    load_builtin_definition,
    load_track,
    load_track_definition,
    save_track_definition,
    track_to_json,
)
from .model import Track, TrackState
from .report import format_track_report, track_report
from .segment import KerbType, SegmentKind, SurfaceType, TrackSegment
from .surface import SurfaceCondition, SurfaceMap, SurfaceRegion, TrackConditions
from .validation import (
    Severity,
    TRACK_CHECKS,
    ValidationIssue,
    ValidationReport,
    validate_track,
)

__all__ = [
    "BankingDefinition",
    "BankingProfile",
    "Centerline",
    "CornerDefinition",
    "CornerDirection",
    "CornerSpeedClass",
    "CurvatureProfile",
    "DrsDefinition",
    "DrsMap",
    "DrsZone",
    "ElevationDefinition",
    "ElevationProfile",
    "KerbDefinition",
    "KerbRegion",
    "KerbType",
    "LayoutElement",
    "LayoutSpan",
    "PlanPoint",
    "SectorDefinition",
    "SegmentKind",
    "Severity",
    "StraightDefinition",
    "SurfaceCondition",
    "SurfaceDefinition",
    "SurfaceMap",
    "SurfaceRegion",
    "SurfaceRegionDefinition",
    "SurfaceType",
    "TRACK_CHECKS",
    "Track",
    "TrackBuilder",
    "TrackConditions",
    "TrackDefaults",
    "TrackDefinition",
    "TrackSegment",
    "TrackState",
    "ValidationIssue",
    "ValidationReport",
    "WidthDefinition",
    "build_track",
    "builtin_track_names",
    "centerline_from_segments",
    "classify_corner",
    "curvature_profile",
    "definition_from_dict",
    "definition_to_dict",
    "format_track_report",
    "load_builtin_definition",
    "load_track",
    "load_track_definition",
    "nominal_corner_speed",
    "save_track_definition",
    "track_report",
    "track_to_json",
    "validate_track",
]
