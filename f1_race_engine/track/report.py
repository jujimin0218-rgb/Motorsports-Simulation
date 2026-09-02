"""Track characteristics report.

Project rule 41 asks for benchmark output at every phase.  Phase 1 has no
vehicle yet, so what can be benchmarked is the circuit itself: its length, its
corner mix, how much of the lap is spent turning, how well the geometry closes,
and how finely it had to be sampled.

The report is a plain dict so the same numbers can go to a build log, a JSON
export, or the track-information panel of a future web UI.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any

from ..core.units import ms_to_kph, rad_to_deg
from .curvature import CornerSpeedClass
from .model import Track

__all__ = ["format_track_report", "track_report"]


def track_report(track: Track) -> dict[str, Any]:
    """Summarise the geometry and character of ``track``."""
    segments = track.segments
    corners = track.corners
    centerline = track.centerline()

    corner_length = math.fsum(s.length for s in segments if s.is_corner)
    straight_length = track.length - corner_length

    speed_classes = Counter(
        str(entry["speed_class"]) for entry in corners.values()
    )
    directions = Counter(str(entry["direction"]) for entry in corners.values())

    straights = track.straight_sections(min_length=0.0)
    straight_lengths = sorted((end - start for start, end in straights), reverse=True)

    elevations = [s.elevation_start for s in segments]
    gradients = [s.gradient for s in segments]
    bankings = [rad_to_deg(s.banking) for s in segments]
    widths = [s.track_width for s in segments]

    return {
        "name": track.name,
        "country": track.country,
        "length": track.length,
        "segment_count": len(segments),
        "corner_count": track.corner_count,
        "direction": "clockwise" if track.is_clockwise else "anticlockwise",
        "geometry": {
            "total_turning_deg": rad_to_deg(track.total_heading_change),
            "full_turns": track.turn_count,
            "closure_error": centerline.closure_error,
            "closure_error_fraction": centerline.closure_error_fraction,
            "bounding_box": list(centerline.extent),
            "min_radius": None if math.isinf(track.min_radius) else track.min_radius,
        },
        "composition": {
            "corner_length": corner_length,
            "straight_length": straight_length,
            "corner_fraction": corner_length / track.length,
            "straight_fraction": straight_length / track.length,
            "longest_straight": track.longest_straight,
            "straight_lengths": straight_lengths[:5],
        },
        "corners": {
            "by_speed_class": {
                cls.value: speed_classes.get(cls.value, 0)
                for cls in CornerSpeedClass
                if cls is not CornerSpeedClass.STRAIGHT
            },
            "by_direction": {"left": directions.get("left", 0), "right": directions.get("right", 0)},
            "detail": [
                {
                    "corner_id": entry["corner_id"],
                    "name": entry["name"],
                    "start_distance": entry["start_distance"],
                    "length": entry["length"],
                    "min_radius": entry["min_radius"],
                    "turn_angle_deg": rad_to_deg(float(entry["turn_angle"])),
                    "direction": entry["direction"],
                    "speed_class": entry["speed_class"],
                    "nominal_speed_kph": ms_to_kph(float(entry["nominal_speed"])),
                }
                for entry in sorted(
                    corners.values(), key=lambda e: float(e["start_distance"])
                )
            ],
        },
        "sectors": {
            "count": track.sector_count,
            "boundaries": list(track.sector_boundaries),
            "lengths": track.sector_lengths(),
        },
        "elevation": {
            "min": min(elevations),
            "max": max(elevations),
            "range": max(elevations) - min(elevations),
            "total_climb": track.elevation_gain,
            "max_gradient_percent": max(gradients) * 100.0,
            "min_gradient_percent": min(gradients) * 100.0,
        },
        "banking": {
            "max_deg": max(bankings),
            "min_deg": min(bankings),
        },
        "width": {
            "min": min(widths),
            "max": max(widths),
            "mean": math.fsum(widths) / len(widths),
        },
        "drs": {
            "zone_count": 0 if track.drs_map is None else len(track.drs_map),
            "coverage": 0.0 if track.drs_map is None else track.drs_map.coverage,
            "zones": [] if track.drs_map is None else track.drs_map.to_dict(),
        },
        "resolution": track.resolution_stats(),
        "metadata": dict(track.metadata),
    }


def _bar(value: float, total: float, width: int = 24) -> str:
    if total <= 0.0:
        return " " * width
    filled = int(round(width * value / total))
    return "#" * filled + "." * (width - filled)


def format_track_report(report: dict[str, Any]) -> str:
    """Render :func:`track_report` output as readable text."""
    lines: list[str] = []
    geometry = report["geometry"]
    composition = report["composition"]

    lines.append("=" * 72)
    country = f" ({report['country']})" if report.get("country") else ""
    lines.append(f"TRACK REPORT  --  {report['name']}{country}")
    lines.append("=" * 72)
    lines.append(
        f"  length              {report['length']:>10.1f} m"
        f"      ({report['length'] / 1000.0:.3f} km)"
    )
    lines.append(f"  corners             {report['corner_count']:>10d}")
    lines.append(f"  direction           {report['direction']:>10}")
    lines.append(f"  segments            {report['segment_count']:>10d}")
    lines.append("")
    lines.append("  GEOMETRY")
    lines.append(f"    total turning     {geometry['total_turning_deg']:>10.3f} deg"
                 f"   ({geometry['full_turns']:+.4f} full turns)")
    lines.append(
        f"    closure error     {geometry['closure_error']:>10.2f} m"
        f"     ({geometry['closure_error_fraction']:.3%} of lap)"
    )
    box = geometry["bounding_box"]
    lines.append(f"    bounding box      {box[0]:>10.0f} x {box[1]:.0f} m")
    min_radius = geometry["min_radius"]
    lines.append(
        f"    tightest radius   {min_radius:>10.1f} m"
        if min_radius is not None
        else "    tightest radius        (none)"
    )
    lines.append("")
    lines.append("  COMPOSITION")
    lines.append(
        f"    straights         {composition['straight_length']:>10.1f} m  "
        f"{_bar(composition['straight_length'], report['length'])} "
        f"{composition['straight_fraction']:.1%}"
    )
    lines.append(
        f"    corners           {composition['corner_length']:>10.1f} m  "
        f"{_bar(composition['corner_length'], report['length'])} "
        f"{composition['corner_fraction']:.1%}"
    )
    lines.append(f"    longest straight  {composition['longest_straight']:>10.1f} m")
    lines.append("")
    lines.append("  CORNER MIX")
    for name, count in report["corners"]["by_speed_class"].items():
        lines.append(f"    {name:<17} {count:>10d}")
    directions = report["corners"]["by_direction"]
    lines.append(f"    left / right      {directions['left']:>7d} / {directions['right']}")
    lines.append("")
    lines.append("  CORNERS")
    lines.append(
        f"    {'id':>3}  {'name':<22}{'at m':>8}{'R m':>8}{'angle':>8}"
        f"{'dir':>7}{'~km/h':>8}"
    )
    for corner in report["corners"]["detail"]:
        lines.append(
            f"    {str(corner['corner_id']):>3}  {str(corner['name'] or ''):<22}"
            f"{corner['start_distance']:>8.0f}{corner['min_radius']:>8.0f}"
            f"{corner['turn_angle_deg']:>8.0f}{corner['direction']:>7}"
            f"{corner['nominal_speed_kph']:>8.0f}"
        )
    lines.append("")
    sectors = report["sectors"]
    lines.append("  SECTORS")
    for index, length in enumerate(sectors["lengths"], start=1):
        lines.append(f"    S{index}                {length:>10.1f} m")
    lines.append("")
    elevation = report["elevation"]
    lines.append("  ELEVATION")
    lines.append(f"    range             {elevation['range']:>10.1f} m")
    lines.append(f"    total climb       {elevation['total_climb']:>10.1f} m")
    lines.append(
        f"    gradient          {elevation['min_gradient_percent']:>10.1f}%"
        f" to {elevation['max_gradient_percent']:+.1f}%"
    )
    lines.append("")
    drs = report["drs"]
    lines.append("  DRS")
    lines.append(f"    zones             {drs['zone_count']:>10d}")
    lines.append(f"    coverage          {drs['coverage']:>10.1%} of the lap")
    for zone in drs["zones"]:
        lines.append(
            f"      zone {zone['index']}  detect {zone['detection_distance']:.0f} m, "
            f"active {zone['activation_start']:.0f}-{zone['activation_end']:.0f} m "
            f"({zone['length']:.0f} m)"
        )
    lines.append("")
    resolution = report["resolution"]
    lines.append("  RESOLUTION")
    lines.append(
        f"    segment length    {resolution['min_length']:>10.2f} m min, "
        f"{resolution['mean_length']:.2f} m mean, {resolution['max_length']:.2f} m max"
    )
    lines.append("=" * 72)
    return "\n".join(lines)
