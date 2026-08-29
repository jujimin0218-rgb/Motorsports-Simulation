"""The gearbox and the engine curve behind it (Phase 12).

Phase 2 stood in for all of this with a peak wheel torque and a flat cap, and
said in its own docstring that Phase 12 would replace it.  These tests are what
"replace" has to mean: force that varies within a gear, a top speed that is a
ratio rather than a balance of forces, and a shift that costs time.
"""

from __future__ import annotations

import math
from dataclasses import replace

import pytest

from f1_race_engine.core.errors import ConfigError
from f1_race_engine.vehicle.gearbox import Gearbox, GearboxProperties
from f1_race_engine.vehicle.power_unit import PowerUnit, PowerUnitProperties

WHEEL = 0.36


@pytest.fixture
def gearbox() -> Gearbox:
    return Gearbox(GearboxProperties(), WHEEL)


# -- the engine curve --------------------------------------------------------


def test_the_power_curve_looks_like_a_power_unit(gearbox):
    """Rising steeply, peaking where it is designed to, easing off after.

    The numbers are what a modern Formula 1 power unit does, and they matter
    beyond realism: the rising side is what decides which gear the car is in.
    """
    assert gearbox.power_fraction(6_000.0) == pytest.approx(0.41, abs=0.06)
    assert gearbox.power_fraction(8_000.0) == pytest.approx(0.65, abs=0.06)
    assert gearbox.power_fraction(10_500.0) == pytest.approx(1.0, abs=1e-9)
    assert gearbox.power_fraction(15_000.0) == pytest.approx(0.93, abs=0.02)


def test_power_peaks_once(gearbox):
    samples = [gearbox.power_fraction(rpm) for rpm in range(4_000, 15_001, 250)]
    peak = max(samples)
    at = samples.index(peak)
    assert all(b >= a for a, b in zip(samples[:at], samples[1 : at + 1]))
    assert all(b <= a for a, b in zip(samples[at:], samples[at + 1 :]))


# -- ratios ------------------------------------------------------------------


def test_each_gear_runs_faster_than_the_one_below(gearbox):
    speeds = [gearbox.speed_at_limit(g) for g in range(1, gearbox.properties.gears + 1)]
    assert all(b > a for a, b in zip(speeds, speeds[1:]))


def test_top_gear_is_the_car_ceiling(gearbox):
    """Top speed is a gear, not a balance of forces.

    It is why a Formula 1 car at Monza sits on the limiter rather than creeping
    towards a terminal velocity, and why DRS there buys nothing at all.
    """
    ceiling = gearbox.maximum_speed
    assert 90.0 < ceiling < 105.0  # 325-378 km/h
    assert gearbox.tractive_force(ceiling * 0.99, 540_000.0) > 0.0
    assert gearbox.tractive_force(ceiling * 1.01, 540_000.0) == 0.0


def test_the_gear_chosen_keeps_the_engine_near_its_peak(gearbox):
    """Force at a road speed is ``P / v`` whatever the ratio, so the gear that
    wins is the one putting the engine nearest its power peak.  That is what a
    shift map is, and it is why the answer looks like real telemetry."""
    for speed_kph, expected in ((120, 3), (160, 5), (200, 6), (300, 8)):
        selection = gearbox.select(speed_kph / 3.6, 540_000.0)
        assert abs(selection.gear - expected) <= 1, (
            f"{speed_kph} km/h chose gear {selection.gear}, expected about {expected}"
        )


def test_the_engine_stays_inside_its_rev_range(gearbox):
    for speed_kph in range(40, 350, 10):
        selection = gearbox.select(speed_kph / 3.6, 540_000.0)
        assert selection.rpm <= gearbox.properties.rev_limit + 1e-6


# -- shifting costs time -----------------------------------------------------


def test_a_short_gear_loses_more_to_its_own_shift(gearbox):
    """A fixed time with no drive costs a gear that is over in a second far
    more of itself than one held down a straight."""
    properties = gearbox.properties
    short = properties.shift_time / (
        (gearbox.speed_at_limit(2) - gearbox.speed_at_limit(1))
        / properties.reference_acceleration
    )
    long = properties.shift_time / (
        (gearbox.speed_at_limit(7) - gearbox.speed_at_limit(6))
        / properties.reference_acceleration
    )
    assert short > long > 0.0


def test_top_gear_pays_nothing_for_shifting(gearbox):
    """There is no gear above it to change into."""
    top = gearbox.properties.gears
    speed = 0.95 * gearbox.speed_at_limit(top)
    selection = gearbox.select(speed, 540_000.0)
    assert selection.gear == top
    assert selection.force == pytest.approx(selection.power / speed)


# -- what the rest of the engine sees ----------------------------------------


def test_the_power_unit_runs_through_the_gearbox():
    unit = PowerUnit(PowerUnitProperties())
    assert unit.maximum_speed == pytest.approx(
        Gearbox(PowerUnitProperties().gearbox, WHEEL).maximum_speed
    )
    assert unit.tractive_force(unit.maximum_speed * 1.05) == 0.0
    assert unit.tractive_force(unit.peak_force_speed) > 0.0


def test_gearing_is_a_setup_decision():
    """A longer top gear buys a higher ceiling and gives up the road below it.

    The trade is at the ends rather than in the middle: with eight ratios
    covering the range, both gearings can find one near the power peak at any
    ordinary speed, and force at a road speed is ``P / v`` whatever the ratio.
    Where they differ is where each one runs out -- which is exactly the choice
    a low-drag circuit asks a team to make.
    """
    short = GearboxProperties(ratios=tuple(r * 1.10 for r in GearboxProperties().ratios))
    long = GearboxProperties(ratios=tuple(r * 0.92 for r in GearboxProperties().ratios))
    geared_short = Gearbox(short, WHEEL)
    geared_long = Gearbox(long, WHEEL)

    assert geared_long.maximum_speed > geared_short.maximum_speed
    # Past the short box's ceiling it has nothing left and the long one is
    # still pulling.
    beyond = geared_short.maximum_speed * 1.02
    assert geared_short.tractive_force(beyond, 540_000.0) == 0.0
    assert geared_long.tractive_force(beyond, 540_000.0) > 0.0
    # And low down, the short box has the engine further up its curve.
    crawl = 40.0 / 3.6
    assert geared_short.tractive_force(crawl, 540_000.0) > geared_long.tractive_force(
        crawl, 540_000.0
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"ratios": (5.0,)},
        {"ratios": (5.0, 8.0)},
        {"ratios": (8.0, -1.0)},
        {"rev_limit": 9_000.0},
        {"shift_time": -0.01},
        {"reference_acceleration": 0.0},
    ],
)
def test_an_impossible_gearbox_is_rejected(kwargs):
    with pytest.raises(ConfigError):
        GearboxProperties(**kwargs)


def test_a_gearbox_round_trips_through_plain_data():
    properties = GearboxProperties(ratios=(16.0, 13.0, 11.0, 9.5, 8.2, 7.0, 6.1, 5.4))
    assert GearboxProperties.from_dict(properties.to_dict()) == properties
