"""The gearbox, and the engine curve it is there to keep the engine on.

Phase 2 stood in for all of this with one number -- a peak wheel torque -- and
said so.  What that number cannot represent is the thing a gearbox exists for:
an engine makes its power over a narrow band of crank speed, and the gearbox is
how a car that has to go from 60 km/h to 340 km/h keeps it there.

Three consequences follow, and none of them can be had from a single torque
figure:

* **Force is not flat within a gear.**  The engine climbs its curve as the car
  accelerates, so tractive force rises and then falls between shifts.
* **Top speed is a gear, not a balance of forces.**  Past the ratio's limit
  there is no more drive whatever the drag says, which is why a Formula 1 car
  at Monza sits on the limiter rather than creeping towards a terminal
  velocity.
* **Shifting costs time.**  Forty milliseconds with no drive, six or seven
  times up a long straight, is a real fraction of a second a lap.

The ratios shipped here put the car on its limiter at about 350 km/h in eighth
and let it pull away from a standstill in first, which is where a Formula 1
gear set sits.  They are data: a low-drag circuit is geared longer and a street
circuit shorter, and that is a setup decision the model can now express.
"""

from __future__ import annotations

import math
import bisect
from dataclasses import dataclass, field
from typing import Any

from ..core.errors import ConfigError
from ..core.interpolation import clamp
from ..core.units import MetresPerSecond, Newtons, Watts

__all__ = ["GearboxProperties", "Gearbox", "GearSelection"]

#: Overall ratios (gear times final drive) for a modern eight-speed Formula 1
#: gearbox.  Each gear runs to the limiter about 15% faster than the one
#: below, closing towards the top, which puts first at 125 km/h and eighth at
#: 350 -- and keeps the engine within a few hundred revolutions of its power
#: peak everywhere it matters.  A car does not launch on the ratio; the clutch
#: does that.
DEFAULT_RATIOS: tuple[float, ...] = (
    16.29, 14.04, 12.12, 10.49, 9.09, 7.83, 6.79, 5.82,
)


@dataclass(frozen=True, slots=True)
class GearboxProperties:
    """A car's gear set and the engine curve behind it."""

    ratios: tuple[float, ...] = DEFAULT_RATIOS
    """Overall ratios, engine revolutions per wheel revolution, lowest first."""

    rev_limit: float = 15_000.0
    """Crank speed the engine is cut at, rpm.  The regulated ceiling."""

    peak_power_rpm: float = 10_500.0
    """Where the power curve peaks, rpm."""

    idle_rpm: float = 4_000.0

    rise_exponent: float = 1.6
    """Shape of the power curve below its peak, as ``(rpm / peak)^n``.

    1.6 puts a power unit at 60% of its power-peak speed on about 40% of its
    power, which is what a modern one does."""

    limiter_power_fraction: float = 0.93
    """Share of peak power still available at the rev limit.

    Not one: an engine held past its power peak is losing breathing, and that
    is why a driver takes the next gear rather than sitting on the limiter."""

    shift_time: float = 0.040
    """Seconds with no drive per gear change.

    Charged where it is actually paid: a gear that is over in under a second
    loses a real share of itself to the change out of it, and a top gear held
    for the length of a straight loses nothing.  The purely mechanical losses
    are separate and live in ``powertrain.drivetrain_efficiency``, so nothing
    is counted twice."""

    reference_acceleration: float = 6.0
    """Acceleration, m/s^2, used to turn a gear's speed span into a duration.

    A shift costs a fixed time, so what it costs as a *share* depends on how
    long the gear lasts -- and that is the span divided by how hard the car is
    accelerating.  Using one representative figure keeps the force a function
    of speed alone, which is what the quasi-steady speed profile needs."""

    def __post_init__(self) -> None:
        if len(self.ratios) < 2:
            raise ConfigError("a gearbox needs at least two ratios")
        if any(r <= 0.0 for r in self.ratios):
            raise ConfigError("gear ratios must be positive")
        if any(b >= a for a, b in zip(self.ratios, self.ratios[1:])):
            raise ConfigError("gear ratios must fall from first to top gear")
        if self.rev_limit <= self.peak_power_rpm:
            raise ConfigError("the rev limit must be above the power peak")
        if self.idle_rpm <= 0.0 or self.idle_rpm >= self.peak_power_rpm:
            raise ConfigError("idle_rpm must be positive and below the power peak")
        if self.rise_exponent <= 0.0:
            raise ConfigError("rise_exponent must be positive")
        if not 0.5 <= self.limiter_power_fraction <= 1.0:
            raise ConfigError("limiter_power_fraction must lie in [0.5, 1.0]")
        if self.shift_time < 0.0:
            raise ConfigError("shift_time must not be negative")
        if self.reference_acceleration <= 0.0:
            raise ConfigError("reference_acceleration must be positive")

    @property
    def gears(self) -> int:
        return len(self.ratios)

    @property
    def top_ratio(self) -> float:
        return self.ratios[-1]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ratios": list(self.ratios),
            "rev_limit": self.rev_limit,
            "peak_power_rpm": self.peak_power_rpm,
            "rise_exponent": self.rise_exponent,
            "idle_rpm": self.idle_rpm,
            "limiter_power_fraction": self.limiter_power_fraction,
            "shift_time": self.shift_time,
            "reference_acceleration": self.reference_acceleration,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GearboxProperties:
        payload = dict(data)
        unknown = set(payload) - set(cls.__slots__)
        if unknown:
            raise ConfigError(f"unknown gearbox key(s): {', '.join(sorted(unknown))}")
        if "ratios" in payload:
            payload["ratios"] = tuple(float(r) for r in payload["ratios"])
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class GearSelection:
    """What gear the car is in and what it is getting for it."""

    gear: int
    """1-based, 0 when the car is below the lowest gear's idle speed."""

    rpm: float
    force: Newtons
    power: Watts
    on_the_limiter: bool = False


class Gearbox:
    """Turns road speed into a gear, a crank speed and a tractive force."""

    __slots__ = ("_properties", "_wheel_radius", "_limits", "_rpm_per_speed", "_shift_loss")

    def __init__(self, properties: GearboxProperties, wheel_radius: float) -> None:
        if wheel_radius <= 0.0:
            raise ConfigError("wheel_radius must be positive")
        self._properties = properties
        self._wheel_radius = wheel_radius
        # Everything that depends only on the ratios, worked out once: this is
        # asked for tens of thousands of times a lap.
        factor = 60.0 / (2.0 * math.pi * wheel_radius)
        self._rpm_per_speed = tuple(ratio * factor for ratio in properties.ratios)
        self._limits = tuple(
            properties.rev_limit / per_speed for per_speed in self._rpm_per_speed
        )
        losses = []
        for index, limit in enumerate(self._limits):
            if index == len(self._limits) - 1:
                losses.append(1.0)  # nothing to change into
                continue
            span = limit - (self._limits[index - 1] if index else 0.0)
            duration = span / properties.reference_acceleration
            losses.append(1.0 - clamp(properties.shift_time / duration, 0.0, 0.25))
        self._shift_loss = tuple(losses)

    @property
    def properties(self) -> GearboxProperties:
        return self._properties

    # -- the engine curve ----------------------------------------------------

    def power_fraction(self, rpm: float) -> float:
        """Share of peak power the engine makes at ``rpm``.

        A single smooth hump: power climbs from idle, peaks where the engine is
        designed to, and falls back towards the limiter.  Torque is then
        ``P / omega``, which is what gives the familiar shape -- torque peaking
        well below the power peak and falling away above it.
        """
        props = self._properties
        if rpm <= 0.0:
            return 0.0
        if rpm <= props.peak_power_rpm:
            # The rising side matters more than it looks: it is what decides
            # which gear a driver is in.  Force at a given road speed is
            # ``P / v`` whatever the ratio, so the gear that wins is simply the
            # one putting the engine nearest its power peak -- and if low
            # revolutions were nearly as powerful as the peak, the model would
            # cruise around in eighth at 120 km/h.  A real power unit at 60% of
            # its power-peak speed makes about 40% of its power, and the
            # exponent below is that.
            return clamp(rpm / props.peak_power_rpm, 0.0, 1.0) ** props.rise_exponent
        span = props.rev_limit - props.peak_power_rpm
        position = clamp((rpm - props.peak_power_rpm) / span, 0.0, 1.0) if span > 0 else 0.0
        return 1.0 - (1.0 - props.limiter_power_fraction) * position * position

    def rpm_at(self, speed: MetresPerSecond, gear: int) -> float:
        """Crank speed, rpm, at a road speed in a given 1-based gear."""
        return abs(speed) * self._rpm_per_speed[gear - 1]

    def speed_at_limit(self, gear: int) -> MetresPerSecond:
        """Road speed at which a gear reaches the rev limit, m/s."""
        return self._limits[gear - 1]

    @property
    def maximum_speed(self) -> MetresPerSecond:
        """Road speed on the limiter in top gear, m/s.  The car's ceiling."""
        return self._limits[-1]

    # -- what the road gets --------------------------------------------------

    def select(self, speed: MetresPerSecond, peak_power: Watts) -> GearSelection:
        """Choose the gear and report what it delivers.

        The gear a driver takes is the one that puts the most force on the road,
        which is what a shift map is for.  Gears whose ratio would put the
        engine past the limiter are not available at all.
        """
        props = self._properties
        speed = abs(speed)
        limits = self._limits

        # Only gears the engine can still turn are available, and the limits
        # rise with the gear, so the first one that reaches this speed is the
        # lowest available.  Force falls off either side of the power peak, so
        # walking up from there and stopping when it stops improving finds the
        # best gear without trying all of them.
        first = bisect.bisect_left(limits, speed)
        if first >= len(limits):
            return GearSelection(gear=0, rpm=props.rev_limit, force=0.0, power=0.0,
                                 on_the_limiter=True)

        effective = max(speed, self._wheel_radius)
        best: GearSelection | None = None
        for index in range(first, len(limits)):
            rpm = speed * self._rpm_per_speed[index]
            power = peak_power * self.power_fraction(max(rpm, props.idle_rpm))
            force = power * self._shift_loss[index] / effective
            if best is not None and force <= best.force:
                break
            best = GearSelection(
                gear=index + 1,
                rpm=rpm,
                force=force,
                power=power,
                on_the_limiter=rpm >= props.rev_limit * 0.999,
            )
        assert best is not None
        return best

    def tractive_force(self, speed: MetresPerSecond, peak_power: Watts) -> Newtons:
        """Drive force available at ``speed``, N, before the traction limit.

        The same answer :meth:`select` gives, without building the record of
        how it got there.  Worth separating: the speed profile asks for this
        tens of thousands of times a lap and never looks at the gear.
        """
        speed = abs(speed)
        limits = self._limits
        first = bisect.bisect_left(limits, speed)
        if first >= len(limits):
            return 0.0
        props = self._properties
        effective = max(speed, self._wheel_radius)
        idle = props.idle_rpm
        best = 0.0
        for index in range(first, len(limits)):
            rpm = speed * self._rpm_per_speed[index]
            force = (
                peak_power
                * self.power_fraction(rpm if rpm > idle else idle)
                * self._shift_loss[index]
                / effective
            )
            if force <= best:
                break
            best = force
        return best

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"Gearbox({self._properties.gears} gears, "
            f"max {self.maximum_speed * 3.6:.0f} km/h)"
        )
