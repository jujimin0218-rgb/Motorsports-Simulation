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

import copy
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
from ..environment.conditions import AmbientConditions, headwind_component
from ..physics.longitudinal import longitudinal_forces
from ..physics.speed_profile import SpeedProfile, compute_speed_profile, cornering_limits
from ..track.model import Track
from ..track.surface import TrackConditions
from ..tyres.state import TyreState
from ..vehicle.ers import (
    ErsState,
    deploy_power,
    harvest_power,
    thermal_harvest_power,
)
from ..vehicle.fuel import fuel_burned
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
    fuel_used: float = 0.0
    """Fuel burned over the lap, kg."""

    energy_deployed: float = 0.0
    """Electrical energy sent to the wheels, J."""

    energy_harvested: float = 0.0
    tyre_wear: float = 0.0
    """Fraction of tread used by the end of the lap."""

    tyre_temperature: float = 0.0
    """Tread surface temperature at the end of the lap, degC."""

    tyre_grip: float = 1.0
    """The tyres' grip multiplier at the end of the lap."""

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
            "fuel_used": self.fuel_used,
            "energy_deployed": self.energy_deployed,
            "energy_harvested": self.energy_harvested,
            "tyre_wear": self.tyre_wear,
            "tyre_temperature": self.tyre_temperature,
            "tyre_grip": self.tyre_grip,
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
        "_conditions", "_corners", "_max_curvature", "_accelerating_time",
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
        self._accelerating_time: float | None = None

    def set_conditions(
        self,
        *,
        ambient: AmbientConditions | None = None,
        conditions: TrackConditions | None = None,
    ) -> None:
        """Tell the simulator the world has moved on.

        A session owns the weather and the state of the track surface; the
        simulator only reads them.  Calling this between laps is how a race
        that runs into a shower, or onto a track that has rubbered in, reaches
        the physics -- there is no other path, and in particular no lap-time
        adjustment anywhere.
        """
        if ambient is not None:
            self.ambient = ambient
        if conditions is not None:
            self._conditions = conditions
        # The deployment policy is built from a reference profile; conditions
        # that change the car's pace change how long it spends accelerating.
        self._accelerating_time = None

    def wetness(self) -> float:
        """How wet the circuit is, 0 to 1.

        The share of the lap that has standing water on it.  A damp corner on
        an otherwise dry lap is not a wet race, and this is the number that
        decides how much of a driver's wet-weather ability is being asked for.
        """
        if self._conditions is None:
            return 0.0
        count = len(self._conditions)
        if count == 0:
            return 0.0
        return sum(
            1 for i in range(count) if self._conditions.is_wet(i)
        ) / count

    def accelerating_time(
        self, mass: float | None = None, tyre_state: TyreState | None = None
    ) -> float:
        """Seconds per lap the car spends accelerating.

        Computed from a reference profile with no deployment, once, and cached:
        it barely moves as tyres go off or fuel burns away, and rebuilding a
        profile every lap to refine it would double the cost of a race for no
        measurable gain.
        """
        if self._accelerating_time is not None:
            return self._accelerating_time

        reference = compute_speed_profile(
            self.track, self.vehicle, self.ambient,
            mass=mass if mass is not None else self.vehicle.total_mass(),
            tyre_state=tyre_state, conditions=self._conditions,
            config=self.config.speed_profile,
        )
        total = 0.0
        count = len(reference)
        for index in range(count):
            if reference.longitudinal_acceleration(index) <= 0.0:
                continue
            nxt = (index + 1) % count
            speeds = reference.speed[index] + reference.speed[nxt]
            if speeds > 0.0:
                total += 2.0 * reference.length[index] / speeds
        self._accelerating_time = total
        return total

    def sustainable_ers_power(
        self,
        energy: ErsState,
        mass: float | None = None,
        tyre_state: TyreState | None = None,
    ) -> float:
        """Deployment power that spreads this lap's energy over this lap.

        Deploying greedily empties the store down the first straight and leaves
        nothing for the last one.  The default policy instead decides a budget
        for the lap and spends it evenly across the time the car is
        accelerating.

        The budget is what the car can actually afford: the regulated per-lap
        limit, or what is in the store plus what the previous lap recovered,
        whichever is smaller.  Over a stint that settles by itself into the
        equilibrium every real hybrid runs at -- **you can deploy what you
        recover, and no more** -- rather than emptying the battery on lap one
        and then running flat for the rest of the race.

        Phase 8 replaces this with a strategic policy that puts the energy
        where it is worth most.  The accounting underneath does not change.
        """
        span = self.accelerating_time(mass, tyre_state)
        if span <= 0.0:
            return 0.0
        ers = self.vehicle.spec.ers
        budget = min(
            ers.deployment_limit_per_lap,
            energy.energy_remaining + energy.recovered_last_lap,
        )
        return min(ers.max_deploy_power, max(budget, 0.0) / span)

    # -- the lap -------------------------------------------------------------

    def simulate(
        self,
        *,
        lap: int = 1,
        mass: float | None = None,
        fuel_mass: float | None = None,
        tyre_state: TyreState | None = None,
        ers_state: ErsState | None = None,
        qualifying: bool = False,
        effort: float = 1.0,
        record_telemetry: bool = True,
        telemetry_stride: int = 1,
        start_speed: float | None = None,
    ) -> LapResult:
        """Simulate one lap.

        ``start_speed`` defaults to a flying lap -- the car crosses the line at
        whatever speed the profile says it can carry there.

        ``effort`` is how hard the driver is pushing, 1.0 being flat out.  An
        out-lap, a cool-down lap and a stint being managed to the end all use
        it, and all of them cost time the same way: less grip used, slower lap.
        """
        vehicle, track = self.vehicle, self.track
        if fuel_mass is None:
            fuel_mass = (
                vehicle.setup.fuel_load if mass is None
                else max(mass - vehicle.mass.dry_mass, 0.0)
            )
        car_mass = vehicle.mass.total_mass(fuel_mass) if mass is None else mass
        tyres = tyre_state or TyreState()
        energy = ers_state if ers_state is not None else ErsState(
            energy_remaining=vehicle.spec.ers.capacity
        )
        energy.start_lap()
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
            wetness=self.wetness(),
            effort=effort,
        )
        deploy = self.sustainable_ers_power(energy, car_mass, tyres)
        profile = self._build_profile(
            commitment, variation, mistakes, car_mass, tyres, deploy
        )
        return self._drive(
            profile, commitment, variation, mistakes, lap,
            car_mass, fuel_mass, tyres, energy, deploy, air_density,
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
        ers_power: float,
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
                limits=limits, corner_limit_override=base, ers_power=ers_power,
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
            limits=limits, corner_limit_override=adjusted, ers_power=ers_power,
            config=self.config.speed_profile,
        )

    # -- stage 2: drive it ---------------------------------------------------

    def _available_assist(self, energy: ErsState, speed: float, deploy: float) -> float:
        """Drive force the ERS can add at ``speed``, N.

        Zero once the store or the lap's budget is spent, which is what makes
        the driver settle for the engine alone on the last straight after
        spending everything on the first.
        """
        ers_config = self.config.ers
        if deploy <= 0.0 or speed < ers_config.minimum_deploy_speed:
            return 0.0
        ers = self.vehicle.spec.ers
        remaining = min(
            energy.energy_remaining,
            ers.deployment_limit_per_lap - energy.deployed_this_lap,
        )
        if remaining <= 0.0:
            return 0.0
        return (
            deploy
            * ers_config.deployment_efficiency
            / max(speed, self.config.powertrain.min_tractive_speed)
        )

    def _drive(
        self,
        profile: SpeedProfile,
        commitment: Commitment,
        variation: LapVariation,
        mistakes: tuple[DriverMistake, ...],
        lap: int,
        car_mass: float,
        fuel_mass: float,
        tyres: TyreState,
        energy: ErsState,
        deploy: float,
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

        ers = vehicle.spec.ers
        ers_config = self.config.ers
        fuel_config = self.config.fuel
        fuel_properties = vehicle.spec.fuel
        thermal_config = self.config.tyre_thermal
        wear_config = self.config.tyre_wear
        drivetrain = self.config.powertrain.drivetrain_efficiency
        min_tractive = self.config.powertrain.min_tractive_speed
        management = self.driver.attributes.tyre_management
        air_temperature = self.ambient.air_temperature
        track_temperature = self.ambient.track_temperature
        wind_speed = self.ambient.wind_speed
        wind_direction = self.ambient.wind_direction

        # The lap is planned on the tyre the driver went out on, so it is
        # driven on that tyre too.  The live state goes on heating and wearing
        # underneath -- it is what the *next* lap is planned and driven on, and
        # what the stint report reads -- but grip is held still for the length
        # of one lap.  Letting the plan and the execution disagree is worse than
        # a small lag: a car whose real grip has dropped below its plan simply
        # fails to brake as hard as it intended, carries the extra speed into
        # the corner, and comes out with a *faster* lap for having less grip.
        # Degradation belongs between laps, which is also where a strategist
        # reads it.
        planned = copy.copy(tyres)

        state = VehicleState(
            speed=profile.speed[0] if start_speed is None else start_speed,
            fuel_mass=fuel_mass,
            tyres=tyres,
        )
        telemetry = Telemetry(stride=telemetry_stride) if record_telemetry else None

        boundaries = list(track.sector_boundaries)
        sector_times = [0.0] * (len(boundaries) + 1)
        top_speed = state.speed
        minimum_speed = state.speed
        max_lateral = 0.0
        max_braking = 0.0

        mass = car_mass
        remaining_fuel = fuel_mass
        fuel_used = 0.0
        deployed_before = energy.deployed_total
        recovered_before = energy.recovered_total

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

            # How long the segment lasts at that speed.  This is the figure the
            # energy books use: an electrical force is ``P / v``, so debiting
            # ``P * (ds / v)`` charges exactly the work that force does over the
            # segment, and deployment stays consistent with propulsion no matter
            # how the step is integrated.
            span = step / reference

            lateral_acceleration = reference * reference * abs(curvature)
            lateral_force = mass * lateral_acceleration
            state_here = track.state_at(segment.mid_distance, self._conditions)
            surface_grip = state_here.grip

            common = {
                "mass": mass,
                "gradient": segment.gradient,
                "banking": segment.banking,
                "tyre_state": planned,
                "lateral_acceleration": lateral_acceleration,
                "lateral_force_used": lateral_force,
                "water_depth": state_here.water_depth,
                "headwind": headwind_component(
                    wind_speed, wind_direction, state_here.heading
                ),
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
                mass=mass,
                coast_acceleration=coasting.acceleration,
                powertrain_force=(
                    vehicle.power_unit.tractive_force(reference)
                    + self._available_assist(energy, reference, deploy)
                ),
                brake_system_force=vehicle.brakes.system_limit(),
                curvature=curvature,
                max_curvature=self._max_curvature,
            )

            # Energy out of the store.  Requested in proportion to the pedal, so
            # the debit matches what actually reaches the road; the force model
            # scales what it is handed by the throttle again, so it is given the
            # full-pedal equivalent.
            ers_power = 0.0
            if command.throttle > 0.0 and deploy > 0.0:
                delivered = deploy_power(
                    energy, ers,
                    speed=reference,
                    dt=span,
                    request=deploy * command.throttle / ers.max_deploy_power,
                    config=ers_config,
                )
                ers_power = delivered / command.throttle

            applied = longitudinal_forces(
                vehicle, reference, air_density,
                throttle=command.throttle, brake=command.brake,
                surface_grip=surface_grip
                * (limits.braking if command.is_braking else limits.traction),
                ers_power=ers_power, **common,
            )
            acceleration = applied.acceleration

            squared = speed * speed + 2.0 * acceleration * step
            next_speed = math.sqrt(squared) if squared > 0.0 else floor
            next_speed = max(next_speed, floor)
            dt = 2.0 * step / (speed + next_speed)

            # Fuel burns for the engine's share of the drive force only -- the
            # electrical share is the whole point of a hybrid.  When the tyres
            # cap the drive, both shares are cut in the same proportion.
            burned = 0.0
            if applied.drive > 0.0 and remaining_fuel > 0.0:
                engine_demand = vehicle.power_unit.tractive_force(
                    reference, throttle=command.throttle
                )
                ers_demand = ers_power * command.throttle / max(reference, min_tractive)
                demand = engine_demand + ers_demand
                engine_share = engine_demand / demand if demand > 0.0 else 0.0
                engine_work = applied.drive * engine_share * step
                crank_work = engine_work / drivetrain
                burned = min(
                    fuel_burned(
                        crank_work, dt,
                        properties=fuel_properties, config=fuel_config,
                    ),
                    remaining_fuel,
                )
                remaining_fuel -= burned
                fuel_used += burned
                mass -= burned

                # The exhaust is doing work too, and the turbine takes a share
                # of it back.  This is the recovery that runs while the car is
                # on the throttle, and over a stint it is the larger of the two.
                thermal_harvest_power(
                    energy, ers,
                    engine_power=crank_work / span,
                    dt=span,
                    config=ers_config,
                )

            # Energy back into the store.  Recovery rides along with the brakes
            # rather than replacing them; the MGU-K's power limit is what binds,
            # not the amount of braking on offer.
            if applied.brake > 0.0:
                harvest_power(
                    energy, ers,
                    braking_power=applied.brake * reference,
                    dt=span,
                    config=ers_config,
                )

            # The tyres heat and wear from the friction force they are asked
            # for -- both axes of it, which is why a long corner punishes a set
            # as hard as a heavy braking zone.
            longitudinal_force = max(applied.drive, 0.0) + applied.brake
            tyres.update(
                friction_force=math.hypot(lateral_force, longitudinal_force),
                speed=reference,
                distance=step,
                dt=dt,
                air_temperature=air_temperature,
                track_temperature=track_temperature,
                water_depth=state_here.water_depth,
                tyre_management=management,
                thermal_config=thermal_config,
                wear_config=wear_config,
            )

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
                        fuel_mass=remaining_fuel,
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
            state.fuel_mass = remaining_fuel

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
            fuel_used=fuel_used,
            energy_deployed=energy.deployed_total - deployed_before,
            energy_harvested=energy.recovered_total - recovered_before,
            tyre_wear=tyres.wear,
            tyre_temperature=tyres.surface_temperature,
            tyre_grip=tyres.grip,
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
