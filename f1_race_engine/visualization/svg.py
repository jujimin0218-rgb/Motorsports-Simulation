"""SVG export of a track map -- no dependencies.

Project rule 42 asks for debug visualisation, and rule 44 asks that the engine
stay independent of any UI.  This module satisfies both without pulling in
matplotlib: it turns a built track into an SVG string using nothing but the
standard library.

The same output is what a web front end wants for a circuit map, so this
doubles as the bridge to the eventual browser client -- the engine produces the
geometry, the client decides how to present it.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from ..track.model import Track

__all__ = ["track_to_svg", "centerline_path", "SECTOR_COLOURS"]

#: Colour-blind-safe qualitative colours for the three timing sectors.
SECTOR_COLOURS: tuple[str, ...] = ("#0072B2", "#E69F00", "#009E73")
_DRS_COLOUR = "#CC79A7"


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def centerline_path(points: Sequence[tuple[float, float]], *, close: bool = True) -> str:
    """Turn projected ``(x, y)`` points into an SVG path ``d`` attribute."""
    if not points:
        return ""
    parts = [f"M {points[0][0]:.2f} {points[0][1]:.2f}"]
    parts.extend(f"L {x:.2f} {y:.2f}" for x, y in points[1:])
    if close:
        parts.append("Z")
    return " ".join(parts)


def track_to_svg(
    track: Track,
    *,
    width: float = 900.0,
    height: float = 620.0,
    padding: float = 40.0,
    samples_per_segment: int = 1,
    colour_by_sector: bool = True,
    show_drs: bool = True,
    show_corners: bool = True,
    show_start: bool = True,
    stroke_width: float = 6.0,
    background: str | None = "#11141a",
    track_colour: str = "#8a93a5",
) -> str:
    """Render ``track`` as a standalone SVG document.

    The track is drawn from the plan-view centreline, coloured by timing sector
    when asked, with DRS activation zones overlaid and corners labelled.
    """
    centerline = track.centerline(samples_per_segment=samples_per_segment)
    if len(centerline) < 2:
        raise ValueError("track has too few points to draw")
    projected = centerline.normalised(width=width, height=height, padding=padding)
    distances = [point.distance for point in centerline.points]

    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.0f} {height:.0f}" '
        f'width="{width:.0f}" height="{height:.0f}" '
        f'role="img" aria-label="{_escape(track.name)} circuit map">',
        f"<title>{_escape(track.name)}</title>",
    ]
    if background is not None:
        parts.append(f'<rect width="{width:.0f}" height="{height:.0f}" fill="{background}"/>')

    # -- the track itself ----------------------------------------------------
    if colour_by_sector and track.sector_boundaries:
        runs: list[tuple[int, list[tuple[float, float]]]] = []
        current_sector = track.sector_of(distances[0])
        run: list[tuple[float, float]] = [projected[0]]
        for point, distance in zip(projected[1:], distances[1:]):
            sector = track.sector_of(distance % track.length)
            run.append(point)
            if sector != current_sector:
                runs.append((current_sector, run))
                run = [point]
                current_sector = sector
        runs.append((current_sector, run))
        for sector, points in runs:
            colour = SECTOR_COLOURS[(sector - 1) % len(SECTOR_COLOURS)]
            parts.append(
                f'<path d="{centerline_path(points, close=False)}" fill="none" '
                f'stroke="{colour}" stroke-width="{stroke_width}" '
                f'stroke-linecap="round" stroke-linejoin="round">'
                f"<title>Sector {sector}</title></path>"
            )
    else:
        parts.append(
            f'<path d="{centerline_path(projected)}" fill="none" '
            f'stroke="{track_colour}" stroke-width="{stroke_width}" '
            f'stroke-linecap="round" stroke-linejoin="round"/>'
        )

    # -- DRS activation zones ------------------------------------------------
    if show_drs and track.drs_map is not None:
        for zone in track.drs_map:
            points = [
                projected[i]
                for i, distance in enumerate(distances)
                if zone.activation_start <= distance % track.length < zone.activation_end
            ]
            if len(points) < 2:
                continue
            parts.append(
                f'<path d="{centerline_path(points, close=False)}" fill="none" '
                f'stroke="{_DRS_COLOUR}" stroke-width="{stroke_width * 0.45:.2f}" '
                f'stroke-linecap="round" stroke-dasharray="10 6">'
                f"<title>DRS zone {zone.index}"
                f"{': ' + _escape(zone.name) if zone.name else ''}</title></path>"
            )

    # -- corner markers ------------------------------------------------------
    if show_corners:
        for corner in sorted(
            track.corners.values(), key=lambda c: float(c["start_distance"])
        ):
            distance = float(corner["start_distance"]) + 0.5 * float(corner["length"])
            index = min(
                range(len(distances)),
                key=lambda i: abs(distances[i] - distance),
            )
            cx, cy = projected[index]
            parts.append(
                f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="3.2" fill="#f5f7fa" '
                f'fill-opacity="0.85"><title>'
                f'{_escape(str(corner["name"] or corner["corner_id"]))} '
                f'(R {float(corner["min_radius"]):.0f} m)</title></circle>'
            )
            parts.append(
                f'<text x="{cx + 8:.1f}" y="{cy - 6:.1f}" font-size="11" '
                f'font-family="system-ui, sans-serif" fill="#c8cfdb">'
                f'{corner["corner_id"]}</text>'
            )

    # -- start/finish line ---------------------------------------------------
    if show_start:
        sx, sy = projected[0]
        heading = centerline.points[0].heading
        normal = (-math.sin(heading), math.cos(heading))
        span = stroke_width * 1.6
        # SVG y grows downward, so flip the normal's y component.
        x1, y1 = sx - normal[0] * span, sy + normal[1] * span
        x2, y2 = sx + normal[0] * span, sy - normal[1] * span
        parts.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="#f5f7fa" stroke-width="3"><title>Start/finish</title></line>'
        )

    # -- caption -------------------------------------------------------------
    parts.append(
        f'<text x="{padding:.0f}" y="{height - padding * 0.5:.0f}" font-size="15" '
        f'font-family="system-ui, sans-serif" fill="#e6eaf2">'
        f"{_escape(track.name)}</text>"
    )
    parts.append(
        f'<text x="{padding:.0f}" y="{height - padding * 0.5 + 17:.0f}" font-size="11" '
        f'font-family="system-ui, sans-serif" fill="#9aa4b5">'
        f"{track.length:.0f} m &#183; {track.corner_count} corners &#183; "
        f"{'clockwise' if track.is_clockwise else 'anticlockwise'}</text>"
    )
    parts.append("</svg>")
    return "\n".join(parts)
