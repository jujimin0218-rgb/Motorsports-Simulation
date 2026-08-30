"""The shape of a circuit, for drawing.

Project rule 11 asks for the physics coordinates and the drawing coordinates to
be kept apart, and they are: the race engine's track model is a **distance**
model -- curvature, camber, elevation and grip as functions of how far round the
lap you are -- and the ``x``/``y`` on each segment is a projection of that,
carried for exactly this purpose.  Nothing here feeds back into the simulation.

What comes out is a plan view in metres with the origin at the start line.  The
client scales it to a viewBox; it is not given pixels, because how big the
drawing is is the drawing's business.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from f1_race_engine.race.pitlane import PitLane
from f1_race_engine.track.model import Track

__all__ = ["TrackGeometry", "build_geometry"]

#: How finely the centreline is sent.  The engine's own resolution is finer
#: than a screen can show -- a lap is eight hundred segments and a drawing is a
#: few hundred pixels across -- so points closer together than this are dropped.
#: Corners keep every point they have regardless; a decimated hairpin looks
#: like a chicane.
MIN_SPACING_M = 12.0
CORNER_SPACING_M = 4.0


@dataclass(frozen=True, slots=True)
class TrackGeometry:
    """A circuit as a plan view, in metres."""

    track: str
    name: str
    length: float
    points: tuple[tuple[float, float, float], ...]
    """``(distance, x, y)`` around the lap, start line first."""

    bounds: tuple[float, float, float, float]
    """``(min x, min y, max x, max y)``."""

    sectors: tuple[float, ...]
    """Distances at which a sector ends."""

    drs_zones: tuple[tuple[float, float], ...]
    corners: tuple[dict[str, Any], ...]
    pit_entry: float
    pit_exit: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "track": self.track,
            "name": self.name,
            "length": round(self.length, 2),
            "points": [
                [round(d, 1), round(x, 2), round(y, 2)] for d, x, y in self.points
            ],
            "bounds": [round(value, 2) for value in self.bounds],
            "sectors": [round(value, 1) for value in self.sectors],
            "drs_zones": [[round(a, 1), round(b, 1)] for a, b in self.drs_zones],
            "corners": list(self.corners),
            "pit_entry": round(self.pit_entry, 1),
            "pit_exit": round(self.pit_exit, 1),
        }


def _drs_spans(track: Track) -> list[tuple[float, float]]:
    """The DRS zones as ``(start, end)`` distances.

    Read off the segments rather than the DRS map so that a zone which wraps
    the start line comes out as the two spans it is drawn as, which is what a
    plan view needs.
    """
    spans: list[tuple[float, float]] = []
    start: float | None = None
    for segment in track.segments:
        inside = segment.drs_zone is not None
        if inside and start is None:
            start = segment.distance
        elif not inside and start is not None:
            spans.append((start, segment.distance))
            start = None
    if start is not None:
        spans.append((start, track.length))
    return spans


def _corners(track: Track) -> list[dict[str, Any]]:
    """One entry per corner, at the point of tightest curvature.

    The label goes where the corner actually is rather than where it starts,
    because a long corner labelled at its entry points at a straight.
    """
    found: dict[int, dict[str, Any]] = {}
    for segment in track.segments:
        if segment.corner_id is None:
            continue
        curvature = abs(segment.curvature_start)
        entry = found.get(segment.corner_id)
        if entry is None or curvature > entry["_curvature"]:
            found[segment.corner_id] = {
                "id": segment.corner_id,
                "name": segment.corner_name or f"Turn {segment.corner_id}",
                "distance": round(segment.distance, 1),
                "x": round(segment.x, 2),
                "y": round(segment.y, 2),
                "radius": round(1.0 / curvature, 1) if curvature > 1e-9 else None,
                "_curvature": curvature,
            }
    corners = []
    for entry in sorted(found.values(), key=lambda item: item["distance"]):
        entry.pop("_curvature")
        corners.append(entry)
    return corners


def build_geometry(track: Track) -> TrackGeometry:
    """Project a circuit into a plan view."""
    corner_distances = {
        segment.distance for segment in track.segments if segment.corner_id is not None
    }

    points: list[tuple[float, float, float]] = []
    last: tuple[float, float] | None = None
    for segment in track.segments:
        spacing = (
            CORNER_SPACING_M if segment.distance in corner_distances else MIN_SPACING_M
        )
        if last is not None:
            moved = math.hypot(segment.x - last[0], segment.y - last[1])
            if moved < spacing:
                continue
        points.append((segment.distance, segment.x, segment.y))
        last = (segment.x, segment.y)

    # A lap is a loop, so the drawing closes back on the start line.
    first = track.segments[0]
    points.append((track.length, first.x, first.y))

    xs = [x for _, x, _ in points]
    ys = [y for _, _, y in points]
    lane = PitLane.for_track(track.length)

    return TrackGeometry(
        track=track.name.lower().replace(" ", "_"),
        name=track.name,
        length=track.length,
        points=tuple(points),
        bounds=(min(xs), min(ys), max(xs), max(ys)),
        sectors=tuple(track.sector_boundaries),
        drs_zones=tuple(_drs_spans(track)),
        corners=tuple(_corners(track)),
        pit_entry=lane.entry_distance,
        pit_exit=lane.exit_distance,
    )
