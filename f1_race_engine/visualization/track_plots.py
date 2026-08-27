"""matplotlib debug plots for the track model.

Project rule 42: while the physics is being built, the fastest way to find a
bad number is to look at it.  These plots cover everything Phase 1 produces --
curvature, radius, elevation, gradient, banking, width and the plan view.  The
speed profile, braking zones and acceleration zones join them in Phase 3, and
:func:`plot_track_overview` is laid out to take those extra panels.

matplotlib is an **optional** dependency.  The engine core never imports it, so
a headless simulation run has no plotting dependency at all; importing this
module without matplotlib raises a clear error rather than failing obscurely.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..core.units import rad_to_deg
from ..track.curvature import curvature_profile
from ..track.model import Track

if TYPE_CHECKING:  # pragma: no cover
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure

__all__ = [
    "plot_banking",
    "plot_curvature",
    "plot_elevation",
    "plot_map",
    "plot_radius",
    "plot_track_overview",
    "plot_width",
    "save_track_overview",
]

_MISSING = (
    "matplotlib is required for debug plots but is not installed.\n"
    "Install it with:  pip install 'f1-race-engine[viz]'   (or: pip install matplotlib)\n"
    "The engine itself has no plotting dependency; only this module needs it."
)


def _pyplot():
    """Import pyplot lazily, with a useful message when it is missing."""
    try:
        import matplotlib.pyplot as plt
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise ImportError(_MISSING) from exc
    return plt


def _sector_shading(axes: "Axes", track: Track) -> None:
    """Tint the background by timing sector so features are easy to place."""
    colours = ("#0072B2", "#E69F00", "#009E73")
    for index, (start, end) in enumerate(track.sector_ranges()):
        axes.axvspan(start, end, color=colours[index % len(colours)], alpha=0.06)


def _drs_shading(axes: "Axes", track: Track) -> None:
    if track.drs_map is None:
        return
    for zone in track.drs_map:
        axes.axvspan(
            zone.activation_start, zone.activation_end, color="#CC79A7", alpha=0.13
        )


def plot_curvature(track: Track, axes: "Axes | None" = None) -> "Axes":
    """Curvature against distance -- the shape of the lap in one line."""
    plt = _pyplot()
    axes = axes or plt.subplots(figsize=(12, 3))[1]
    profile = curvature_profile(track.segments, samples_per_segment=2)
    _sector_shading(axes, track)
    axes.plot(profile.distance, profile.curvature, linewidth=1.2, color="#0072B2")
    axes.axhline(0.0, color="#666", linewidth=0.7)
    axes.set_ylabel("curvature  [1/m]")
    axes.set_xlabel("distance  [m]")
    axes.set_title(
        f"Curvature -- {track.name}  "
        f"(+ left, - right; min radius {track.min_radius:.0f} m)"
    )
    axes.set_xlim(0, track.length)
    axes.grid(alpha=0.2)
    return axes


def plot_radius(track: Track, axes: "Axes | None" = None, *, cap: float = 1000.0) -> "Axes":
    """Unsigned corner radius against distance, clipped so corners stay legible."""
    plt = _pyplot()
    axes = axes or plt.subplots(figsize=(12, 3))[1]
    distances = [s.mid_distance for s in track.segments]
    radii = [min(s.corner_radius, cap) for s in track.segments]
    _sector_shading(axes, track)
    axes.plot(distances, radii, linewidth=1.2, color="#009E73")
    axes.set_ylabel(f"radius  [m]  (capped at {cap:.0f})")
    axes.set_xlabel("distance  [m]")
    axes.set_title(f"Corner radius -- {track.name}")
    axes.set_xlim(0, track.length)
    axes.set_yscale("log")
    axes.grid(alpha=0.2, which="both")
    return axes


def plot_elevation(track: Track, axes: "Axes | None" = None) -> "Axes":
    """Elevation and gradient against distance."""
    plt = _pyplot()
    axes = axes or plt.subplots(figsize=(12, 3))[1]
    distances = [s.distance for s in track.segments]
    elevations = [s.elevation_start for s in track.segments]
    gradients = [s.gradient_percent for s in track.segments]
    _sector_shading(axes, track)
    axes.fill_between(distances, elevations, min(elevations), alpha=0.25, color="#8a6d3b")
    axes.plot(distances, elevations, linewidth=1.4, color="#8a6d3b")
    axes.set_ylabel("elevation  [m]")
    axes.set_xlabel("distance  [m]")
    axes.set_xlim(0, track.length)
    axes.grid(alpha=0.2)
    twin = axes.twinx()
    twin.plot(distances, gradients, linewidth=0.9, color="#D55E00", alpha=0.75)
    twin.set_ylabel("gradient  [%]", color="#D55E00")
    twin.axhline(0.0, color="#D55E00", linewidth=0.5, alpha=0.4)
    axes.set_title(
        f"Elevation -- {track.name}  "
        f"(range {max(elevations) - min(elevations):.1f} m, "
        f"climb {track.elevation_gain:.1f} m)"
    )
    return axes


def plot_banking(track: Track, axes: "Axes | None" = None) -> "Axes":
    """Banking angle against distance."""
    plt = _pyplot()
    axes = axes or plt.subplots(figsize=(12, 2.4))[1]
    distances = [s.mid_distance for s in track.segments]
    banking = [rad_to_deg(s.banking) for s in track.segments]
    _sector_shading(axes, track)
    axes.plot(distances, banking, linewidth=1.2, color="#CC79A7")
    axes.axhline(0.0, color="#666", linewidth=0.7)
    axes.set_ylabel("banking  [deg]")
    axes.set_xlabel("distance  [m]")
    axes.set_title(f"Banking -- {track.name}  (+ supports a left-hand corner)")
    axes.set_xlim(0, track.length)
    axes.grid(alpha=0.2)
    return axes


def plot_width(track: Track, axes: "Axes | None" = None) -> "Axes":
    """Track width against distance, with DRS zones marked."""
    plt = _pyplot()
    axes = axes or plt.subplots(figsize=(12, 2.4))[1]
    distances = [s.mid_distance for s in track.segments]
    widths = [s.track_width for s in track.segments]
    _sector_shading(axes, track)
    _drs_shading(axes, track)
    axes.plot(distances, widths, linewidth=1.2, color="#56B4E9")
    axes.set_ylabel("width  [m]")
    axes.set_xlabel("distance  [m]")
    axes.set_title(f"Track width -- {track.name}  (shaded: DRS activation zones)")
    axes.set_xlim(0, track.length)
    axes.grid(alpha=0.2)
    return axes


def plot_map(track: Track, axes: "Axes | None" = None, *, colour_by: str = "sector") -> "Axes":
    """Plan view of the circuit, coloured by sector or by corner speed."""
    plt = _pyplot()
    axes = axes or plt.subplots(figsize=(7, 7))[1]
    centerline = track.centerline(samples_per_segment=2)
    xs = [p.x for p in centerline.points]
    ys = [p.y for p in centerline.points]

    if colour_by == "sector" and track.sector_boundaries:
        colours = ("#0072B2", "#E69F00", "#009E73")
        start = 0
        current = track.sector_of(centerline.points[0].distance)
        for i, point in enumerate(centerline.points[1:], start=1):
            sector = track.sector_of(point.distance % track.length)
            if sector != current or i == len(centerline.points) - 1:
                axes.plot(
                    xs[start : i + 1],
                    ys[start : i + 1],
                    linewidth=2.6,
                    color=colours[(current - 1) % len(colours)],
                    label=f"S{current}" if start == 0 or current == 1 else None,
                    solid_capstyle="round",
                )
                start = i
                current = sector
    else:
        axes.plot(xs, ys, linewidth=2.6, color="#0072B2", solid_capstyle="round")

    axes.plot(xs[0], ys[0], "o", color="#f0f0f0", markeredgecolor="#333", markersize=8)
    for corner in sorted(track.corners.values(), key=lambda c: float(c["start_distance"])):
        mid = float(corner["start_distance"]) + 0.5 * float(corner["length"])
        index = min(range(len(centerline.points)),
                    key=lambda i: abs(centerline.points[i].distance - mid))
        axes.annotate(
            str(corner["corner_id"]),
            (xs[index], ys[index]),
            textcoords="offset points",
            xytext=(6, 6),
            fontsize=8,
            color="#444",
        )
    axes.set_aspect("equal", adjustable="datalim")
    axes.set_title(
        f"{track.name}  --  {track.length:.0f} m, {track.corner_count} corners, "
        f"closure {centerline.closure_error:.2f} m"
    )
    axes.set_xlabel("x  [m]")
    axes.set_ylabel("y  [m]")
    axes.grid(alpha=0.2)
    return axes


def plot_track_overview(track: Track) -> "Figure":
    """One figure with every Phase 1 diagnostic.

    Later phases add the speed profile, braking zones and acceleration zones as
    further rows of the same grid.
    """
    plt = _pyplot()
    figure = plt.figure(figsize=(16, 13), layout="constrained")
    grid = figure.add_gridspec(5, 2, width_ratios=(1.0, 1.35))

    plot_map(track, figure.add_subplot(grid[0:3, 0]))
    plot_curvature(track, figure.add_subplot(grid[0, 1]))
    plot_radius(track, figure.add_subplot(grid[1, 1]))
    plot_elevation(track, figure.add_subplot(grid[2, 1]))
    plot_banking(track, figure.add_subplot(grid[3, :]))
    plot_width(track, figure.add_subplot(grid[4, :]))

    figure.suptitle(
        f"Track diagnostics -- {track.name}  "
        f"({len(track.segments)} segments, "
        f"{track.resolution_stats()['min_length']:.1f}-"
        f"{track.resolution_stats()['max_length']:.1f} m resolution)",
        fontsize=14,
    )
    return figure


def save_track_overview(track: Track, path: str, *, dpi: int = 110) -> str:
    """Render :func:`plot_track_overview` to an image file."""
    plt = _pyplot()
    figure = plot_track_overview(track)
    figure.savefig(path, dpi=dpi)
    plt.close(figure)
    return path
