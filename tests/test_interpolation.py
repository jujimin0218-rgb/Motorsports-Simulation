"""Profiles must be smooth, bounded and periodic where a lap requires it."""

from __future__ import annotations

import pytest

from f1_race_engine.core.errors import ConfigError
from f1_race_engine.core.interpolation import (
    ConstantProfile,
    PiecewiseProfile,
    clamp,
    inverse_lerp,
    lerp,
    smoothstep,
)


def test_clamp_and_lerp():
    assert clamp(5.0, 0.0, 1.0) == 1.0
    assert clamp(-5.0, 0.0, 1.0) == 0.0
    assert clamp(0.5, 0.0, 1.0) == 0.5
    assert lerp(10.0, 20.0, 0.25) == pytest.approx(12.5)
    assert inverse_lerp(10.0, 20.0, 12.5) == pytest.approx(0.25)
    assert inverse_lerp(10.0, 10.0, 12.5) == 0.0


def test_clamp_rejects_inverted_bounds():
    with pytest.raises(ValueError):
        clamp(1.0, 5.0, 0.0)


def test_smoothstep_is_bounded_and_monotone():
    values = [smoothstep(0.0, 100.0, x) for x in range(-10, 111)]
    assert min(values) == 0.0
    assert max(values) == 1.0
    assert all(b >= a - 1e-12 for a, b in zip(values, values[1:]))


def test_profile_passes_through_its_control_points():
    profile = PiecewiseProfile([(0.0, 0.0), (100.0, 30.0), (250.0, 10.0)])
    assert profile.value(0.0) == pytest.approx(0.0)
    assert profile.value(100.0) == pytest.approx(30.0)
    assert profile.value(250.0) == pytest.approx(10.0)


def test_monotone_cubic_never_overshoots():
    """A hill must not invent a dip that is not in the data."""
    profile = PiecewiseProfile([(0.0, 0.0), (100.0, 30.0), (200.0, 30.0), (300.0, 0.0)])
    samples = [profile.value(x / 10.0) for x in range(3001)]
    assert max(samples) <= 30.0 + 1e-9
    assert min(samples) >= 0.0 - 1e-9


def test_periodic_profile_is_continuous_across_the_seam():
    period = 3000.0
    profile = PiecewiseProfile(
        [(0.0, 0.0), (1000.0, 30.0), (2000.0, 10.0), (period, 0.0)], period=period
    )
    assert profile.value(period - 1e-6) == pytest.approx(profile.value(0.0), abs=1e-4)
    assert profile.derivative(period - 1e-6) == pytest.approx(
        profile.derivative(0.0), abs=1e-6
    )


def test_periodic_profile_has_no_derivative_jumps():
    """Gradient enters the force balance directly, so it must be C1."""
    period = 4800.0
    profile = PiecewiseProfile(
        [(0.0, 0.0), (1200.0, -12.0), (2400.0, 24.0), (3600.0, 6.0), (period, 0.0)],
        period=period,
    )
    step = 0.5
    derivatives = [profile.derivative(i * step) for i in range(int(period / step))]
    jumps = [abs(b - a) for a, b in zip(derivatives, derivatives[1:])]
    assert max(jumps) < 1e-3


def test_periodic_profile_wraps():
    profile = PiecewiseProfile([(0.0, 5.0), (500.0, 15.0)], period=1000.0)
    assert profile.value(1200.0) == pytest.approx(profile.value(200.0))
    assert profile.value(-100.0) == pytest.approx(profile.value(900.0))


def test_closure_mismatch_is_reported_not_hidden():
    profile = PiecewiseProfile([(0.0, 10.0), (3000.0, 25.0)], period=3000.0)
    assert profile.closure_mismatch == pytest.approx(15.0)


def test_non_periodic_profile_clamps_outside_its_range():
    profile = PiecewiseProfile([(0.0, 5.0), (100.0, 9.0)])
    assert profile.value(-50.0) == pytest.approx(5.0)
    assert profile.value(500.0) == pytest.approx(9.0)
    assert profile.derivative(-50.0) == 0.0


def test_linear_method_matches_hand_calculation():
    profile = PiecewiseProfile([(0.0, 0.0), (100.0, 10.0)], method="linear")
    assert profile.value(25.0) == pytest.approx(2.5)
    assert profile.derivative(25.0) == pytest.approx(0.1)


def test_step_method_holds_its_value():
    profile = PiecewiseProfile([(0.0, 1.0), (100.0, 2.0)], method="step")
    assert profile.value(99.0) == 1.0
    assert profile.value(100.0) == 2.0
    assert profile.derivative(50.0) == 0.0


def test_constant_profile():
    profile = ConstantProfile(13.0)
    assert profile.value(-1e6) == 13.0
    assert profile.value(1e6) == 13.0
    assert profile.derivative(42.0) == 0.0


def test_empty_and_duplicate_control_points_are_rejected():
    with pytest.raises(ConfigError):
        PiecewiseProfile([])
    with pytest.raises(ConfigError):
        PiecewiseProfile([(0.0, 1.0), (0.0, 2.0)])


def test_control_points_spanning_more_than_the_period_are_rejected():
    with pytest.raises(ConfigError):
        PiecewiseProfile([(0.0, 1.0), (5000.0, 2.0)], period=1000.0)
