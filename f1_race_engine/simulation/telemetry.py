"""Telemetry.

Project rule 43 asks that the engine's output be comparable with real Formula 1
telemetry, so the sample below carries the channels a real trace does: distance,
time, speed, throttle, brake, gear, and the accelerations.  A lap recorded here
and a lap pulled from FastF1 line up channel for channel, which is what makes
calibration possible later.

Recording is opt-in and strided, because a full race at 1 m resolution is
millions of samples and almost nobody needs all of them.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Any

from ..core.units import Metres, MetresPerSecond, Seconds, ms_to_kph

__all__ = ["Telemetry", "TelemetrySample"]

_COLUMNS = (
    "distance", "time", "speed", "speed_kph", "throttle", "brake", "steering",
    "gear", "longitudinal_g", "lateral_g", "sector", "corner_id", "drs",
    "tyre_wear", "fuel_mass", "duration",
)


@dataclass(frozen=True, slots=True)
class TelemetrySample:
    """One instant of a lap."""

    distance: Metres
    time: Seconds
    speed: MetresPerSecond
    throttle: float
    brake: float
    """Fraction of the braking *system's* capability being demanded.

    An F1 car's brakes are deliberately stronger than its tyres, so at the
    limit this saturates around 0.7 rather than 1.0 -- the tyres lock first.
    Real telemetry records pedal *pressure*, which is a different quantity and
    does reach 100%; the two are not directly comparable without a pedal-force
    map, which belongs with the brake model in Phase 12."""

    steering: float
    longitudinal_g: float
    lateral_g: float
    sector: int
    corner_id: int | None = None
    gear: int | None = None
    drs: bool = False
    tyre_wear: float = 0.0
    fuel_mass: float = 0.0
    duration: Seconds = 0.0
    """Time this sample's step took.  Carried so that the summary fractions can
    be time-weighted the way real telemetry reports them -- samples are spaced
    by distance, and a lap has far more of them in the corners."""

    @property
    def speed_kph(self) -> float:
        return ms_to_kph(self.speed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "distance": self.distance,
            "time": self.time,
            "speed": self.speed,
            "speed_kph": self.speed_kph,
            "throttle": self.throttle,
            "brake": self.brake,
            "steering": self.steering,
            "gear": self.gear,
            "longitudinal_g": self.longitudinal_g,
            "lateral_g": self.lateral_g,
            "sector": self.sector,
            "corner_id": self.corner_id,
            "drs": self.drs,
            "tyre_wear": self.tyre_wear,
            "fuel_mass": self.fuel_mass,
            "duration": self.duration,
        }


@dataclass
class Telemetry:
    """A recorded trace of one lap."""

    samples: list[TelemetrySample] = field(default_factory=list)
    stride: int = 1
    _seen: int = field(default=0, repr=False)

    def record(self, sample: TelemetrySample) -> None:
        if self._seen % self.stride == 0:
            self.samples.append(sample)
        self._seen += 1

    def __len__(self) -> int:
        return len(self.samples)

    def __iter__(self):
        return iter(self.samples)

    def __getitem__(self, index: int) -> TelemetrySample:
        return self.samples[index]

    # -- summary -------------------------------------------------------------

    def channel(self, name: str) -> list[float]:
        """One channel as a plain list, for plotting or comparison."""
        if name not in _COLUMNS:
            raise KeyError(f"unknown telemetry channel {name!r}; have {_COLUMNS}")
        return [sample.to_dict()[name] for sample in self.samples]

    @property
    def duration(self) -> Seconds:
        return self.samples[-1].time if self.samples else 0.0

    def _time_weighted(self, predicate) -> float:
        total = sum(sample.duration for sample in self.samples)
        if total <= 0.0:
            return 0.0
        return (
            sum(sample.duration for sample in self.samples if predicate(sample)) / total
        )

    @property
    def full_throttle_fraction(self) -> float:
        """Share of lap *time* at full throttle.

        Time-weighted, which is how teams quote it: Monza is about 80%,
        Silverstone 70%, Monaco 55%.
        """
        return self._time_weighted(lambda s: s.throttle >= 0.99)

    @property
    def braking_fraction(self) -> float:
        """Share of lap time on the brakes."""
        return self._time_weighted(lambda s: s.brake > 0.0)

    @property
    def cornering_fraction(self) -> float:
        """Share of lap time carrying meaningful lateral load."""
        return self._time_weighted(lambda s: abs(s.lateral_g) > 0.5)

    # -- export --------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "samples": [sample.to_dict() for sample in self.samples],
            "count": len(self.samples),
        }

    def to_csv(self) -> str:
        """CSV with one row per sample, for comparison against real traces."""
        buffer = io.StringIO()
        buffer.write(",".join(_COLUMNS) + "\n")
        for sample in self.samples:
            payload = sample.to_dict()
            buffer.write(
                ",".join(
                    "" if payload[column] is None else str(payload[column])
                    for column in _COLUMNS
                )
                + "\n"
            )
        return buffer.getvalue()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Telemetry({len(self.samples)} samples, {self.duration:.3f} s)"
