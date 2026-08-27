"""Vehicle performance benchmark (project rule 41).

Phase 1 benchmarked the circuit.  Phase 2 benchmarks the car: the standard
numbers a race engineer would quote, produced by integrating the force balance
rather than by being written down anywhere.

Every figure here is derived.  Top speed is where net force reaches zero;
0-100 km/h comes from integrating ``dt = dv / a(v)``; braking distance comes
from integrating the deceleration the tyres actually allow.  None of them is a
parameter, which is the point -- change the car's mass or wing level and they
all move together, in the directions physics says they should.

Reference figures for a 2024-generation Formula 1 car are carried alongside so
the output can be compared at a glance, and later against real telemetry
(project rule 43).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from ..core.units import kph_to_ms, ms_to_kph
from ..environment.conditions import AmbientConditions
from ..tyres.state import TyreState
from ..vehicle.model import Vehicle
from .lateral import corner_speed_limit, lateral_capability
from .longitudinal import longitudinal_forces, max_deceleration

__all__ = ["REFERENCE_F1", "VehicleBenchmark", "benchmark_vehicle", "format_benchmark"]

#: Published figures for a current-generation F1 car, for comparison only.
#: Never used as an input to the model.
REFERENCE_F1: dict[str, tuple[float, float]] = {
    "top_speed_kph": (320.0, 360.0),
    "zero_to_100_kph": (2.4, 3.0),
    "zero_to_200_kph": (4.4, 5.6),
    "zero_to_300_kph": (9.5, 12.5),
    "braking_200_to_0_m": (55.0, 80.0),
    "peak_lateral_g": (4.5, 6.5),
    "peak_braking_g": (4.5, 6.5),
    "standing_acceleration_g": (0.8, 1.6),
}


@dataclass(frozen=True, slots=True)
class VehicleBenchmark:
    """Measured performance of one car in one configuration."""

    vehicle: str
    wing_level: float
    mass: float
    air_density: float
    top_speed: float
    acceleration_times: dict[int, float]
    """Time from rest to each target speed, in km/h, seconds."""

    acceleration_distances: dict[int, float]
    braking_distances: dict[int, float]
    """Distance to stop from each speed, in km/h, metres."""

    braking_times: dict[int, float]
    peak_lateral_g: float
    peak_lateral_speed: float
    peak_braking_g: float
    standing_acceleration_g: float
    lateral_g_by_speed: dict[int, float]
    corner_speeds: dict[int, float]
    """Cornering speed limit, m/s, by corner radius in metres."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "vehicle": self.vehicle,
            "wing_level": self.wing_level,
            "mass": self.mass,
            "air_density": self.air_density,
            "top_speed": self.top_speed,
            "top_speed_kph": ms_to_kph(self.top_speed),
            "acceleration_times": dict(self.acceleration_times),
            "acceleration_distances": dict(self.acceleration_distances),
            "braking_distances": dict(self.braking_distances),
            "braking_times": dict(self.braking_times),
            "peak_lateral_g": self.peak_lateral_g,
            "peak_lateral_speed_kph": ms_to_kph(self.peak_lateral_speed),
            "peak_braking_g": self.peak_braking_g,
            "standing_acceleration_g": self.standing_acceleration_g,
            "lateral_g_by_speed": dict(self.lateral_g_by_speed),
            "corner_speeds_kph": {
                radius: ms_to_kph(speed) for radius, speed in self.corner_speeds.items()
            },
        }


def _net_acceleration(
    vehicle: Vehicle, speed: float, air_density: float, mass: float, tyres: TyreState
) -> float:
    return longitudinal_forces(
        vehicle,
        speed,
        air_density,
        mass=mass,
        throttle=1.0,
        tyre_state=tyres,
    ).acceleration


def _top_speed(
    vehicle: Vehicle,
    air_density: float,
    mass: float,
    tyres: TyreState,
    ceiling: float = 150.0,
) -> float:
    """Speed at which drive force equals resistance, m/s (bisection)."""
    if _net_acceleration(vehicle, ceiling, air_density, mass, tyres) > 0.0:
        return ceiling
    low, high = 1.0, ceiling
    for _ in range(60):
        mid = 0.5 * (low + high)
        if _net_acceleration(vehicle, mid, air_density, mass, tyres) > 0.0:
            low = mid
        else:
            high = mid
        if high - low < 1e-3:
            break
    return low


#: Sub-intervals used when integrating an acceleration or braking run.
#: Measured convergence on the reference car: 500 steps reproduces the
#: 4000-step answer to 1e-5 relative (0-300 km/h within 0.0002 s, a 200-0 km/h
#: stop within 0.00003 m) at an eighth of the cost.  Raise it for a
#: high-precision run; nothing in the model depends on the value.
INTEGRATION_STEPS: int = 500


def _accelerate_to(
    vehicle: Vehicle,
    target: float,
    air_density: float,
    mass: float,
    tyres: TyreState,
    steps: int = INTEGRATION_STEPS,
) -> tuple[float, float]:
    """Integrate ``dt = dv / a(v)`` from rest to ``target``.

    Returns ``(time, distance)``; infinite when the car cannot reach the target.
    """
    if target <= 0.0:
        return 0.0, 0.0
    dv = target / steps
    time = 0.0
    distance = 0.0
    speed = 0.0
    for _ in range(steps):
        mid_speed = speed + 0.5 * dv
        acceleration = _net_acceleration(vehicle, mid_speed, air_density, mass, tyres)
        if acceleration <= 1e-6:
            return math.inf, math.inf
        time += dv / acceleration
        distance += mid_speed * dv / acceleration
        speed += dv
    return time, distance


def _brake_from(
    vehicle: Vehicle,
    initial_speed: float,
    air_density: float,
    mass: float,
    tyres: TyreState,
    steps: int = INTEGRATION_STEPS,
) -> tuple[float, float]:
    """Integrate braking from ``initial_speed`` to rest.  Returns (time, distance)."""
    dv = initial_speed / steps
    time = 0.0
    distance = 0.0
    speed = initial_speed
    for _ in range(steps):
        mid_speed = max(speed - 0.5 * dv, 1e-3)
        deceleration = max_deceleration(
            vehicle, mid_speed, air_density, mass=mass, tyre_state=tyres
        )
        if deceleration <= 1e-6:
            return math.inf, math.inf
        time += dv / deceleration
        distance += mid_speed * dv / deceleration
        speed -= dv
    return time, distance


def benchmark_vehicle(
    vehicle: Vehicle,
    ambient: AmbientConditions | None = None,
    *,
    mass: float | None = None,
    tyre_state: TyreState | None = None,
    speed_targets: tuple[int, ...] = (100, 200, 300),
    braking_speeds: tuple[int, ...] = (100, 200, 300),
    corner_radii: tuple[int, ...] = (25, 50, 100, 200, 400, 800),
    integration_steps: int = INTEGRATION_STEPS,
) -> VehicleBenchmark:
    """Measure a car's performance envelope."""
    conditions = ambient or AmbientConditions()
    air_density = conditions.air_density
    car_mass = vehicle.total_mass() if mass is None else mass
    tyres = tyre_state or TyreState()

    top_speed = _top_speed(vehicle, air_density, car_mass, tyres)

    acceleration_times: dict[int, float] = {}
    acceleration_distances: dict[int, float] = {}
    for target_kph in speed_targets:
        target = kph_to_ms(target_kph)
        if target > top_speed:
            acceleration_times[target_kph] = math.inf
            acceleration_distances[target_kph] = math.inf
            continue
        time, distance = _accelerate_to(
            vehicle, target, air_density, car_mass, tyres, steps=integration_steps
        )
        acceleration_times[target_kph] = time
        acceleration_distances[target_kph] = distance

    braking_distances: dict[int, float] = {}
    braking_times: dict[int, float] = {}
    for speed_kph in braking_speeds:
        speed = kph_to_ms(speed_kph)
        if speed > top_speed:
            braking_distances[speed_kph] = math.inf
            braking_times[speed_kph] = math.inf
            continue
        time, distance = _brake_from(
            vehicle, speed, air_density, car_mass, tyres, steps=integration_steps
        )
        braking_times[speed_kph] = time
        braking_distances[speed_kph] = distance

    lateral_g_by_speed: dict[int, float] = {}
    peak_lateral_g = 0.0
    peak_lateral_speed = 0.0
    for speed_kph in range(50, int(ms_to_kph(top_speed)) + 1, 10):
        capability = lateral_capability(
            vehicle,
            kph_to_ms(speed_kph),
            air_density,
            mass=car_mass,
            tyre_state=tyres,
        )
        lateral_g_by_speed[speed_kph] = capability.lateral_g
        if capability.lateral_g > peak_lateral_g:
            peak_lateral_g = capability.lateral_g
            peak_lateral_speed = kph_to_ms(speed_kph)

    peak_braking_g = max(
        max_deceleration(
            vehicle, kph_to_ms(speed_kph), air_density, mass=car_mass, tyre_state=tyres
        )
        / 9.80665
        for speed_kph in range(50, int(ms_to_kph(top_speed)) + 1, 10)
    )

    standing_acceleration_g = (
        _net_acceleration(vehicle, 0.5, air_density, car_mass, tyres) / 9.80665
    )

    corner_speeds = {
        radius: corner_speed_limit(
            vehicle,
            1.0 / radius,
            air_density,
            mass=car_mass,
            tyre_state=tyres,
            max_speed=top_speed,
        )
        for radius in corner_radii
    }

    return VehicleBenchmark(
        vehicle=vehicle.name,
        wing_level=vehicle.wing_level,
        mass=car_mass,
        air_density=air_density,
        top_speed=top_speed,
        acceleration_times=acceleration_times,
        acceleration_distances=acceleration_distances,
        braking_distances=braking_distances,
        braking_times=braking_times,
        peak_lateral_g=peak_lateral_g,
        peak_lateral_speed=peak_lateral_speed,
        peak_braking_g=peak_braking_g,
        standing_acceleration_g=standing_acceleration_g,
        lateral_g_by_speed=lateral_g_by_speed,
        corner_speeds=corner_speeds,
    )


def _check(value: float, key: str) -> str:
    """Mark a figure against its published Formula 1 range."""
    bounds = REFERENCE_F1.get(key)
    if bounds is None or not math.isfinite(value):
        return "     "
    low, high = bounds
    if value < low:
        return " LOW "
    if value > high:
        return " HIGH"
    return "  ok "


def format_benchmark(benchmark: VehicleBenchmark) -> str:
    """Render a benchmark as readable text, flagged against real F1 figures."""
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append(f"VEHICLE BENCHMARK  --  {benchmark.vehicle}")
    lines.append("=" * 72)
    lines.append(
        f"  wing level {benchmark.wing_level:.2f}   mass {benchmark.mass:.0f} kg   "
        f"air density {benchmark.air_density:.4f} kg/m^3"
    )
    lines.append("")
    lines.append(f"  {'':<28}{'value':>12}{'':<7}{'F1 reference':>16}")
    lines.append("  " + "-" * 66)

    top_kph = ms_to_kph(benchmark.top_speed)
    lines.append(
        f"  {'top speed':<28}{top_kph:>9.1f} km/h{_check(top_kph, 'top_speed_kph')}"
        f"{'320-360 km/h':>16}"
    )
    for target, time in benchmark.acceleration_times.items():
        key = f"zero_to_{target}_kph"
        reference = REFERENCE_F1.get(key)
        text = f"{reference[0]:.1f}-{reference[1]:.1f} s" if reference else ""
        value = f"{time:>11.2f} s" if math.isfinite(time) else f"{'n/a':>13}"
        lines.append(
            f"  {'0-' + str(target) + ' km/h':<28}{value}{_check(time, key)}{text:>16}"
        )
    lines.append("")
    for speed, distance in benchmark.braking_distances.items():
        key = f"braking_{speed}_to_0_m"
        reference = REFERENCE_F1.get(key)
        text = f"{reference[0]:.0f}-{reference[1]:.0f} m" if reference else ""
        value = f"{distance:>11.1f} m" if math.isfinite(distance) else f"{'n/a':>13}"
        lines.append(
            f"  {str(speed) + '-0 km/h braking':<28}{value}"
            f"{_check(distance, key)}{text:>16}"
        )
    lines.append("")
    lines.append(
        f"  {'peak lateral':<28}{benchmark.peak_lateral_g:>11.2f} g"
        f"{_check(benchmark.peak_lateral_g, 'peak_lateral_g')}{'4.5-6.5 g':>16}"
    )
    lines.append(
        f"  {'peak braking':<28}{benchmark.peak_braking_g:>11.2f} g"
        f"{_check(benchmark.peak_braking_g, 'peak_braking_g')}{'4.5-6.5 g':>16}"
    )
    lines.append(
        f"  {'standing acceleration':<28}{benchmark.standing_acceleration_g:>11.2f} g"
        f"{_check(benchmark.standing_acceleration_g, 'standing_acceleration_g')}"
        f"{'0.8-1.6 g':>16}"
    )
    lines.append("")
    lines.append("  LATERAL GRIP BUILD-UP (downforce is proportional to v^2)")
    for speed_kph in sorted(benchmark.lateral_g_by_speed)[::5]:
        value = benchmark.lateral_g_by_speed[speed_kph]
        bar = "#" * int(round(value * 8))
        lines.append(f"    {speed_kph:>4} km/h  {value:>5.2f} g  {bar}")
    lines.append("")
    lines.append("  CORNERING SPEED BY RADIUS")
    for radius, speed in sorted(benchmark.corner_speeds.items()):
        flat = " (flat out)" if speed >= benchmark.top_speed - 1e-3 else ""
        lines.append(
            f"    R {radius:>4} m  {ms_to_kph(speed):>6.1f} km/h"
            f"  ({speed * speed / radius / 9.80665:.2f} g){flat}"
        )
    lines.append("=" * 72)
    return "\n".join(lines)
