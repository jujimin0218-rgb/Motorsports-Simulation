"""The lap: time, sectors, zones, and the tests project rule 40 asks for."""

from __future__ import annotations

import math
from dataclasses import replace

import pytest

from f1_race_engine.core.config import TrackBuildConfig
from f1_race_engine.core.units import ms_to_kph
from f1_race_engine.physics import compute_lap_time, format_lap_result
from f1_race_engine.physics.speed_profile import PerformanceLimits
from f1_race_engine.track.builder import build_track
from f1_race_engine.tyres import TyreState
from f1_race_engine.vehicle import MEDIUM_DOWNFORCE, Vehicle


# -- the lap itself ----------------------------------------------------------


def test_lap_time_is_plausible(fast_lap):
    """The reference circuit, against the range the calendar spans.

    Average speed is the measure circuits are described by, and Formula 1
    spans roughly 170 km/h at Monaco to 265 km/h at Monza.  A reference
    circuit of every corner speed belongs in the middle of that.
    """
    assert 55.0 < fast_lap.lap_time < 110.0
    assert 165.0 < fast_lap.average_speed_kph < 270.0


def test_sector_times_sum_to_the_lap_time(fast_lap):
    assert sum(fast_lap.sector_times) == pytest.approx(fast_lap.lap_time, abs=1e-9)
    assert len(fast_lap.sector_times) == 3
    assert all(sector > 0.0 for sector in fast_lap.sector_times)


def test_average_speed_matches_distance_over_time(fast_lap):
    assert fast_lap.average_speed == pytest.approx(
        fast_lap.lap_length / fast_lap.lap_time
    )


def test_speed_extremes_come_from_the_profile(fast_lap):
    assert fast_lap.top_speed == fast_lap.profile.top_speed
    assert fast_lap.minimum_speed == fast_lap.profile.minimum_speed
    assert fast_lap.minimum_speed < fast_lap.top_speed


def test_accelerations_are_physically_sane(fast_lap):
    assert 2.0 < fast_lap.max_lateral_g < 7.0
    assert 2.0 < fast_lap.max_braking_g < 7.0
    assert 0.3 < fast_lap.max_acceleration_g < 2.0


def test_lap_composition_adds_up(fast_lap):
    assert 0.0 < fast_lap.braking_fraction < 0.5
    assert 0.4 < fast_lap.full_throttle_fraction < 1.0


def test_energy_and_power_are_consistent(fast_lap):
    assert fast_lap.energy_delivered > 0.0
    assert fast_lap.mean_power == pytest.approx(
        fast_lap.energy_delivered / fast_lap.lap_time
    )
    # A lap cannot average more than the engine can make.
    assert fast_lap.mean_power < 560_000.0


def test_lap_time_is_deterministic(fast_track, reference_spec):
    """Rule 40, Test A, at the lap level."""
    car = Vehicle(reference_spec, MEDIUM_DOWNFORCE)
    first = compute_lap_time(fast_track, car, analyse_zones=False)
    second = compute_lap_time(fast_track, car, analyse_zones=False)
    assert first.lap_time == second.lap_time
    assert first.profile.speed == second.profile.speed


# -- rule 40 -----------------------------------------------------------------


def test_c_a_faster_car_gives_a_faster_lap(fast_track, reference_spec):
    """Rule 40, Test C -- only testable once there is a lap."""
    car = Vehicle(reference_spec, MEDIUM_DOWNFORCE)
    stronger = car.with_spec(
        replace(
            reference_spec,
            power_unit=replace(
                reference_spec.power_unit,
                max_power=reference_spec.power_unit.max_power * 1.15,
            ),
        )
    )
    base = compute_lap_time(fast_track, car, analyse_zones=False)
    quick = compute_lap_time(fast_track, stronger, analyse_zones=False)
    assert quick.lap_time < base.lap_time
    assert quick.top_speed > base.top_speed


def test_d_more_grip_gives_a_faster_lap(fast_track, reference_spec, compounds):
    car = Vehicle(reference_spec, MEDIUM_DOWNFORCE)
    soft = compute_lap_time(
        fast_track, car, tyre_state=TyreState(compound=compounds["S"]),
        analyse_zones=False,
    )
    hard = compute_lap_time(
        fast_track, car, tyre_state=TyreState(compound=compounds["H"]),
        analyse_zones=False,
    )
    assert soft.lap_time < hard.lap_time


def test_more_mass_gives_a_slower_lap(fast_track, reference_spec):
    car = Vehicle(reference_spec, MEDIUM_DOWNFORCE)
    light = compute_lap_time(fast_track, car, mass=800.0, analyse_zones=False)
    heavy = compute_lap_time(fast_track, car, mass=950.0, analyse_zones=False)
    assert heavy.lap_time > light.lap_time


def test_fuel_costs_a_realistic_amount_of_lap_time(reference_spec,
                                                   coarse_build_config):
    """Every circuit must charge roughly what the sport charges for fuel.

    Teams work in seconds per kilogram, and across the calendar the number
    sits between about 0.024 and 0.041 s/kg.  It is the one mass figure that
    can be checked against the outside world, and it falls out of the force
    balance rather than being set anywhere.

    Deliberately *not* asserted: that a slow circuit charges more than a fast
    one.  Published figures say it does, but they are derived from long runs
    and carry tyre degradation with them; on a single lap at a fixed tyre
    state the model says the circuits are close together, and the physics
    agrees -- mass cancels out of low-speed cornering almost exactly.
    """
    from f1_race_engine.track.io import load_builtin_definition

    car = Vehicle(reference_spec, MEDIUM_DOWNFORCE)
    for name in (
        "synthetic_power_circuit",
        "synthetic_proving_ground",
        "synthetic_street_circuit",
    ):
        track = build_track(load_builtin_definition(name), coarse_build_config)
        base = compute_lap_time(track, car, analyse_zones=False).lap_time
        heavy = compute_lap_time(
            track, car, mass=car.total_mass() + 50.0, analyse_zones=False
        ).lap_time
        per_kg = (heavy - base) / 50.0
        assert 0.015 < per_kg < 0.050, f"{name}: {per_kg:.4f} s/kg"


def test_a_less_committed_driver_is_slower(fast_track, reference_spec):
    car = Vehicle(reference_spec, MEDIUM_DOWNFORCE)
    ideal = compute_lap_time(fast_track, car, analyse_zones=False)
    timid = compute_lap_time(
        fast_track, car, limits=PerformanceLimits(cornering=0.95, braking=0.95),
        analyse_zones=False,
    )
    assert timid.lap_time > ideal.lap_time


# -- resolution independence -------------------------------------------------


def test_lap_time_converges_with_track_resolution(proving_ground_definition,
                                                  reference_spec):
    """The Phase 3 counterpart of Phase 1's resolution test.

    A lap time that depended on how finely the circuit happened to be sampled
    would make every later result meaningless.
    """
    car = Vehicle(reference_spec, MEDIUM_DOWNFORCE)

    # A *uniform* refinement ladder: every criterion is tightened by the same
    # factor at each step.  Mixing a coarse corner setting with a fine straight
    # one gives a sequence that is not ordered by resolution at all, and then
    # "does it converge" has no meaning to test.
    def ladder(scale: float) -> TrackBuildConfig:
        return TrackBuildConfig(
            straight_segment_length=30.0 * scale,
            corner_segment_length=20.0 * scale,
            min_segment_length=max(0.5, 5.0 * scale),
            max_segment_length=30.0 * scale,
            max_heading_change_per_segment_deg=8.0 * scale,
            max_curvature_change_per_segment=0.01 * scale,
        )

    times = []
    counts = []
    for scale in (1.0, 0.5, 0.25, 0.125):
        track = build_track(proving_ground_definition, ladder(scale))
        counts.append(len(track))
        times.append(compute_lap_time(track, car, analyse_zones=False).lap_time)

    assert counts[-1] > 4 * counts[0]  # the sampling really did change
    spread = max(times) - min(times)
    assert spread < 0.05, f"lap times {times} span {spread:.4f} s"

    # And it converges rather than wandering.  Stated as "the refinement stops
    # mattering" rather than "every step is smaller than the last": once the
    # whole spread is down at a hundredth of a second the individual steps are
    # noise, and demanding monotonicity there tests the noise.
    steps = [abs(b - a) for a, b in zip(times, times[1:])]
    assert steps[-1] <= steps[0], (
        f"lap times {times} changed by {steps} -- the refinements are growing"
    )
    assert steps[-1] < 0.01, (
        f"doubling the resolution again still moved the lap by {steps[-1]:.4f} s"
    )


# -- zones -------------------------------------------------------------------


def test_braking_zones_are_found(fast_lap):
    zones = fast_lap.braking_zones
    assert zones
    for zone in zones:
        assert zone.entry_speed > zone.exit_speed
        assert zone.length > 0.0
        assert zone.peak_deceleration_g > 1.0
        assert zone.duration > 0.0


def test_braking_zones_serve_corners(fast_lap):
    assert all(zone.corner_id is not None for zone in fast_lap.braking_zones)


def test_the_heaviest_braking_ends_at_a_slow_corner(fast_lap):
    """The biggest stop must arrive somewhere slow.

    Not necessarily the *slowest* corner: that is a fact about one circuit
    rather than about braking.  A slow corner at the end of a short link is
    reached with a small stop, while the heaviest braking of the lap is
    wherever the longest straight happens to end -- which at Silverstone is
    Stowe and not the Loop.
    """
    heaviest = max(fast_lap.braking_zones, key=lambda z: z.entry_speed - z.exit_speed)
    assert heaviest.exit_speed < 0.5 * fast_lap.top_speed
    assert heaviest.entry_speed - heaviest.exit_speed > 0.3 * fast_lap.top_speed


def test_the_slowest_corner_is_braked_for(fast_lap):
    """Whatever the slowest point of the lap is, the car had to stop for it."""
    slowest = min(
        fast_lap.braking_zones, key=lambda z: z.exit_speed
    )
    assert slowest.exit_speed == pytest.approx(fast_lap.minimum_speed, rel=0.10)


def test_acceleration_zones_are_found(fast_lap):
    zones = fast_lap.acceleration_zones
    assert zones
    for zone in zones:
        assert zone.exit_speed > zone.entry_speed
        assert zone.peak_acceleration_g > 0.0


def test_slow_corner_exits_are_traction_limited(fast_lap):
    """Project rule 17: corner exit and straight-line acceleration differ."""
    slowest = min(fast_lap.acceleration_zones, key=lambda z: z.entry_speed)
    fastest = max(fast_lap.acceleration_zones, key=lambda z: z.entry_speed)
    assert slowest.traction_limited_length > 0.0
    assert slowest.traction_limited_length >= fastest.traction_limited_length


def test_zones_do_not_overlap(fast_lap):
    for a, b in zip(fast_lap.braking_zones, fast_lap.braking_zones[1:]):
        assert b.start_distance >= a.end_distance - 1e-6


def test_zone_analysis_can_be_skipped(fast_track, reference_spec):
    result = compute_lap_time(
        fast_track, Vehicle(reference_spec, MEDIUM_DOWNFORCE), analyse_zones=False
    )
    assert result.braking_zones == ()
    assert result.acceleration_zones == ()


# -- output ------------------------------------------------------------------


def test_export_is_json_serialisable(fast_lap):
    import json

    json.dumps(fast_lap.to_dict())
    json.dumps(fast_lap.to_dict(include_profile=True))


def test_formatted_report(fast_lap):
    text = format_lap_result(fast_lap)
    assert "LAP" in text
    assert fast_lap.formatted in text
    assert "BRAKING ZONES" in text
    assert "ACCELERATION ZONES" in text


def test_lap_time_formatting(fast_lap):
    assert ":" in fast_lap.formatted
    from f1_race_engine.core.units import parse_lap_time

    assert parse_lap_time(fast_lap.formatted) == pytest.approx(
        fast_lap.lap_time, abs=0.001
    )


def test_reusing_a_profile_gives_the_same_lap(fast_track, reference_spec):
    car = Vehicle(reference_spec, MEDIUM_DOWNFORCE)
    first = compute_lap_time(fast_track, car)
    again = compute_lap_time(fast_track, car, profile=first.profile)
    assert again.lap_time == pytest.approx(first.lap_time)


# -- what the limit lap is, and is not ---------------------------------------


def test_the_default_limit_lap_is_the_chassis_limit(fast_track, reference_spec):
    """ERS shut, DRS shut: what the car is worth before anything is spent.

    Deployment is a decision rather than a property, and it is one the car
    cannot make everywhere at once -- the store holds a lap's worth and no
    more.  So Phase 3 answers the question without it, and says so.
    """
    car = Vehicle(reference_spec, MEDIUM_DOWNFORCE)
    shut = compute_lap_time(fast_track, car)
    deployed = compute_lap_time(
        fast_track, car, ers_power=reference_spec.ers.max_deploy_power
    )
    assert deployed.lap_time < shut.lap_time

    # And the difference is the size ERS actually is: seconds, not tenths.
    assert 1.0 < shut.lap_time - deployed.lap_time < 6.0


def test_a_driven_lap_lands_between_the_two_limits(fast_track, reference_spec):
    """The ordering that says the phases are wired to each other correctly.

    A real qualifying lap beats the chassis limit, because the driver deploys.
    It does not beat the deployed limit, because nobody is perfect.  If either
    half of that failed, a driver would be either leaving ERS on the table or
    exceeding the grip the tyres have -- and both are bugs, not driving.
    """
    from f1_race_engine.core.rng import RngHub
    from f1_race_engine.driver.io import load_builtin_driver
    from f1_race_engine.simulation.lap import LapSimulator

    car = Vehicle(reference_spec, MEDIUM_DOWNFORCE)
    shut = compute_lap_time(fast_track, car, mass=car.total_mass(30.0))
    deployed = compute_lap_time(
        fast_track,
        car,
        mass=car.total_mass(30.0),
        ers_power=reference_spec.ers.max_deploy_power,
    )
    driven = LapSimulator(
        track=fast_track,
        vehicle=car,
        driver=load_builtin_driver("01_benchmark"),
        rng=RngHub(5),
    ).simulate(fuel_mass=30.0, qualifying=True, record_telemetry=False)

    assert deployed.lap_time < driven.lap_time < shut.lap_time
