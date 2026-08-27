"""matplotlib diagnostics for the speed profile and the lap (project rule 42).

Rule 42 asks specifically for the speed profile, the braking zones and the
acceleration zones, and these are the plots where a lap-time bug becomes
obvious in a second: an apex that is not on the cornering limit, a braking zone
that starts too late, a straight where the car stops accelerating early.

* **Speed profile** -- speed against distance with the cornering limit drawn
  over it.  Where the two touch is an apex; where they part, the car is limited
  by braking or by power instead.
* **Zones** -- braking and acceleration runs shaded, so the rhythm of the lap
  is visible at a glance.
* **Speed map** -- the circuit's plan view coloured by speed, which is the
  clearest way to see whether a corner is being taken at a sensible pace.
* **g-trace** -- lateral and longitudinal acceleration against distance, the
  trace a real engineer reads.

matplotlib is an optional extra; the engine core never imports it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..core.units import ms_to_kph
from ..physics.lap_time import LapTimeResult
from ..track.model import Track

if TYPE_CHECKING:  # pragma: no cover
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure

__all__ = [
    "plot_g_trace",
    "plot_lap_overview",
    "plot_speed_map",
    "plot_speed_profile",
    "save_lap_overview",
]

_BRAKING_COLOUR = "#D55E00"
_ACCELERATION_COLOUR = "#009E73"
_LIMIT_COLOUR = "#CC79A7"


def _pyplot():
    try:
        import matplotlib.pyplot as plt
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise ImportError(
            "matplotlib is required for debug plots but is not installed.\n"
            "Install it with:  pip install 'f1-race-engine[viz]'"
        ) from exc
    return plt


def _closed(values: tuple[float, ...]) -> list[float]:
    """Repeat the first value at the end so a lap plot joins up."""
    return list(values) + [values[0]]


def plot_speed_profile(
    result: LapTimeResult, axes: "Axes | None" = None, *, show_zones: bool = True
) -> "Axes":
    """Speed against distance, with the cornering limit and the zones."""
    plt = _pyplot()
    axes = axes or plt.subplots(figsize=(13, 4))[1]
    profile = result.profile

    distances = list(profile.distance) + [profile.lap_length]
    speeds = [ms_to_kph(v) for v in _closed(profile.speed)]
    ceiling = max(speeds) * 1.12

    # Draw the cornering limit only where it actually binds.  Over most of a
    # lap the tyres are nowhere near the constraint and the "limit" is just the
    # solver's ceiling, which would otherwise paint a meaningless line along
    # the top of the plot.
    limits = [
        ms_to_kph(v) if ms_to_kph(v) <= ceiling else float("nan")
        for v in _closed(profile.corner_limit)
    ]

    if show_zones:
        for zone in result.braking_zones:
            axes.axvspan(
                zone.start_distance, zone.end_distance,
                color=_BRAKING_COLOUR, alpha=0.16,
            )
        for zone in result.acceleration_zones:
            axes.axvspan(
                zone.start_distance,
                min(zone.end_distance, profile.lap_length),
                color=_ACCELERATION_COLOUR, alpha=0.09,
            )

    axes.plot(
        distances, limits,
        color=_LIMIT_COLOUR, linewidth=1.4, linestyle="--",
        label="cornering limit (where it binds)",
    )
    axes.plot(distances, speeds, color="#0072B2", linewidth=1.8, label="speed")
    axes.set_xlim(0, profile.lap_length)
    axes.set_ylim(0, ceiling)
    axes.set_xlabel("distance  [m]")
    axes.set_ylabel("speed  [km/h]")
    axes.set_title(
        f"Speed profile -- {result.vehicle_name} at {result.track_name}   "
        f"{result.formatted}   (shaded: braking / accelerating)"
    )
    axes.legend(fontsize=8, loc="lower right")
    axes.grid(alpha=0.2)
    return axes


def plot_g_trace(result: LapTimeResult, axes: "Axes | None" = None) -> "Axes":
    """Lateral and longitudinal acceleration against distance."""
    plt = _pyplot()
    axes = axes or plt.subplots(figsize=(13, 3))[1]
    profile = result.profile
    count = len(profile)

    distances = list(profile.distance) + [profile.lap_length]
    lateral = [profile.lateral_acceleration(i) / 9.80665 for i in range(count)]
    longitudinal = [profile.longitudinal_acceleration(i) / 9.80665 for i in range(count)]

    axes.plot(distances, lateral + [lateral[0]], color="#0072B2",
              linewidth=1.2, label="lateral")
    axes.plot(distances, longitudinal + [longitudinal[0]], color="#E69F00",
              linewidth=1.2, label="longitudinal (+ accelerating)")
    axes.axhline(0.0, color="#666", linewidth=0.7)
    axes.set_xlim(0, profile.lap_length)
    axes.set_xlabel("distance  [m]")
    axes.set_ylabel("acceleration  [g]")
    axes.set_title(
        f"g trace -- peak {result.max_lateral_g:.2f} g lateral, "
        f"{result.max_braking_g:.2f} g braking, "
        f"{result.max_acceleration_g:.2f} g acceleration"
    )
    axes.legend(fontsize=8)
    axes.grid(alpha=0.2)
    return axes


def plot_speed_map(
    result: LapTimeResult, track: Track, axes: "Axes | None" = None
) -> "Axes":
    """The circuit's plan view, coloured by speed."""
    plt = _pyplot()
    axes = axes or plt.subplots(figsize=(7, 7))[1]
    centerline = track.centerline()
    points = centerline.points

    speeds = [ms_to_kph(result.profile.speed_at(point.distance)) for point in points]
    lowest, highest = min(speeds), max(speeds)
    span = max(highest - lowest, 1e-6)
    colourmap = plt.get_cmap("viridis")

    for index in range(len(points) - 1):
        a, b = points[index], points[index + 1]
        axes.plot(
            [a.x, b.x], [a.y, b.y],
            color=colourmap((speeds[index] - lowest) / span),
            linewidth=3.0, solid_capstyle="round",
        )

    for zone in result.braking_zones:
        marker = min(
            points, key=lambda p: abs(p.distance - zone.start_distance % track.length)
        )
        axes.plot(marker.x, marker.y, "v", color=_BRAKING_COLOUR, markersize=7)

    axes.plot(points[0].x, points[0].y, "o", color="#f0f0f0",
              markeredgecolor="#333", markersize=8)
    axes.set_aspect("equal", adjustable="datalim")
    axes.set_title(
        f"{track.name} -- speed map  ({lowest:.0f}-{highest:.0f} km/h; "
        f"triangles are braking points)"
    )
    axes.set_xlabel("x  [m]")
    axes.set_ylabel("y  [m]")
    axes.grid(alpha=0.2)

    mappable = plt.cm.ScalarMappable(
        cmap=colourmap, norm=plt.Normalize(vmin=lowest, vmax=highest)
    )
    axes.figure.colorbar(mappable, ax=axes, label="speed [km/h]", fraction=0.045)
    return axes


def plot_lap_overview(result: LapTimeResult, track: Track) -> "Figure":
    """One figure with every Phase 3 diagnostic."""
    plt = _pyplot()
    figure = plt.figure(figsize=(17, 10), layout="constrained")
    grid = figure.add_gridspec(2, 2, width_ratios=(1.0, 1.5))

    plot_speed_map(result, track, figure.add_subplot(grid[:, 0]))
    plot_speed_profile(result, figure.add_subplot(grid[0, 1]))
    plot_g_trace(result, figure.add_subplot(grid[1, 1]))

    sectors = "  ".join(f"S{i}: {t:.3f}" for i, t in enumerate(result.sector_times, 1))
    figure.suptitle(
        f"Lap diagnostics -- {result.vehicle_name} at {result.track_name}   "
        f"{result.formatted}   ({sectors})",
        fontsize=14,
    )
    return figure


def save_lap_overview(
    result: LapTimeResult, track: Track, path: str, *, dpi: int = 110
) -> str:
    """Render :func:`plot_lap_overview` to an image file."""
    plt = _pyplot()
    figure = plot_lap_overview(result, track)
    figure.savefig(path, dpi=dpi)
    plt.close(figure)
    return path
