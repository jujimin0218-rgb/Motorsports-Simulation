"""Weather that moves (project rule 30).

A wet race is a wet race because nobody knows whether it is going to rain.
These tests pin down that the weather is a process rather than a setting: the
same seed gives the same afternoon, a different seed gives a different one, and
nothing anywhere schedules a shower.
"""

from __future__ import annotations

import pytest

from f1_race_engine.core.config import WeatherConfig
from f1_race_engine.core.errors import ConfigError
from f1_race_engine.core.rng import RngHub
from f1_race_engine.environment import (
    AmbientConditions,
    Forecast,
    WeatherModel,
    headwind_component,
)


def _run(model: WeatherModel, minutes: int, step: float = 300.0):
    states = [model.state]
    for _ in range(int(minutes * 60 / step)):
        states.append(model.advance(step))
    return states


# -- determinism -------------------------------------------------------------


def test_the_same_seed_gives_the_same_afternoon():
    def once():
        model = WeatherModel(Forecast(rain_probability=0.6), RngHub(4))
        return [(s.air_temperature, s.rain_intensity) for s in _run(model, 90)]

    assert once() == once()


def test_a_different_seed_gives_a_different_afternoon():
    def rain(seed):
        model = WeatherModel(Forecast(rain_probability=0.6), RngHub(seed))
        return [s.rain_intensity for s in _run(model, 90)]

    assert rain(1) != rain(2)


def test_the_answer_does_not_depend_on_how_often_you_ask():
    """Rule 12 applied to time: the caller's step size is a sampling choice,
    not a modelling one."""
    coarse = WeatherModel(Forecast(rain_probability=0.5), RngHub(9))
    fine = WeatherModel(Forecast(rain_probability=0.5), RngHub(9))
    coarse.advance(1800.0)
    for _ in range(6):
        fine.advance(300.0)
    assert coarse.state.air_temperature == pytest.approx(fine.state.air_temperature)
    assert coarse.state.rain_intensity == pytest.approx(fine.state.rain_intensity)


def test_resetting_starts_the_session_again():
    model = WeatherModel(Forecast(), RngHub(2))
    start = model.state
    model.advance(3600.0)
    model.reset()
    assert model.state == start


# -- the process behaves -----------------------------------------------------


def test_a_dry_forecast_stays_dry():
    model = WeatherModel(
        Forecast(rain_probability=0.0),
        RngHub(3),
        config=WeatherConfig(shower_onset_per_hour=0.0),
    )
    assert all(state.rain_intensity == 0.0 for state in _run(model, 180))


def test_a_wet_forecast_eventually_rains():
    model = WeatherModel(Forecast(rain_probability=1.0), RngHub(3))
    assert any(state.is_wet for state in _run(model, 240))


def test_showers_have_no_fixed_length():
    """Ending is a Poisson event, so some pass in minutes and some settle in."""
    lengths = []
    for seed in range(1, 25):
        model = WeatherModel(Forecast(rain_probability=1.0), RngHub(seed))
        run = 0
        for state in _run(model, 240, step=60.0):
            if state.raining:
                run += 1
            elif run:
                lengths.append(run)
                run = 0
    assert len(set(lengths)) > 3


def test_the_track_lags_the_air():
    """Asphalt has thermal mass, which is why a cloud cools the track long
    after it has gone."""
    model = WeatherModel(Forecast(air_temperature=25.0, cloud_cover=0.0), RngHub(6))
    hot = model.state.track_temperature
    model.forecast = Forecast(air_temperature=5.0, cloud_cover=1.0)
    model.advance(60.0)
    quick = model.state.track_temperature
    model.advance(3600.0)
    settled = model.state.track_temperature
    assert settled < quick < hot
    assert hot - quick < (hot - settled) * 0.5


def test_sunshine_puts_the_track_above_the_air():
    clear = WeatherModel(Forecast(cloud_cover=0.0), RngHub(6)).state
    overcast = WeatherModel(Forecast(cloud_cover=1.0), RngHub(6)).state
    assert clear.track_temperature > clear.air_temperature
    assert overcast.track_temperature == pytest.approx(overcast.air_temperature)


def test_rain_cools_the_session():
    model = WeatherModel(Forecast(air_temperature=28.0, rain_probability=1.0), RngHub(7))
    states = _run(model, 240)
    wet = [s for s in states if s.rain_intensity > 0.2]
    if not wet:  # pragma: no cover - defensive; the forecast makes rain certain
        pytest.skip("no shower in this draw")
    assert min(s.track_temperature for s in wet) < states[0].track_temperature


def test_temperatures_stay_physical():
    for seed in range(1, 12):
        model = WeatherModel(Forecast(rain_probability=0.8), RngHub(seed))
        for state in _run(model, 300):
            assert -30.0 <= state.air_temperature <= 60.0
            assert -30.0 <= state.track_temperature <= 85.0
            assert 0.0 <= state.rain_intensity <= 1.0
            state.ambient  # must always be constructible


def test_the_state_converts_to_conditions_the_physics_reads():
    model = WeatherModel(Forecast(air_temperature=18.0), RngHub(1))
    ambient = model.state.ambient
    assert isinstance(ambient, AmbientConditions)
    assert ambient.air_temperature == pytest.approx(18.0)
    assert ambient.air_density > 1.0


def test_an_impossible_forecast_is_rejected():
    with pytest.raises(ConfigError):
        Forecast(rain_probability=1.5)
    with pytest.raises(ConfigError):
        Forecast(cloud_cover=-0.1)


def test_the_state_serialises():
    payload = WeatherModel(Forecast(), RngHub(1)).state.to_dict()
    assert "rain_intensity" in payload and "track_temperature" in payload


# -- wind --------------------------------------------------------------------


def test_a_headwind_opposes_and_a_tailwind_helps():
    # Wind blowing towards +x; a car heading into it (+pi) sees a headwind.
    assert headwind_component(10.0, 0.0, 3.141592653589793) == pytest.approx(10.0)
    assert headwind_component(10.0, 0.0, 0.0) == pytest.approx(-10.0)


def test_a_crosswind_is_neither():
    assert headwind_component(10.0, 0.0, 1.5707963267948966) == pytest.approx(0.0)


def test_still_air_has_no_component():
    assert headwind_component(0.0, 1.2, 0.4) == 0.0


def test_wind_costs_lap_time_both_ways(fast_track, car, perfect_driver):
    """Drag grows with the square of airspeed, so a headwind down one straight
    and a tailwind down the next do not cancel -- which is why wind direction
    shows up in real session data."""
    from f1_race_engine.core.rng import RngHub
    from f1_race_engine.simulation import LapSimulator

    still = AmbientConditions(wind_speed=0.0)
    windy = AmbientConditions(wind_speed=12.0, wind_direction=0.4)
    calm_lap = LapSimulator(
        fast_track, car, perfect_driver, rng=RngHub(8), ambient=still
    ).simulate(record_telemetry=False)
    windy_lap = LapSimulator(
        fast_track, car, perfect_driver, rng=RngHub(8), ambient=windy
    ).simulate(record_telemetry=False)
    assert windy_lap.lap_time > calm_lap.lap_time
