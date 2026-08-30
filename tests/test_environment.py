"""Ambient conditions and air density."""

from __future__ import annotations

import pytest

from f1_race_engine.core.errors import ConfigError
from f1_race_engine.environment import (
    AmbientConditions,
    air_density,
    saturation_vapour_pressure,
)


def test_isa_sea_level_density():
    """15 degC, 1013.25 hPa, dry -- the textbook 1.225 kg/m^3."""
    assert air_density(15.0, 101_325.0, 0.0) == pytest.approx(1.225, abs=0.001)


def test_density_falls_with_temperature():
    values = [air_density(t, 101_325.0, 0.0) for t in (0.0, 15.0, 30.0, 45.0)]
    assert all(b < a for a, b in zip(values, values[1:]))


def test_density_rises_with_pressure():
    low = air_density(25.0, 95_000.0, 0.0)
    high = air_density(25.0, 105_000.0, 0.0)
    assert high > low


def test_moist_air_is_less_dense_than_dry_air():
    """Counter-intuitive but real: water vapour is lighter than the nitrogen
    and oxygen it displaces."""
    dry = air_density(30.0, 101_325.0, 0.0)
    humid = air_density(30.0, 101_325.0, 0.95)
    assert humid < dry


def test_saturation_vapour_pressure_rises_with_temperature():
    values = [saturation_vapour_pressure(t) for t in (0.0, 10.0, 20.0, 30.0)]
    assert all(b > a for a, b in zip(values, values[1:]))
    # About 3.17 kPa at 25 degC.
    assert saturation_vapour_pressure(25.0) == pytest.approx(3170.0, rel=0.02)


def test_hot_race_has_measurably_less_air():
    """A hot Bahrain evening against a cold Spa morning."""
    cold = AmbientConditions(air_temperature=5.0, relative_humidity=0.2)
    hot = AmbientConditions(air_temperature=35.0, relative_humidity=0.6)
    loss = 1.0 - hot.air_density / cold.air_density
    assert 0.08 < loss < 0.14


def test_dynamic_pressure():
    conditions = AmbientConditions()
    assert conditions.dynamic_pressure(0.0) == 0.0
    assert conditions.dynamic_pressure(20.0) == pytest.approx(
        0.5 * conditions.air_density * 400.0
    )
    # Quadratic in speed.
    assert conditions.dynamic_pressure(40.0) == pytest.approx(
        4.0 * conditions.dynamic_pressure(20.0)
    )


def test_round_trip():
    conditions = AmbientConditions(air_temperature=31.0, relative_humidity=0.7)
    assert AmbientConditions.from_dict(conditions.to_dict()) == conditions


def test_is_wet():
    assert not AmbientConditions().is_wet
    assert AmbientConditions(rain_intensity=0.3).is_wet


@pytest.mark.parametrize(
    "kwargs",
    [
        {"air_temperature": -100.0},
        {"track_temperature": 200.0},
        {"pressure": 0.0},
        {"relative_humidity": 1.5},
        {"wind_speed": -1.0},
        {"rain_intensity": 2.0},
    ],
)
def test_implausible_conditions_are_rejected(kwargs):
    with pytest.raises(ConfigError):
        AmbientConditions(**kwargs)


def test_below_absolute_zero_is_rejected():
    with pytest.raises(ConfigError):
        air_density(-300.0, 101_325.0)
