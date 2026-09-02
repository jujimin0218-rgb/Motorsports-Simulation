"""Unit conventions and the conversion layer.

The engine computes **exclusively in SI units** (see project rule 38):

===============  ==========================
quantity         unit
===============  ==========================
distance         metre (m)
time             second (s)
speed            metre per second (m/s)
acceleration     metre per second squared
mass             kilogram (kg)
force            newton (N)
power            watt (W)
energy           joule (J)
angle            radian (rad)
temperature      kelvin (K) for physics,
                 degrees Celsius at the I/O boundary
pressure         pascal (Pa)
===============  ==========================

Human-facing data (track files, UI, telemetry imports) routinely uses km/h,
degrees, bar and horsepower.  Those values are converted **once**, at the
boundary, using the helpers in this module.  Nothing inside the physics core
should ever see a non-SI number.

Naming convention used throughout the engine: a variable carries its unit as a
suffix when ambiguity is possible (``speed_ms``, ``speed_kph``, ``angle_rad``,
``angle_deg``).  The type aliases below are documentation only -- they are
plain floats at runtime and cost nothing.
"""

from __future__ import annotations

import math
import re

from .errors import UnitError

# ---------------------------------------------------------------------------
# Semantic type aliases (documentation, zero runtime cost)
# ---------------------------------------------------------------------------

Metres = float
Seconds = float
MetresPerSecond = float
MetresPerSecondSquared = float
Kilograms = float
Newtons = float
Watts = float
Joules = float
Radians = float
Degrees = float
Kelvin = float
Celsius = float
Pascals = float
Curvature = float  # 1/m
Dimensionless = float

# ---------------------------------------------------------------------------
# Physical constants
# ---------------------------------------------------------------------------

#: Standard gravity (m/s^2), CODATA / ISO 80000 definition.
STANDARD_GRAVITY: MetresPerSecondSquared = 9.80665

#: Air density at 15 degC, 1013.25 hPa (ISA sea level), kg/m^3.
ISA_SEA_LEVEL_AIR_DENSITY: float = 1.225

#: Specific gas constant for dry air, J/(kg*K).
DRY_AIR_GAS_CONSTANT: float = 287.058

#: 0 degC expressed in kelvin.
ZERO_CELSIUS_IN_KELVIN: Kelvin = 273.15

# ---------------------------------------------------------------------------
# Speed
# ---------------------------------------------------------------------------

_KPH_PER_MS = 3.6
_MPH_PER_MS = 2.2369362920544020


def kph_to_ms(speed_kph: float) -> MetresPerSecond:
    """Convert kilometres per hour to metres per second."""
    return speed_kph / _KPH_PER_MS


def ms_to_kph(speed_ms: MetresPerSecond) -> float:
    """Convert metres per second to kilometres per hour."""
    return speed_ms * _KPH_PER_MS


def mph_to_ms(speed_mph: float) -> MetresPerSecond:
    """Convert miles per hour to metres per second."""
    return speed_mph / _MPH_PER_MS


def ms_to_mph(speed_ms: MetresPerSecond) -> float:
    """Convert metres per second to miles per hour."""
    return speed_ms * _MPH_PER_MS


# ---------------------------------------------------------------------------
# Distance
# ---------------------------------------------------------------------------


def km_to_m(distance_km: float) -> Metres:
    """Convert kilometres to metres."""
    return distance_km * 1000.0


def m_to_km(distance_m: Metres) -> float:
    """Convert metres to kilometres."""
    return distance_m / 1000.0


# ---------------------------------------------------------------------------
# Angle
# ---------------------------------------------------------------------------


def deg_to_rad(angle_deg: Degrees) -> Radians:
    """Convert degrees to radians."""
    return math.radians(angle_deg)


def rad_to_deg(angle_rad: Radians) -> Degrees:
    """Convert radians to degrees."""
    return math.degrees(angle_rad)


def wrap_angle(angle_rad: Radians) -> Radians:
    """Wrap an angle into ``(-pi, pi]``."""
    wrapped = math.remainder(angle_rad, math.tau)
    # math.remainder maps exactly -pi to -pi; normalise to +pi for stability.
    if wrapped == -math.pi:
        return math.pi
    return wrapped


# ---------------------------------------------------------------------------
# Acceleration
# ---------------------------------------------------------------------------


def g_to_ms2(acceleration_g: float) -> MetresPerSecondSquared:
    """Convert an acceleration expressed in g to m/s^2."""
    return acceleration_g * STANDARD_GRAVITY


def ms2_to_g(acceleration_ms2: MetresPerSecondSquared) -> float:
    """Convert an acceleration in m/s^2 to multiples of g."""
    return acceleration_ms2 / STANDARD_GRAVITY


# ---------------------------------------------------------------------------
# Power and energy
# ---------------------------------------------------------------------------

_WATTS_PER_METRIC_HP = 735.49875
_WATTS_PER_KW = 1000.0


def hp_to_w(power_hp: float) -> Watts:
    """Convert metric horsepower (PS) to watts."""
    return power_hp * _WATTS_PER_METRIC_HP


def w_to_hp(power_w: Watts) -> float:
    """Convert watts to metric horsepower (PS)."""
    return power_w / _WATTS_PER_METRIC_HP


def kw_to_w(power_kw: float) -> Watts:
    """Convert kilowatts to watts."""
    return power_kw * _WATTS_PER_KW


def w_to_kw(power_w: Watts) -> float:
    """Convert watts to kilowatts."""
    return power_w / _WATTS_PER_KW


def kj_to_j(energy_kj: float) -> Joules:
    """Convert kilojoules to joules."""
    return energy_kj * 1000.0


def j_to_kj(energy_j: Joules) -> float:
    """Convert joules to kilojoules."""
    return energy_j / 1000.0


def mj_to_j(energy_mj: float) -> Joules:
    """Convert megajoules to joules."""
    return energy_mj * 1.0e6


def j_to_mj(energy_j: Joules) -> float:
    """Convert joules to megajoules."""
    return energy_j / 1.0e6


# ---------------------------------------------------------------------------
# Temperature and pressure
# ---------------------------------------------------------------------------


def celsius_to_kelvin(temperature_c: Celsius) -> Kelvin:
    """Convert degrees Celsius to kelvin."""
    return temperature_c + ZERO_CELSIUS_IN_KELVIN


def kelvin_to_celsius(temperature_k: Kelvin) -> Celsius:
    """Convert kelvin to degrees Celsius."""
    return temperature_k - ZERO_CELSIUS_IN_KELVIN


def bar_to_pa(pressure_bar: float) -> Pascals:
    """Convert bar to pascals."""
    return pressure_bar * 1.0e5


def pa_to_bar(pressure_pa: Pascals) -> float:
    """Convert pascals to bar."""
    return pressure_pa / 1.0e5


def psi_to_pa(pressure_psi: float) -> Pascals:
    """Convert pounds per square inch to pascals."""
    return pressure_psi * 6894.757293168361


def pa_to_psi(pressure_pa: Pascals) -> float:
    """Convert pascals to pounds per square inch."""
    return pressure_pa / 6894.757293168361


# ---------------------------------------------------------------------------
# Track geometry helpers
# ---------------------------------------------------------------------------

#: Radius treated as "straight".  1/50000 m^-1 is far below any measurable
#: lateral load, so anything flatter is numerically a straight line.
STRAIGHT_RADIUS_THRESHOLD: Metres = 50_000.0


def curvature_from_radius(radius_m: Metres) -> Curvature:
    """Return the curvature (1/m) matching ``radius_m``.

    A radius of zero or beyond :data:`STRAIGHT_RADIUS_THRESHOLD` returns ``0``
    (a straight).  The sign of the radius is preserved: a positive radius is a
    left-hand corner, a negative radius a right-hand corner.
    """
    if radius_m == 0.0:
        raise UnitError("radius of 0 m is not a physical corner")
    if abs(radius_m) >= STRAIGHT_RADIUS_THRESHOLD:
        return 0.0
    return 1.0 / radius_m


def radius_from_curvature(curvature: Curvature) -> Metres:
    """Return the radius (m) matching ``curvature``.

    Straights (curvature 0) return ``inf`` rather than raising, because a
    speed-profile pass legitimately asks for "the radius here" on a straight.
    """
    if curvature == 0.0:
        return math.inf
    return 1.0 / curvature


def gradient_from_percent(gradient_percent: float) -> Dimensionless:
    """Convert a road gradient in percent to the dimensionless slope dz/ds."""
    return gradient_percent / 100.0


def percent_from_gradient(gradient: Dimensionless) -> float:
    """Convert a dimensionless slope dz/ds to percent."""
    return gradient * 100.0


# ---------------------------------------------------------------------------
# Lap time formatting (I/O boundary only)
# ---------------------------------------------------------------------------

_LAP_TIME_RE = re.compile(r"^(?:(?P<min>\d+):)?(?P<sec>\d{1,2}(?:\.\d+)?)$")


def format_lap_time(seconds: Seconds, decimals: int = 3) -> str:
    """Format a lap time in seconds as ``M:SS.mmm``.

    Values below one minute are still rendered with a leading ``0:`` so that
    timing tables line up.
    """
    if not math.isfinite(seconds):
        return "--:--.---"
    sign = "-" if seconds < 0 else ""
    seconds = abs(seconds)
    minutes = int(seconds // 60)
    remainder = seconds - minutes * 60
    # Guard against 59.9996 rounding up into "60.000".
    if round(remainder, decimals) >= 60.0:
        minutes += 1
        remainder = 0.0
    return f"{sign}{minutes}:{remainder:0{decimals + 3}.{decimals}f}"


def format_gap(seconds: Seconds, decimals: int = 3) -> str:
    """Format a time gap as ``+S.mmm`` (or ``M:SS.mmm`` for large gaps)."""
    if not math.isfinite(seconds):
        return "--"
    if abs(seconds) < 60.0:
        return f"{seconds:+.{decimals}f}"
    sign = "+" if seconds >= 0 else "-"
    return f"{sign}{format_lap_time(abs(seconds), decimals)}"


def parse_lap_time(text: str) -> Seconds:
    """Parse ``"1:21.345"`` or ``"81.345"`` into seconds."""
    match = _LAP_TIME_RE.match(text.strip())
    if match is None:
        raise UnitError(f"cannot parse lap time from {text!r}")
    minutes = int(match.group("min") or 0)
    return minutes * 60.0 + float(match.group("sec"))
