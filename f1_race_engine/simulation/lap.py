"""Lap simulation -- a car actually driving a lap.

Project rule 26 specifies the flow, and this module is it:

.. code-block:: text

    Track Segment -> Vehicle State -> Driver Input -> Physics -> New Vehicle State
          ^                                                              |
          +--------------------------- next segment --------------------+

with time integrated as ``dt = ds / v``.

**How this differs from Phase 3.**  Phase 3 produced the *limit lap*: an
integral over a speed profile, with a perfect driver.  Phase 4 puts a real
driver in the car and steps the vehicle state forward segment by segment,
producing pedal inputs and telemetry at every step.  A driver whose commitment
is 1.0 on every axis and whose consistency is perfect reproduces the Phase 3
answer exactly -- which is the test that says the stepping is right.

**Where the driver enters.**  Not as a lap-time correction.  The driver's
abilities become grip commitments, the commitments change the cornering limit,
and the profile's forward and backward passes propagate the consequences: a
weaker braker brakes earlier, a mistake at one corner costs the exit and the
following straight as well.  Nothing here ever adds seconds to a result.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from ..core.config import SimulationConfig
from ..core.rng import RngHub
from ..core.units import Seconds, format_lap_time, ms_to_kph
from ..driver.consistency import LapVariation, sample_lap_variation
from ..driver.inputs import control_input
from ..driver.mistakes import DriverMistake, sample_mistakes
from ..driver.model import Driver
from ..driver.pace import Commitment, commitment_for
from ..environment.conditions import AmbientConditions
from ..physics.longitudinal import longitudinal_forces
from ..physics.speed_profile import SpeedProfile, compute_speed_profile, cornering_limits
from ..track.model import Track
from ..track.surface import TrackConditions
from ..tyres.state import TyreState
from ..vehicle.model import Vehicle
from ..vehicle.state import VehicleState
from .telemetry import Telemetry, TelemetrySample

__all__ = ["LapResult", "LapSimulator", "simulate_lap"]


@dataclass(frozen=True)
class LapResult:
    """One driver's lap."""

    driver_name: str
    vehicle_name: str
    track_name: str
    lap: int
    lap_time: Seconds
    sector_times: tuple[Seconds, ...]
    top_speed: float
    minimum_speed: float
    average_speed: float
    max_lateral_g: float
    max_braking_g: float
    commitment: Commitment
    mistakes: tuple[DriverMistake, ...] = ()
    variation: LapVariation | None = field(default=None, repr=False)
    telemetry: Telemetry | None = field(default=None, repr=False)
    profile: SpeedProfile | None = field(default=None, repr=False)
    final_state: VehicleState | None = field(default=None, repr=False)

    @property
    def formatted(self) -> str:
        return format_lap_time(self.lap_time)

    @property
    def had_mistake(self) -> bool:
        return bool(self.mistakes)

    def to_dict(self, *, include_telemetry: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "driver": self.driver_name,
            "vehicle": self.vehicle_name,
            "track": self.track_name,
            "lap": self.lap,
            "lap_time": self.lap_time,
            "lap_time_formatted": self.formatted,
            "sector_times": list(self.sector_times),
            "top_speed_kph": ms_to_kph(self.top_speed),
            "minimum_speed_kph": ms_to_kph(self.minimum_speed),
            "average_speed_kph": ms_to_kph(self.average_speed),
            "max_lateral_g": self.max_lateral_g,
            "max_braking_g": self.max_braking_g,
            "commitment": {
                "cornering": self.commitment.cornering,
                "braking": self.commitment.braking,
                "traction": self.commitment.traction,
            },
            "mistakes": [mistake.to_dict() for mistake in self.mistakes],
        }
        if include_telemetry and self.telemetry is not None:
            payload["telemetry"] = self.telemetry.to_dict()
        return payload

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"LapResult({self.driver_name!r} lap {self.lap}, {self.formatted}"
            f"{', mistake' if self.had_mistake else ''})"
        )


class LapSimulator:
    """Drives one car around one circuit, one lap at a time.

    The simulator is reusable across laps: the expensive part -- resolving the
    track state at every node -- is done once, and each lap only re-runs the
    profile passes and the stepping.
    """

    __slots__ = (
        "track", "vehicle", "driver", "ambient", "config", "rng",
        "_conditions", "_corners", "_max_curvature",
    )

    def __init__(
        self,
        track: Track,
        vehicle: Vehicle,
        driver: Driver,
        *,
        rng: RngHub | None = None,
        ambient: AmbientConditions | None = None,
        conditions: TrackConditions | None = None,
        config: SimulationConfig | None = None,
    ) -> None:
        self.track = track
        self.vehicle = vehicle
        self.driver = driver
        self.ambient = ambient or AmbientConditions()
        self.config = config or vehicle.config
        self.rng = rng or RngHub(self.config.randomness.seed)
        self._conditions = conditions
        self._corners: dict[int, str | None] = {
            int(corner_id): (
                str(entry["name"]) if entry.get("name") is not None else None
            )
            for corner_id, entry in track.corners.items()
        }
        self._max_curvature = max(
            (abs(segment.curvature) for segment in track.segments), default=1.0
        ) or 1.0

    # -- the lap -------------------------------------------------------------

    def simulate(
        self,
        *,
        lap: int = 1,
        mass: float | None = None,
        tyre_state: TyreState | None = None,
        qualifying: bool = False,
        record_telemetry: bool = True,
        telemetry_stride: int = 1,
        start_speed: float | None = None,
    ) -> LapResult:
        """Simulate one lap.

        ``start_speed`` defaults to a flying lap -- the car crosses the line at
        whatever speed the profile says it can carry there.
        """
        vehicle, track = self.vehicle, self.track
        car_mass = vehicle.total_mass() if mass is None else mass
        tyres = tyre_state or TyreState()
        air_density = self.ambient.air_density
        driver_key = self.driver.abbreviation

        variation = sample_lap_variation(
            self.driver.attributes,
            self.rng,
            driver=driver_key,
            lap=lap,
            corner_ids=tuple(sorted(self._corners)),
            config=self.config.driver,
        )
        mistakes = sample_mistakes(
            self.driver.attributes,
            self.rng,
            driver=driver_key,
            lap=lap,
            corners=self._corners,
            config=self.config.driver,
        )
        commitment = commitment_for(
            self.driver.attributes,
            self.config.driver,
            qualifying=qualifying,
            bias=variation.lap_bias,
        )
        profile = self._build_profile(
            commitment, variation, mistakes, car_mass, tyres
        )
        return self._drive(
            profile, commitment, variation, mistakes, lap,
            car_mass, tyres, air_density,
            record_telemetry, telemetry_stride, start_speed,
        )

    # -- stage 1: the driver's own speed profile -----------------------------

    def _build_profile(
        self,
        commitment: Commitment,
        variation: LapVariation,
        mistakes: tuple[DriverMistake, ...],
        car_mass: float,
        tyres: TyreState,
    ) -> SpeedProfile:
        limits = commitment.as_limits()
        base = cornering_limits(
            self.track,
            self.vehicle,
            self.ambient,
            mass=car_mass,
            tyre_state=tyres,
            conditions=self._conditions,
            limits=limits,
            config=self.config.speed_profile,
        )

        penalties = {mistake.corner_id: mistake.speed_penalty for mistake in mistakes}
        needs_override = bool(penalties) or bool(variation.corner_bias)
        if not needs_override:
            return compute_speed_profile(
                self.track, self.vehicle, self.ambient,
                mass=car_mass, tyre_state=tyres, conditions=self._conditions,
                limits=limits, corner_limit_override=base,
                config=self.config.speed_profile,
            )

        adjusted = list(base)
        for index, segment in enumerate(self.track.segments):
            corner_id = segment.corner_id
            if corner_id is None:
                continue
            factor = 1.0
            bias = variation.corner_bias.get(corner_id, 0.0)
            if bias:
                # Lateral acceleration scales with the grip used, and speed with
                # its square root.
                factor *= math.sqrt(
                    max(1.0 + bias / max(commitment.cornering, 1e-6), 0.0)
                )
            penalty = penalties.get(corner_id)
            if penalty:
                factor *= 1.0 - penalty
            adjusted[index] = base[index] * factor

        return compute_speed_profile(
            self.track, self.vehicle, self.ambient,
            mass=car_mass, tyre_state=tyres, conditions=self._conditions,
            limits=limits, corner_limit_override=adjusted,
            config=self.config.speed_profile,
        )

    # -- stage 2: drive it ---------------------------------------------------

    def _drive(
        self,
        profile: SpeedProfile,
        commitment: Commitment,
        variation: LapVariation,
        mistakes: tuple[DriverMistake, ...],
        lap: int,
        car_mass: float,
        tyres: TyreState,
        air_density: float,
        record_telemetry: bool,
        telemetry_stride: int,
        start_speed: float | None,
    ) -> LapResult:
        track, vehicle = self.track, self.vehicle
        segments = track.segments
        count = len(segments)
        limits = commitment.as_limits()
        floor = self.config.speed_profile.minimum_speed

        state = VehicleState(
            speed=profile.speed[0] if start_speed is None else start_speed,
            fuel_mass=car_mass - vehicle.mass.dry_mass,
            tyres=tyres,
        )
        telemetry = Telemetry(stride=telemetry_stride) if record_telemetry else None

        boundaries = list(track.sector_boundaries)
        sector_times = [0.0] * (len(boundaries) + 1)
        top_speed = state.speed
        minimum_speed = state.speed
        max_lateral = 0.0
        max_braking = 0.0

        for index in range(count):
            segment = segments[index]
            step = segment.length
            curvature = profile.curvature[index]
            target = profile.speed[(index + 1) % count]
            speed = max(state.speed, floor)

            # The pedal is held across the segment, so the force it has to
            # supply is the one evaluated at the segment's representative
            # speed.  The profile's own energy update uses the same midpoint,
            # and using the entry speed here instead would report a driver
            # lifting slightly on a straight where they are in fact flat.
            reference = max(0.5 * (speed + target), floor)

            lateral_acceleration = reference * reference * abs(curvature)
            lateral_force = car_mass * lateral_acceleration
            surface_grip = track.state_at(segment.mid_distance, self._conditions).grip

            common = {
                "mass": car_mass,
                "gradient": segment.gradient,
                "banking": segment.banking,
                "tyre_state": tyres,
                "lateral_acceleration": lateral_acceleration,
                "lateral_force_used": lateral_force,
            }
            # What the car does with no pedal: drag, rolling resistance and the
            # slope.  The driver only supplies the difference from there.
            coasting = longitudinal_forces(
                vehicle, reference, air_density,
                surface_grip=surface_grip * limits.traction, **common,
            )

            command = control_input(
                speed=speed,
                target_speed=target,
                distance_step=step,
                mass=car_mass,
                coast_acceleration=coasting.acceleration,
                powertrain_force=vehicle.power_unit.tractive_force(reference),
                brake_system_force=vehicle.brakes.system_limit(),
                curvature=curvature,
                max_curvature=self._max_curvature,
            )

            applied = longitudinal_forces(
                vehicle, reference, air_density,
                throttle=command.throttle, brake=command.brake,
                surface_grip=surface_grip
                * (limits.braking if command.is_braking else limits.traction),
                **common,
            )
            acceleration = applied.acceleration

            squared = speed * speed + 2.0 * acceleration * step
            next_speed = math.sqrt(squared) if squared > 0.0 else floor
            next_speed = max(next_speed, floor)
            dt = 2.0 * step / (speed + next_speed)

            self._accumulate_sectors(
                sector_times, boundaries, segment.distance, step,
                speed, next_speed, track,
            )

            if telemetry is not None:
                telemetry.record(
                    TelemetrySample(
                        distance=segment.distance,
                        time=state.time,
                        speed=speed,
                        throttle=command.throttle,
                        brake=command.brake,
                        steering=command.steering,
                        longitudinal_g=acceleration / 9.80665,
                        lateral_g=lateral_acceleration / 9.80665,
                        sector=segment.sector,
                        corner_id=segment.corner_id,
                        gear=command.gear,
                        drs=segment.has_drs,
                        tyre_wear=tyres.wear,
                        fuel_mass=state.fuel_mass,
                        duration=dt,
                    )
                )

            state.time += dt
            state.distance += step
            state.speed = next_speed
            state.acceleration = acceleration
            state.lateral_acceleration = lateral_acceleration
            state.throttle = command.throttle
            state.brake = command.brake
            tyres.age_distance += step

            top_speed = max(top_speed, next_speed)
            minimum_speed = min(minimum_speed, next_speed)
            max_lateral = max(max_lateral, lateral_acceleration)
            max_braking = max(max_braking, -acceleration)

        tyres.age_laps += 1.0
        lap_time = state.time
        return LapResult(
            driver_name=self.driver.name,
            vehicle_name=self.vehicle.name,
            track_name=track.name,
            lap=lap,
            lap_time=lap_time,
            sector_times=tuple(sector_times),
            top_speed=top_speed,
            minimum_speed=minimum_speed,
            average_speed=track.length / lap_time if lap_time > 0.0 else 0.0,
            max_lateral_g=max_lateral / 9.80665,
            max_braking_g=max_braking / 9.80665,
            commitment=commitment,
            mistakes=mistakes,
            variation=variation,
            telemetry=telemetry,
            profile=profile,
            final_state=state,
        )

    @staticmethod
    def _accumulate_sectors(
        sector_times: list[float],
        boundaries: list[float],
        start: float,
        length: float,
        speed: float,
        next_speed: float,
        track: Track,
    ) -> None:
        """Split a segment across sector boundaries so the sectors add up."""
        cuts = [0.0]
        for boundary in boundaries:
            if start < boundary < start + length:
                cuts.append((boundary - start) / length)
        cuts.append(1.0)
        squared_start = speed * speed
        squared_delta = next_speed * next_speed - squared_start
        for lower, upper in zip(cuts, cuts[1:]):
            if upper <= lower:
                continue
            v0 = math.sqrt(max(squared_start + squared_delta * lower, 0.0))
            v1 = math.sqrt(max(squared_start + squared_delta * upper, 0.0))
            if v0 + v1 <= 0.0:
                continue
            piece = 2.0 * (upper - lower) * length / (v0 + v1)
            midpoint = start + (lower + upper) * 0.5 * length
            sector_times[track.sector_of(midpoint) - 1] += piece


def simulate_lap(
    track: Track,
    vehicle: Vehicle,
    driver: Driver,
    **kwargs: Any,
) -> LapResult:
    """Convenience wrapper: build a simulator and run one lap."""
    simulator_keys = {"rng", "ambient", "conditions", "config"}
    simulator = LapSimulator(
        track, vehicle, driver,
        **{k: v for k, v in kwargs.items() if k in simulator_keys},
    )
    return simulator.simulate(
        **{k: v for k, v in kwargs.items() if k not in simulator_keys}
    )
