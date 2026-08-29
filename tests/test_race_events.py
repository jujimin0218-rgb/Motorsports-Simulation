"""Race events (project rule 35): what goes wrong, and what is done about it.

Two things are being checked here and they are different.  The *shape* tests
say the model is built out of the right relationships -- a hazard per distance
rather than per lap, contact that needs somebody to fight, a flag that is a
response rather than a cause.  The *envelope* tests say the numbers that come
out land where Formula 1's actually do, which is a thing anybody can look up.
"""

from __future__ import annotations

import math
from dataclasses import replace

import pytest

from f1_race_engine.core.config import default_config
from f1_race_engine.core.rng import RngHub
from f1_race_engine.events import (
    ContactRisk,
    FlagState,
    Incident,
    IncidentKind,
    IncidentSeverity,
    RaceControl,
    contact_probability,
    cooling_stress,
    failure_probability,
    sample_contact,
    sample_failure,
)
from f1_race_engine.events.reliability import SystemStress, stress_from_lap


def _blocking(lap: int = 5, car: int = 1) -> Incident:
    return Incident(
        kind=IncidentKind.MECHANICAL,
        severity=IncidentSeverity.BLOCKING,
        car_number=car,
        lap=lap,
    )


# -- failures are a hazard, not a coin flip ----------------------------------


def test_failure_risk_follows_distance_not_laps():
    """The distinction the whole model rests on.

    A per-lap probability would make Monaco's 78 laps harder on a car than
    Spa's 44, when Spa is the longer race and the harder one on a power unit.
    As a hazard the answer is the same however finely it is sampled.
    """
    once = failure_probability(300_000.0)["power_unit"]
    in_pieces = 1.0
    for _ in range(300):
        in_pieces *= 1.0 - failure_probability(1_000.0)["power_unit"]
    assert once == pytest.approx(1.0 - in_pieces, rel=1e-9)


def test_a_longer_race_breaks_more_cars():
    short = failure_probability(150_000.0)["power_unit"]
    long = failure_probability(305_000.0)["power_unit"]
    assert long > short
    # Sub-linearly, because it is a hazard: a car that has already survived
    # the first half is not twice as likely to break in the second.
    assert long < (305.0 / 150.0) * short


def test_working_a_system_harder_makes_it_more_likely_to_break():
    managed = failure_probability(305_000.0, SystemStress(power_unit=0.9))["power_unit"]
    pushed = failure_probability(305_000.0, SystemStress(power_unit=1.2))["power_unit"]
    assert pushed > managed


def test_stress_comes_from_the_lap_that_was_driven():
    """Nothing per-circuit: a lap that burned more fuel worked the engine
    harder, and that is the whole input."""
    easy = stress_from_lap(fuel_used=2.0, energy_harvested=3.0e6, distance=7000.0)
    hard = stress_from_lap(fuel_used=2.6, energy_harvested=4.5e6, distance=7000.0)
    assert hard.power_unit > easy.power_unit
    assert hard.brakes > easy.brakes


def test_a_hot_race_breaks_more_cars():
    assert cooling_stress(40.0) > cooling_stress(25.0) == 1.0


def test_where_a_car_stops_is_a_separate_question_from_whether_it_stopped():
    """A driver with a warning gets it out of the way; without one, it is left
    where it has to be recovered.  Only the second brings out a flag."""
    seen = set()
    for seed in range(400):
        incident = sample_failure(
            RngHub(seed).stream("h"), car_number=1, lap=1, distance=250_000.0
        )
        if incident is not None:
            seen.add(incident.severity)
    assert seen == {IncidentSeverity.RETIREMENT, IncidentSeverity.BLOCKING}


# -- contact needs somebody to fight -----------------------------------------


def test_a_car_in_clean_air_does_not_hit_anybody():
    assert contact_probability(ContactRisk(laps_in_combat=0.0)) == 0.0


def test_fighting_for_longer_is_riskier():
    brief = contact_probability(ContactRisk(laps_in_combat=3.0))
    long = contact_probability(ContactRisk(laps_in_combat=15.0))
    assert long > brief > 0.0


def test_the_first_lap_is_the_dangerous_one():
    """Twenty cars arriving at the first corner together is where a
    disproportionate share of a season's contact happens."""
    ordinary = contact_probability(ContactRisk(laps_in_combat=1.0))
    opening = contact_probability(ContactRisk(laps_in_combat=1.0, first_lap=True))
    assert opening > 3.0 * ordinary


def test_both_drivers_decide_the_risk():
    """Contact takes two, so a good driver makes it less likely for the pair."""
    reckless = contact_probability(
        ContactRisk(laps_in_combat=10.0, attacker_skill=0.6, rival_skill=0.6)
    )
    careful = contact_probability(
        ContactRisk(laps_in_combat=10.0, attacker_skill=0.98, rival_skill=0.98)
    )
    assert careful < reckless


def test_a_narrow_circuit_is_worse():
    wide = contact_probability(ContactRisk(laps_in_combat=10.0, track_width=15.0))
    narrow = contact_probability(ContactRisk(laps_in_combat=10.0, track_width=9.0))
    assert narrow > wide


def test_contact_leaves_debris_that_has_to_be_picked_up():
    """Separate from whether anybody retired: a front wing shed at speed brings
    out a virtual safety car while its owner drives on to the pits."""
    outcomes = []
    for seed in range(300):
        incident = sample_contact(
            RngHub(seed).stream("c"),
            ContactRisk(laps_in_combat=40.0),
            car_number=1,
            lap=3,
        )
        if incident is not None and not incident.retires:
            outcomes.append(incident.needs_recovery)
    assert any(outcomes) and not all(outcomes)


# -- race control is a response, never a cause -------------------------------


def test_nothing_happening_leaves_the_flag_green():
    control = RaceControl(RngHub(1).stream("rc"))
    for lap in range(1, 20):
        assert control.assess(lap, []).flag is FlagState.GREEN
    assert control.flag is FlagState.GREEN


def test_a_car_stopped_in_a_safe_place_does_not_stop_the_race():
    """Severity is the incident's; the response is race control's."""
    control = RaceControl(RngHub(1).stream("rc"))
    safe = replace(_blocking(), severity=IncidentSeverity.RETIREMENT)
    for lap in range(1, 30):
        control.assess(lap, [safe])
    assert control.flag is FlagState.GREEN


def test_the_response_matches_the_shares_race_control_actually_uses():
    counts = {flag: 0 for flag in FlagState}
    trials = 2000
    for seed in range(trials):
        control = RaceControl(RngHub(seed).stream("rc"))
        control.assess(5, [_blocking()])
        counts[control.flag] += 1
    config = default_config().race_control
    assert counts[FlagState.SAFETY_CAR] / trials == pytest.approx(
        config.safety_car_share, abs=0.04
    )
    assert counts[FlagState.VSC] / trials == pytest.approx(config.vsc_share, abs=0.04)
    assert counts[FlagState.RED_FLAG] / trials == pytest.approx(
        config.red_flag_share, abs=0.03
    )
    # The rest are recovered under a local yellow, which is the commonest
    # answer of all and the one that costs the race nothing.
    assert counts[FlagState.GREEN] / trials > 0.2


def test_a_neutralisation_runs_its_laps_and_then_goes_green():
    control = RaceControl(
        RngHub(3).stream("rc"),
        replace(default_config().race_control, safety_car_share=1.0,
                vsc_share=0.0, red_flag_share=0.0),
    )
    control.assess(5, [_blocking()])
    assert control.flag is FlagState.SAFETY_CAR
    laps = control.laps_remaining
    for lap in range(6, 6 + laps):
        control.assess(lap, [])
    assert control.flag is FlagState.GREEN
    assert any(flag is FlagState.GREEN for _, flag, _ in control.log)


def test_a_safety_car_lap_is_a_different_activity():
    control = RaceControl(
        RngHub(3).stream("rc"),
        replace(default_config().race_control, safety_car_share=1.0,
                vsc_share=0.0, red_flag_share=0.0),
    )
    control.assess(5, [_blocking()])
    behind = control.neutralisation()
    assert behind.pace_factor > 1.3
    assert behind.pit_saving > 0.0
    assert behind.bunches
    assert not behind.racing


def test_the_safety_car_destroys_the_gaps():
    """The single biggest thing that can happen to a race: a thirty-second
    lead is worth one second again."""
    control = RaceControl(RngHub(3).stream("rc"))
    elapsed = {1: 100.0, 2: 130.0, 3: 175.0}
    bunched = control.bunch(elapsed, [1, 2, 3])
    gaps = [bunched[2] - bunched[1], bunched[3] - bunched[2]]
    assert all(gap == pytest.approx(control.config.bunching_gap) for gap in gaps)
    assert bunched[1] == elapsed[1]


def test_one_incident_does_not_cascade_into_overlapping_flags():
    config = replace(default_config().race_control, safety_car_share=1.0,
                     vsc_share=0.0, red_flag_share=0.0)
    control = RaceControl(RngHub(3).stream("rc"), config)
    control.assess(5, [_blocking()])
    deployed = control.laps_remaining
    # More incidents while it is out change nothing about how long it runs.
    for lap in range(6, 6 + deployed):
        control.assess(lap, [_blocking(lap=lap)])
    assert control.flag is FlagState.GREEN


# -- the envelope ------------------------------------------------------------


def test_the_rates_land_where_formula_ones_do():
    """The calibration, against numbers anybody can look up.

    2023: 22 races, 20 cars, about 13% of starts ending in retirement -- split
    roughly evenly between something breaking and somebody hitting somebody --
    a safety car in a little over 40% of races, a virtual one in about half,
    and three red flags in the season.
    """
    config = default_config()
    mechanical = 1.0 - math.prod(
        1.0 - p for p in failure_probability(305_000.0, config=config.reliability).values()
    )
    assert 0.04 < mechanical < 0.09, f"mechanical retirement {mechanical:.1%}"

    incidents = config.incidents
    first_lap = contact_probability(
        ContactRisk(laps_in_combat=1.0, first_lap=True, track_width=10.5), incidents
    )
    rest = contact_probability(
        ContactRisk(laps_in_combat=11.0, track_width=10.5), incidents
    )
    contact = 1.0 - (1.0 - first_lap) * (1.0 - rest)
    ends_it = incidents.retirement_share + incidents.blocking_share
    assert 0.03 < contact * ends_it < 0.09, f"contact retirement {contact * ends_it:.1%}"

    total = 1.0 - (1.0 - mechanical) * (1.0 - contact * ends_it)
    assert 0.08 < total < 0.17, f"total retirement {total:.1%}"

    recoverable = 20.0 * (
        mechanical * config.reliability.stops_on_circuit_share
        + contact * incidents.blocking_share
        + contact * (1.0 - ends_it) * incidents.debris_share
    )
    control = config.race_control
    safety_car = 1.0 - (1.0 - control.safety_car_share) ** recoverable
    virtual = 1.0 - (1.0 - control.vsc_share) ** recoverable
    red = 1.0 - (1.0 - control.red_flag_share) ** recoverable
    assert 0.30 < safety_car < 0.55, f"safety car in {safety_car:.0%} of races"
    assert 0.35 < virtual < 0.65, f"virtual safety car in {virtual:.0%} of races"
    assert 0.06 < red < 0.22, f"red flag in {red:.0%} of races"


# -- damage: the one direction it must never go ------------------------------


def test_damage_never_makes_a_car_faster():
    """The trap the aerodynamic model sets, and the reason it is worth a test.

    Downforce and drag are not independent: ``CdA = CdA_0 + k ClA^2``, so
    taking downforce area away takes induced drag away with it.  Model damage
    as a smaller wing and a car leaves the barrier quicker than it arrived --
    on a power circuit, spectacularly so, because a trimmed-out wing is exactly
    what a power circuit wants.

    A damaged wing is not a trimmed wing.  It is a bluff body with the flow
    separated behind it: the downforce is gone and the drag is not.  So the
    car must be slower everywhere, and slower in a straight line too.
    """
    from dataclasses import replace as _replace

    from f1_race_engine.core.units import ms_to_kph
    from f1_race_engine.physics.speed_profile import compute_speed_profile
    from f1_race_engine.track.io import load_track
    from f1_race_engine.vehicle import Vehicle, VehicleSetup
    from f1_race_engine.vehicle.io import load_builtin_vehicle

    cfg = default_config().incidents
    spec = load_builtin_vehicle("reference_2024")
    wing = 0.7

    def hurt(level: float):
        aero = spec.aero
        kept = 1.0 - cfg.damage_downforce_loss * level
        target = aero.drag_area(wing) * (1.0 + cfg.damage_drag_penalty * level)
        induced = aero.induced_drag_factor * (aero.downforce_area(wing) * kept) ** 2
        return Vehicle(
            _replace(
                spec,
                aero=_replace(
                    aero,
                    min_downforce_area=aero.min_downforce_area * kept,
                    max_downforce_area=aero.max_downforce_area * kept,
                    zero_lift_drag_area=max(
                        target - induced, aero.zero_lift_drag_area
                    ),
                ),
            ),
            VehicleSetup(wing_level=wing),
        )

    for name in ("synthetic_power_circuit", "synthetic_street_circuit"):
        track = load_track(name)

        def lap(car):
            profile = compute_speed_profile(
                track, car, mass=car.total_mass(40.0)
            )
            time = sum(l / s for l, s in zip(profile.length, profile.speed))
            return time, profile.top_speed

        intact_time, intact_top = lap(hurt(0.0))
        previous = intact_time
        for level in (0.3, 0.6, 1.0):
            time, top = lap(hurt(level))
            assert time > previous, f"{name}: damage {level} did not cost time"
            assert top < intact_top, f"{name}: damage {level} raised top speed"
            previous = time

        # And the size is a damaged car's size: seconds, not tenths, and not
        # so much that it could not reach the pits.
        worst, _ = lap(hurt(1.0))
        assert 1.5 < worst - intact_time < 8.0
