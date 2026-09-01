"""Choosing a line, and what it costs.

The claim being tested is that racecraft here is geometry rather than a rule:
nothing in this file asserts that defending is slower *because defending is
slower*, only that the inside of a corner is a tighter path and that a tighter
path is a lower speed.
"""

from __future__ import annotations

import pytest

from f1_race_engine import load_track
from f1_race_engine.race.racecraft import (
    LEAST,
    MARGIN,
    MOST,
    STRAIGHT,
    bias_of_offset,
    corner_scale,
    holds_the_line,
)
from f1_race_engine.world import world_for


@pytest.fixture(scope="module")
def lines():
    world = world_for(load_track("bahrain"))
    assert world.lines is not None
    return world.lines


# -- what a line is worth ----------------------------------------------------


def test_the_same_radius_costs_nothing():
    assert corner_scale(0.02, 0.02) == pytest.approx(1.0)


def test_a_tighter_line_is_slower():
    """Half the radius is 1/sqrt(2) of the speed, which is the whole model."""
    assert corner_scale(0.01, 0.02) == pytest.approx(1.0 / 2.0**0.5, rel=1e-6)


def test_a_wider_line_is_quicker():
    assert corner_scale(0.02, 0.01) > 1.0


def test_moving_across_a_straight_costs_nothing():
    """The trap this walked into once: a straight has no radius to be worse
    than, and dividing two near-zero curvatures had cars crawling down it."""
    assert corner_scale(STRAIGHT / 100.0, STRAIGHT * 5.0) == 1.0
    assert corner_scale(0.0, 0.001) == 1.0


def test_the_price_is_bounded_either_way():
    assert corner_scale(1.0, 1e-3) == MOST
    assert corner_scale(1e-3, 1.0) == LEAST


# -- reading a line off a place across the road ------------------------------


def test_sitting_on_the_racing_line_is_no_bias(lines):
    index = 200
    assert bias_of_offset(lines, index, lines.optimal.offsets[index]) == pytest.approx(
        0.0
    )


def test_the_inside_and_outside_lines_read_back_as_plus_and_minus_one(lines):
    index = 200
    assert bias_of_offset(lines, index, lines.inside_edge[index]) == pytest.approx(
        1.0, abs=1e-6
    )
    assert bias_of_offset(lines, index, lines.outside_edge[index]) == pytest.approx(
        -1.0, abs=1e-6
    )


def test_bias_and_offset_are_inverses(lines):
    for index in (10, 200, 640, 1000):
        for bias in (-1.0, -0.4, 0.0, 0.3, 1.0):
            offset = lines.at(index, bias)
            assert bias_of_offset(lines, index, offset) == pytest.approx(bias, abs=1e-6)


def test_a_car_shoved_past_the_edge_is_still_read_as_on_the_edge(lines):
    """Clamped rather than extrapolated: what happens to a car beyond the road
    is the world layer's business, not the line's."""
    index = 200
    far = lines.inside_edge[index] * 4.0 + 10.0
    assert abs(bias_of_offset(lines, index, far)) <= 1.0


# -- holding it, or not ------------------------------------------------------


def test_a_car_on_the_line_it_planned_for_holds_it():
    assert holds_the_line(1.0, 1.0, racecraft=0.5)


def test_a_wider_line_than_planned_is_always_held():
    """Backing out of a move is never what puts a car off the road."""
    assert holds_the_line(0.9, 1.0, racecraft=0.0)


def test_a_slightly_tighter_line_comes_off():
    assert holds_the_line(1.0, 1.0 - MARGIN / 2.0, racecraft=0.5)


def test_a_much_tighter_line_does_not():
    assert not holds_the_line(1.0, 1.0 - MARGIN * 3.0, racecraft=0.5)


def test_the_better_racer_gets_away_with_more():
    """The difference between drivers is who can pull a late move off -- not
    what happens when the move is beyond them."""
    asking = 1.0 - MARGIN * 1.2
    assert holds_the_line(1.0, asking, racecraft=1.0)
    assert not holds_the_line(1.0, asking, racecraft=0.0)


def test_nobody_holds_a_line_far_beyond_them():
    for racecraft in (0.0, 0.5, 1.0):
        assert not holds_the_line(1.0, 0.5, racecraft=racecraft)


# -- the mechanism, in a race ------------------------------------------------


def test_a_race_prices_the_lines_its_cars_choose(street_track, small_field):
    """The integration claim: cars in traffic leave the racing line, are
    charged a radius for it, and sometimes ask for more than they have.

    Run on a circuit with nowhere to overtake, so the field spends the race
    close together and the racing logic is actually exercised.  Asserted as
    "this happens at all" rather than as counts: how often is a property of
    the circuit and the drivers, and pinning it would make the test a record
    of one seed rather than of the mechanism.
    """
    from f1_race_engine.core.rng import RngHub
    from f1_race_engine.race import RaceSession
    from f1_race_engine.race.traffic import Traffic

    seen: list[tuple[float, float, bool]] = []
    original = Traffic.at

    def watch(self, **kwargs):
        state = original(self, **kwargs)
        seen.append((state.bias, state.corner_scale, state.ran_wide))
        return state

    Traffic.at = watch
    try:
        RaceSession(street_track, small_field, laps=3, rng=RngHub(5)).run()
    finally:
        Traffic.at = original

    assert seen, "no car ever asked the road what was going on"
    assert any(abs(bias) > 0.1 for bias, _, _ in seen), "nobody left the racing line"
    assert any(scale < 1.0 for _, scale, _ in seen), "leaving it never cost anything"
    assert all(LEAST <= scale <= MOST for _, scale, _ in seen)


def test_the_leader_in_clear_air_is_never_charged_for_a_line(fast_track, small_field):
    """The safety property, from the other end: a car with nobody near it
    drives the racing line, so its lap is the one the engine always gave."""
    from f1_race_engine.core.rng import RngHub
    from f1_race_engine.race import RaceSession
    from f1_race_engine.race.traffic import Traffic

    on_the_line: list[float] = []
    original = Traffic.at

    def watch(self, **kwargs):
        state = original(self, **kwargs)
        # Clean air and on the line: the two conditions under which a car is
        # driving the lap the engine has always given it.
        if state.wake.downforce_factor >= 1.0 and abs(state.bias) < 0.02:
            on_the_line.append(state.corner_scale)
        return state

    Traffic.at = watch
    try:
        RaceSession(fast_track, small_field, laps=2, rng=RngHub(5)).run()
    finally:
        Traffic.at = original

    assert on_the_line, "nobody ever ran on the racing line in clean air"
    # Not exactly one: "on the line" here means within two per cent of it,
    # because a car easing back on after a move is still essentially on it.
    # What matters is that the number is a rounding error rather than a
    # charge -- a hundredth of a per cent, against the eight per cent that
    # holding the inside of a corner costs.
    for scale in on_the_line:
        assert scale == pytest.approx(1.0, abs=1e-3)
