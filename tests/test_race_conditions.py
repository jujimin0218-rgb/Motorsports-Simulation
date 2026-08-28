"""A race that runs into weather (Phases 8 and 10 meeting Phase 6).

The point of running the weather, the track surface and the strategist in the
same loop is that a shower has to be able to rearrange a race without anybody
having written down that it should.
"""

from __future__ import annotations

import pytest

from f1_race_engine.core.rng import RngHub
from f1_race_engine.environment import Forecast, TrackEvolution, WeatherModel
from f1_race_engine.race import PitLane, RaceSession, RaceStrategy
from f1_race_engine.track.surface import TrackConditions


@pytest.fixture
def field(make_entry, lineup, compounds):
    entries = []
    for index, driver in enumerate(lineup[:4]):
        entry = make_entry(index + 1, driver, fuel_mass=60.0)
        entry.compounds = tuple(compounds.compounds)
        entry.strategy = RaceStrategy(minimum_stint=3)
        entry.fit(compounds["M"])
        entries.append(entry)
    return entries


def _session(track, entries, **kwargs):
    kwargs.setdefault("laps", 10)
    kwargs.setdefault("rng", RngHub(9))
    return RaceSession(track, entries, **kwargs)


# -- the track moves under them ----------------------------------------------


def test_a_race_rubbers_the_track_in(session_track, field):
    conditions = TrackConditions(session_track.segments)
    evolution = TrackEvolution(conditions)
    _session(session_track, field, evolution=evolution).run()
    assert conditions.mean_rubber > 0.0


def test_the_weather_moves_while_they_race(session_track, field):
    weather = WeatherModel(Forecast(), RngHub(2))
    start = weather.state.elapsed
    _session(session_track, field, weather=weather).run()
    assert weather.state.elapsed > start


def test_a_race_without_weather_still_runs(session_track, field):
    result = _session(session_track, field).run()
    assert len(result.classification) == len(field)


# -- rain rearranges it ------------------------------------------------------


def test_rain_puts_the_field_on_wet_tyres(session_track, field, compounds):
    """Nothing says rain means intermediates.  The strategist asks which tread
    copes with the water that is down, and the answer changes."""
    conditions = TrackConditions(session_track.segments)
    for index in range(len(conditions)):
        conditions[index].water_depth = 0.004
    evolution = TrackEvolution(conditions)
    _session(session_track, field, evolution=evolution, laps=6).run()
    assert all(entry.tyres.is_wet_weather for entry in field)
    assert all(
        any(stop.reason == "conditions" for stop in entry.pit_stops)
        for entry in field
    )


def test_a_drying_track_gets_the_slicks_back(session_track, field, compounds):
    """The cars dry the racing line themselves, and the strategist notices."""
    conditions = TrackConditions(session_track.segments)
    for index in range(len(conditions)):
        conditions[index].water_depth = 0.003
    evolution = TrackEvolution(conditions)
    for entry in field:
        entry.fit(compounds["W"])
    _session(session_track, field, evolution=evolution, laps=14).run()
    assert evolution.mean_water_depth < 0.003
    if evolution.mean_water_depth == 0.0:
        assert any(not entry.tyres.is_wet_weather for entry in field)


def test_a_wet_race_is_slower_than_a_dry_one(session_track, field, make_entry, lineup, compounds):
    def race(depth):
        entries = []
        for index, driver in enumerate(lineup[:4]):
            entry = make_entry(index + 1, driver, fuel_mass=60.0)
            entry.compounds = tuple(compounds.compounds)
            entry.strategy = RaceStrategy(minimum_stint=3)
            entry.fit(compounds["M"] if depth == 0.0 else compounds["W"])
            entries.append(entry)
        conditions = TrackConditions(session_track.segments)
        for index in range(len(conditions)):
            conditions[index].water_depth = depth
        return _session(
            session_track, entries, laps=5, conditions=conditions
        ).run().classification[0].total_time

    assert race(0.003) > race(0.0)


# -- stopping ----------------------------------------------------------------


def test_a_car_with_no_strategy_never_stops(session_track, make_entry, lineup, compounds):
    entries = []
    for index, driver in enumerate(lineup[:3]):
        entry = make_entry(index + 1, driver, fuel_mass=60.0)
        entry.fit(compounds["S"])
        entries.append(entry)
    result = _session(session_track, entries, laps=8).run()
    assert all(not entry.pit_stops for entry in entries)
    assert all(row.pit_stops == 0 for row in result.classification)


def test_a_stop_costs_the_lap_it_happens_on(session_track, field, compounds):
    """The loss is charged where it was incurred, so the lap chart shows it."""
    for entry in field:
        entry.fit(compounds["S"])
        entry.strategy = RaceStrategy(minimum_stint=2, wear_limit=0.05)
    result = _session(session_track, field, laps=8).run()
    for entry in field:
        if not entry.pit_stops:
            continue
        stop = entry.pit_stops[0]
        records = result.timing.records(entry.car_number)
        pit_lap = records[stop.lap - 1]
        assert pit_lap.pitted
        others = [r.lap_time for r in records if not r.pitted]
        assert pit_lap.lap_time > min(others) + stop.loss * 0.5
        break


def test_the_classification_counts_the_stops(session_track, field, compounds):
    for entry in field:
        entry.fit(compounds["S"])
        entry.strategy = RaceStrategy(minimum_stint=2, wear_limit=0.05)
    result = _session(session_track, field, laps=8).run()
    for row in result.classification:
        entry = next(e for e in field if e.car_number == row.car_number)
        assert row.pit_stops == len(
            [s for s in entry.pit_stops if s.lap <= row.laps_completed]
        )


def test_a_custom_pit_lane_changes_what_a_stop_costs(session_track, field, compounds):
    def race(length):
        for entry in field:
            entry.pit_stops.clear()
            entry.fit(compounds["S"])
            entry.strategy = RaceStrategy(minimum_stint=2, wear_limit=0.05)
        lane = PitLane.for_track(session_track.length, length=length)
        _session(session_track, field, laps=6, pit_lane=lane).run()
        return [s.loss for e in field for s in e.pit_stops]

    short = race(300.0)
    long_lane = race(700.0)
    assert short and long_lane
    assert min(long_lane) > max(short)


# -- the start ---------------------------------------------------------------


def test_a_standing_start_makes_lap_one_the_slowest(session_track, field):
    for position, entry in enumerate(field, start=1):
        entry.grid_position = position
    result = _session(session_track, field, laps=6, standing_start=True).run()
    for row in result.classification:
        records = result.timing.records(row.car_number)
        assert records[0].lap_time == max(r.lap_time for r in records)


def test_the_back_of_the_grid_loses_time_to_the_front(session_track, field):
    for position, entry in enumerate(field, start=1):
        entry.grid_position = position
    session = _session(session_track, field, laps=3, standing_start=True)
    session.run()
    launches = session.launches
    front = launches[field[0].car_number]
    back = launches[field[-1].car_number]
    assert back.total > front.total
    assert back.distance > front.distance


def test_a_rolling_start_has_no_launch(session_track, field):
    session = _session(session_track, field, laps=3, standing_start=False)
    session.run()
    assert session.launches == {}


def test_the_world_advancing_does_not_depend_on_entry_order(
    session_track, make_entry, lineup, compounds
):
    """The track and the sky move once per lap of the field, not once per car,
    so the entry list still cannot change anybody's race."""
    def race(reverse):
        entries = []
        for index, driver in enumerate(lineup[:4]):
            entry = make_entry(index + 1, driver, fuel_mass=60.0)
            entry.fit(compounds["M"])
            entries.append(entry)
        if reverse:
            entries.reverse()
        conditions = TrackConditions(session_track.segments)
        evolution = TrackEvolution(conditions)
        weather = WeatherModel(Forecast(), RngHub(3))
        result = _session(
            session_track, entries, laps=5, weather=weather, evolution=evolution
        ).run()
        return {row.car_number: row.total_time for row in result.classification}

    assert race(False) == race(True)
