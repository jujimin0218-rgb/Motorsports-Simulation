"""matplotlib diagnostics for the vehicle and the physics (project rule 42).

The track plots answered "is the circuit right?".  These answer "is the car
right?" -- and they are the plots to reach for first when a lap time comes out
wrong in Phase 4, because almost every such bug is visible here as a kink, a
crossover in the wrong place, or a curve with the wrong shape.

* **Force balance** -- drive, drag and net force against speed.  The corner
  where the drive curve stops being flat is the torque/power crossover; where
  the net curve reaches zero is the top speed.
* **g-g diagram** -- the friction circle the car actually has at several
  speeds.  Phase 3's speed profile lives inside these envelopes.
* **Performance envelope** -- lateral, braking and acceleration against speed,
  which is where a wrong tyre or aero number shows up immediately.
* **Cornering** -- speed against radius, with the flat-out region marked.

matplotlib is an optional extra; the engine core never imports it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..core.units import kph_to_ms, ms_to_kph
from ..environment.conditions import AmbientConditions
from ..physics.benchmark import benchmark_vehicle
from ..physics.lateral import corner_speed_limit, lateral_capability
from ..physics.longitudinal import longitudinal_forces, max_deceleration
from ..vehicle.model import Vehicle

if TYPE_CHECKING:  # pragma: no cover
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure

__all__ = [
    "plot_cornering",
    "plot_force_balance",
    "plot_gg_diagram",
    "plot_performance_envelope",
    "plot_vehicle_overview",
    "save_vehicle_overview",
]

_MISSING = (
    "matplotlib is required for debug plots but is not installed.\n"
    "Install it with:  pip install 'f1-race-engine[viz]'"
)


def _pyplot():
    try:
        import matplotlib.pyplot as plt
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise ImportError(_MISSING) from exc
    return plt


def _speeds(top_speed: float, count: int = 120) -> list[float]:
    return [1.0 + (top_speed - 1.0) * i / (count - 1) for i in range(count)]


def plot_force_balance(
    vehicle: Vehicle, ambient: AmbientConditions | None = None, axes: "Axes | None" = None
) -> "Axes":
    """Drive, resistance and net force against speed."""
    plt = _pyplot()
    axes = axes or plt.subplots(figsize=(9, 4))[1]
    conditions = ambient or AmbientConditions()
    rho = conditions.air_density
    mass = vehicle.total_mass()
    top = benchmark_vehicle(vehicle, conditions, corner_radii=(), speed_targets=(),
                            braking_speeds=()).top_speed
    speeds = _speeds(top * 1.05)

    drive, drag, net = [], [], []
    for speed in speeds:
        forces = longitudinal_forces(vehicle, speed, rho, mass=mass, throttle=1.0)
        drive.append(forces.drive)
        drag.append(forces.drag + forces.rolling_resistance)
        net.append(forces.net)

    kph = [ms_to_kph(s) for s in speeds]
    axes.plot(kph, drive, label="drive (powertrain and traction)", color="#0072B2")
    axes.plot(kph, drag, label="drag + rolling resistance", color="#D55E00")
    axes.plot(kph, net, label="net", color="#009E73", linewidth=2)
    axes.axhline(0.0, color="#666", linewidth=0.8)
    axes.axvline(
        ms_to_kph(vehicle.power_unit.torque_limit_speed),
        color="#999", linestyle=":", linewidth=1,
        label="torque / power crossover",
    )
    axes.axvline(ms_to_kph(top), color="#333", linestyle="--", linewidth=1,
                 label=f"top speed {ms_to_kph(top):.0f} km/h")
    axes.set_xlabel("speed  [km/h]")
    axes.set_ylabel("force  [N]")
    axes.set_title(f"Longitudinal force balance -- {vehicle.name}")
    axes.legend(fontsize=8)
    axes.grid(alpha=0.2)
    return axes


def plot_gg_diagram(
    vehicle: Vehicle,
    ambient: AmbientConditions | None = None,
    axes: "Axes | None" = None,
    speeds_kph: tuple[int, ...] = (60, 120, 200, 280),
) -> "Axes":
    """The friction circle available at several speeds.

    Downforce inflates the circle with speed, which is the single most
    important thing about an F1 car's behaviour.
    """
    plt = _pyplot()
    axes = axes or plt.subplots(figsize=(6, 6))[1]
    conditions = ambient or AmbientConditions()
    rho = conditions.air_density
    mass = vehicle.total_mass()
    exponent = vehicle.config.tyres.combined_grip_exponent
    colours = ("#56B4E9", "#0072B2", "#E69F00", "#D55E00", "#CC79A7")

    for index, speed_kph in enumerate(speeds_kph):
        speed = kph_to_ms(speed_kph)
        lateral = lateral_capability(vehicle, speed, rho, mass=mass).lateral_g
        braking = max_deceleration(vehicle, speed, rho, mass=mass) / 9.80665
        # The envelope is the friction ellipse scaled onto each axis.
        points_x, points_y = [], []
        for i in range(241):
            fraction = i / 240.0
            lateral_used = -1.0 + 2.0 * fraction
            remaining = max(0.0, 1.0 - abs(lateral_used) ** exponent) ** (1.0 / exponent)
            points_x.append(lateral_used * lateral)
            points_y.append(remaining * braking)
        axes.plot(points_x, points_y, color=colours[index % len(colours)],
                  label=f"{speed_kph} km/h")
        axes.plot(points_x, [-y for y in points_y], color=colours[index % len(colours)],
                  linestyle="--", alpha=0.5)

    axes.axhline(0.0, color="#666", linewidth=0.7)
    axes.axvline(0.0, color="#666", linewidth=0.7)
    axes.set_xlabel("lateral  [g]")
    axes.set_ylabel("braking (+) / acceleration (-)  [g]")
    axes.set_title(f"g-g envelope -- {vehicle.name}")
    axes.set_aspect("equal", adjustable="datalim")
    axes.legend(fontsize=8)
    axes.grid(alpha=0.2)
    return axes


def plot_performance_envelope(
    vehicle: Vehicle, ambient: AmbientConditions | None = None, axes: "Axes | None" = None
) -> "Axes":
    """Lateral, braking and acceleration capability against speed."""
    plt = _pyplot()
    axes = axes or plt.subplots(figsize=(9, 4))[1]
    conditions = ambient or AmbientConditions()
    rho = conditions.air_density
    mass = vehicle.total_mass()
    top = benchmark_vehicle(vehicle, conditions, corner_radii=(), speed_targets=(),
                            braking_speeds=()).top_speed
    speeds = _speeds(top)
    kph = [ms_to_kph(s) for s in speeds]

    lateral = [lateral_capability(vehicle, s, rho, mass=mass).lateral_g for s in speeds]
    braking = [max_deceleration(vehicle, s, rho, mass=mass) / 9.80665 for s in speeds]
    accelerating = [
        longitudinal_forces(vehicle, s, rho, mass=mass, throttle=1.0).acceleration / 9.80665
        for s in speeds
    ]

    axes.plot(kph, lateral, label="lateral", color="#0072B2", linewidth=2)
    axes.plot(kph, braking, label="braking", color="#D55E00", linewidth=2)
    axes.plot(kph, accelerating, label="acceleration", color="#009E73", linewidth=2)
    axes.axhline(0.0, color="#666", linewidth=0.7)
    axes.set_xlabel("speed  [km/h]")
    axes.set_ylabel("acceleration  [g]")
    axes.set_title(
        f"Performance envelope -- {vehicle.name}  "
        f"(downforce is why lateral and braking rise with speed)"
    )
    axes.legend(fontsize=8)
    axes.grid(alpha=0.2)
    return axes


def plot_cornering(
    vehicle: Vehicle, ambient: AmbientConditions | None = None, axes: "Axes | None" = None
) -> "Axes":
    """Cornering speed against radius, with the flat-out region marked."""
    plt = _pyplot()
    axes = axes or plt.subplots(figsize=(9, 4))[1]
    conditions = ambient or AmbientConditions()
    rho = conditions.air_density
    mass = vehicle.total_mass()
    top = benchmark_vehicle(vehicle, conditions, corner_radii=(), speed_targets=(),
                            braking_speeds=()).top_speed

    radii = [10.0 * 1.09**i for i in range(60)]
    speeds = [
        corner_speed_limit(vehicle, 1.0 / r, rho, mass=mass, max_speed=top) for r in radii
    ]
    kph = [ms_to_kph(s) for s in speeds]

    axes.plot(radii, kph, color="#0072B2", linewidth=2)
    axes.axhline(ms_to_kph(top), color="#333", linestyle="--", linewidth=1,
                 label=f"top speed {ms_to_kph(top):.0f} km/h")
    flat_out = [r for r, s in zip(radii, speeds) if s >= top - 1e-6]
    if flat_out:
        axes.axvspan(min(flat_out), max(radii), color="#009E73", alpha=0.10,
                     label="flat out")
    axes.set_xscale("log")
    axes.set_xlabel("corner radius  [m]")
    axes.set_ylabel("cornering speed  [km/h]")
    axes.set_title(f"Cornering limit -- {vehicle.name}")
    axes.legend(fontsize=8)
    axes.grid(alpha=0.2, which="both")
    return axes


def plot_vehicle_overview(
    vehicle: Vehicle, ambient: AmbientConditions | None = None
) -> "Figure":
    """One figure with every Phase 2 diagnostic."""
    plt = _pyplot()
    conditions = ambient or AmbientConditions()
    figure = plt.figure(figsize=(15, 10), layout="constrained")
    grid = figure.add_gridspec(2, 2)

    plot_force_balance(vehicle, conditions, figure.add_subplot(grid[0, 0]))
    plot_gg_diagram(vehicle, conditions, figure.add_subplot(grid[0, 1]))
    plot_performance_envelope(vehicle, conditions, figure.add_subplot(grid[1, 0]))
    plot_cornering(vehicle, conditions, figure.add_subplot(grid[1, 1]))

    figure.suptitle(
        f"Vehicle diagnostics -- {vehicle.name}   "
        f"(wing {vehicle.wing_level:.2f}, {vehicle.total_mass():.0f} kg, "
        f"air {conditions.air_temperature:.0f} degC)",
        fontsize=14,
    )
    return figure


def save_vehicle_overview(
    vehicle: Vehicle,
    path: str,
    ambient: AmbientConditions | None = None,
    *,
    dpi: int = 110,
) -> str:
    """Render :func:`plot_vehicle_overview` to an image file."""
    plt = _pyplot()
    figure = plot_vehicle_overview(vehicle, ambient)
    figure.savefig(path, dpi=dpi)
    plt.close(figure)
    return path
