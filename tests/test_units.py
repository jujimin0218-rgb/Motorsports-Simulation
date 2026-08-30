"""SI conventions and the conversion layer (project rule 38)."""

from __future__ import annotations

import math

import pytest

from f1_race_engine.core import units as u
from f1_race_engine.core.errors import UnitError


@pytest.mark.parametrize(
    ("to_si", "from_si", "value"),
    [
        (u.kph_to_ms, u.ms_to_kph, 342.0),
        (u.mph_to_ms, u.ms_to_mph, 212.5),
        (u.km_to_m, u.m_to_km, 5.793),
        (u.deg_to_rad, u.rad_to_deg, 137.5),
        (u.g_to_ms2, u.ms2_to_g, 5.2),
        (u.hp_to_w, u.w_to_hp, 1000.0),
        (u.kw_to_w, u.w_to_kw, 735.0),
        (u.mj_to_j, u.j_to_mj, 4.0),
        (u.celsius_to_kelvin, u.kelvin_to_celsius, 42.5),
        (u.bar_to_pa, u.pa_to_bar, 1.9),
        (u.psi_to_pa, u.pa_to_psi, 23.0),
        (u.gradient_from_percent, u.percent_from_gradient, 17.5),
    ],
)
def test_conversions_round_trip(to_si, from_si, value):
    assert from_si(to_si(value)) == pytest.approx(value, rel=1e-12)


def test_known_conversion_values():
    assert u.kph_to_ms(360.0) == pytest.approx(100.0)
    assert u.ms_to_kph(100.0) == pytest.approx(360.0)
    assert u.g_to_ms2(1.0) == pytest.approx(u.STANDARD_GRAVITY)
    assert u.celsius_to_kelvin(0.0) == pytest.approx(273.15)
    assert u.bar_to_pa(1.0) == pytest.approx(1e5)


def test_curvature_and_radius_are_inverse():
    assert u.curvature_from_radius(50.0) == pytest.approx(0.02)
    assert u.radius_from_curvature(0.02) == pytest.approx(50.0)
    # Sign is preserved: negative radius is a right-hand corner.
    assert u.curvature_from_radius(-50.0) == pytest.approx(-0.02)


def test_straight_has_zero_curvature_and_infinite_radius():
    assert u.curvature_from_radius(1e9) == 0.0
    assert math.isinf(u.radius_from_curvature(0.0))


def test_zero_radius_is_rejected():
    with pytest.raises(UnitError):
        u.curvature_from_radius(0.0)


def test_wrap_angle():
    assert u.wrap_angle(0.0) == pytest.approx(0.0)
    assert u.wrap_angle(math.tau) == pytest.approx(0.0, abs=1e-12)
    assert u.wrap_angle(3 * math.pi) == pytest.approx(math.pi)
    assert abs(u.wrap_angle(math.pi * 1.5)) <= math.pi


@pytest.mark.parametrize(
    ("seconds", "text"),
    [(81.345, "1:21.345"), (59.999, "0:59.999"), (0.5, "0:00.500"), (135.0, "2:15.000")],
)
def test_lap_time_formatting(seconds, text):
    assert u.format_lap_time(seconds) == text
    assert u.parse_lap_time(text) == pytest.approx(seconds)


def test_lap_time_rounding_does_not_produce_sixty_seconds():
    assert u.format_lap_time(59.9999) == "1:00.000"


def test_parse_lap_time_accepts_bare_seconds():
    assert u.parse_lap_time("81.345") == pytest.approx(81.345)


def test_parse_lap_time_rejects_nonsense():
    with pytest.raises(UnitError):
        u.parse_lap_time("not a lap time")


def test_format_gap():
    assert u.format_gap(0.234) == "+0.234"
    assert u.format_gap(-1.5) == "-1.500"
    assert u.format_gap(75.5) == "+1:15.500"


def test_infinite_lap_time_is_rendered_not_crashed():
    assert u.format_lap_time(math.inf) == "--:--.---"
