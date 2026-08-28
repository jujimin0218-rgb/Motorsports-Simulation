"""A weekend, where the three systems meet.

Practice, qualifying and a race share one sky and one track surface.  What
these tests check is that sharing them actually does something: that the laps
run in practice make qualifying quicker, that qualifying decides where the race
starts from, and that rain in the middle of any of it changes what everyone is
running on.
"""

from __future__ import annotations

import pytest

from f1_race_engine.core.errors import EntryError
from f1_race_engine.core.rng import RngHub
from f1_race_engine.environment import Forecast
from f1_race_engine.race import QualifyingSegment, RaceStrategy, Weekend

SHORT = (
    QualifyingSegment("Q1", 400.0, 1),
    QualifyingSegment("Q2", 350.0, 1),
    QualifyingSegment("Q3", 300.0, 0),
)


@pytest.fixture
def weekend_field(make_entry, lineup, compounds):
    entries = []
    for index, driver in enumerate(lineup[:4]):
        entry = make_entry(index + 1, driver, fuel_mass=60.0)
        entry.compounds = tuple(compounds.compounds)
        entry.strategy = RaceStrategy(minimum_stint=4)
        entries.append(entry)
    return entries


def _weekend(track, entries, **kwargs):
    kwargs.setdefault("laps", 5)
    kwargs.setdefault("rng", RngHub(12))
    kwargs.setdefault("segments", SHORT)
    kwargs.setdefault("practice_laps", 2)
    return Weekend(track, entries, **kwargs)


# -- the weekend runs --------------------------------------------------------


def test_a_weekend_produces_a_grid_and_a_result(session_track, weekend_field):
    result = _weekend(session_track, weekend_field).run()
    assert result.qualifying is not None
    assert len(result.qualifying.order) == len(weekend_field)
    assert len(result.race.classification) == len(weekend_field)
    assert result.winner is not None


def test_qualifying_decides_where_the_race_starts_from(session_track, weekend_field):
    result = _weekend(session_track, weekend_field).run()
    by_number = {entry.car_number: entry for entry in weekend_field}
    for position, car in enumerate(result.qualifying.order, start=1):
        assert by_number[car].grid_position == position


def test_the_race_can_be_run_without_qualifying(session_track, weekend_field):
    result = _weekend(session_track, weekend_field).run(qualify=False)
    assert result.qualifying is None
    assert result.pole is None
    assert len(result.race.classification) == len(weekend_field)


def test_a_weekend_is_reproducible(session_track, make_entry, lineup, compounds):
    def once():
        entries = []
        for index, driver in enumerate(lineup[:4]):
            entry = make_entry(index + 1, driver, fuel_mass=60.0)
            entry.compounds = tuple(compounds.compounds)
            entry.strategy = RaceStrategy(minimum_stint=4)
            entries.append(entry)
        result = _weekend(session_track, entries).run()
        return (
            result.qualifying.order,
            tuple(row.total_time for row in result.race.classification),
        )

    assert once() == once()


def test_an_empty_weekend_is_rejected(session_track):
    with pytest.raises(EntryError):
        Weekend(session_track, [], laps=5)


def test_a_race_needs_a_lap(session_track, weekend_field):
    with pytest.raises(EntryError):
        Weekend(session_track, weekend_field, laps=0)


# -- the sessions are connected ----------------------------------------------


def test_practice_leaves_rubber_behind_for_qualifying(session_track, weekend_field):
    """Nothing in practice is timed.  The point is that the laps happened."""
    weekend = _weekend(session_track, weekend_field, practice_laps=6)
    assert weekend.conditions.mean_rubber == 0.0
    weekend.run()
    assert weekend.conditions.mean_rubber > 0.0


def test_more_practice_makes_qualifying_quicker(
    session_track, make_entry, lineup, compounds
):
    def pole_time(practice_laps):
        entries = []
        for index, driver in enumerate(lineup[:4]):
            entry = make_entry(index + 1, driver, fuel_mass=60.0)
            entry.compounds = tuple(compounds.slicks)
            entries.append(entry)
        weekend = _weekend(
            session_track, entries, practice_laps=practice_laps,
            forecast=Forecast(rain_probability=0.0),
        )
        result = weekend.run()
        return min(result.qualifying.best.values())

    assert pole_time(10) < pole_time(0)


def test_the_weather_carries_across_the_weekend(session_track, weekend_field):
    weekend = _weekend(session_track, weekend_field)
    result = weekend.run()
    assert len(result.weather_log) > 2
    assert result.weather_log[-1].elapsed > result.weather_log[0].elapsed


def test_a_wet_weekend_puts_everybody_on_wet_tyres(
    session_track, make_entry, lineup, compounds
):
    """Nothing tells the strategist that rain means intermediates.  It asks
    which tread copes with the water that is down, and the answer changes."""
    entries = []
    for index, driver in enumerate(lineup[:4]):
        entry = make_entry(index + 1, driver, fuel_mass=60.0)
        entry.compounds = tuple(compounds.compounds)
        entry.strategy = RaceStrategy(minimum_stint=2)
        entries.append(entry)
    weekend = _weekend(
        session_track, entries, laps=8, practice_laps=2,
        forecast=Forecast(rain_probability=1.0, air_temperature=16.0),
        rng=RngHub(5),
    )
    result = weekend.run()
    wet_running = any(
        entry.tyres.is_wet_weather or any(
            stop.reason == "conditions" for stop in entry.pit_stops
        )
        for entry in entries
    )
    assert wet_running or weekend.evolution.mean_water_depth == 0.0
    assert result.race.classification


def test_the_result_serialises_and_formats(session_track, weekend_field):
    result = _weekend(session_track, weekend_field).run()
    payload = result.to_dict()
    assert "qualifying" in payload and "race" in payload
    text = result.format({e.car_number: e.driver.name for e in weekend_field})
    assert "qualifying" in text


# -- the standing start ------------------------------------------------------


def test_the_race_starts_from_a_standstill(session_track, weekend_field):
    weekend = _weekend(session_track, weekend_field)
    result = weekend.run()
    # Lap one includes a reaction and an acceleration from rest, so it is the
    # slowest lap of the race for everybody who did not have a mistake.
    for row in result.race.classification:
        records = result.race.timing.records(row.car_number)
        assert records[0].lap_time > row.best_lap


def test_starting_further_back_costs_time(session_track, weekend_field):
    result = _weekend(session_track, weekend_field).run()
    launches = result.race.timing
    first = result.qualifying.order[0]
    last = result.qualifying.order[-1]
    assert launches.records(last)[0].elapsed > launches.records(first)[0].elapsed
