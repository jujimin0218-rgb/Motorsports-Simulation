"""Qualifying and the grid (project rule 27).

A knockout session run for real, so the grid is what the running produced: the
track comes to the drivers as it rubbers in, an out-lap has to warm the tyres,
and the weather does not wait for anybody.
"""

from __future__ import annotations

import pytest

from f1_race_engine.core.errors import EntryError
from f1_race_engine.core.rng import RngHub
from f1_race_engine.environment import TrackEvolution
from f1_race_engine.race import QualifyingSegment, QualifyingSession, starting_grid
from f1_race_engine.race.grid import launch_from_rest, reaction_time
from f1_race_engine.track.surface import TrackConditions

SHORT = (
    QualifyingSegment("Q1", 400.0, 2),
    QualifyingSegment("Q2", 350.0, 1),
    QualifyingSegment("Q3", 300.0, 0),
)


@pytest.fixture
def qualifying_field(make_entry, lineup, compounds):
    entries = [make_entry(i + 1, d) for i, d in enumerate(lineup)]
    for entry in entries:
        entry.compounds = tuple(compounds.slicks)
    return entries


def _session(track, entries, **kwargs):
    kwargs.setdefault("segments", SHORT)
    kwargs.setdefault("rng", RngHub(7))
    kwargs.setdefault("max_runs", 1)
    return QualifyingSession(track, entries, **kwargs)


# -- the session produces a grid ---------------------------------------------


def test_qualifying_orders_the_whole_field(session_track, qualifying_field):
    result = _session(session_track, qualifying_field).run()
    assert len(result.order) == len(qualifying_field)
    assert len(set(result.order)) == len(result.order)
    assert result.pole == result.order[0]


def test_the_grid_is_a_set_of_distances(session_track, qualifying_field):
    result = _session(session_track, qualifying_field).run()
    slots = [result.slot_for(car) for car in result.order]
    assert slots[0].distance_back < slots[-1].distance_back
    assert all(b.distance_back > a.distance_back for a, b in zip(slots, slots[1:]))


def test_everybody_sets_a_time(session_track, qualifying_field):
    result = _session(session_track, qualifying_field).run()
    assert set(result.best) == {e.car_number for e in qualifying_field}
    assert all(time > 0.0 for time in result.best.values())


def test_the_order_is_by_the_times_that_counted(session_track, qualifying_field):
    result = _session(session_track, qualifying_field).run()
    survivors = [c for c, seg in result.eliminated_in.items() if seg == "Q3"]
    front = [c for c in result.order if c in survivors]
    times = [result.best_in("Q3")[c] for c in front]
    assert times == sorted(times)


def test_the_eliminated_are_classified_behind_the_survivors(
    session_track, qualifying_field
):
    result = _session(session_track, qualifying_field).run()
    positions = {car: i for i, car in enumerate(result.order)}
    rank = {"Q3": 0, "Q2": 1, "Q1": 2}
    ordering = [rank[result.eliminated_in[car]] for car in result.order]
    assert ordering == sorted(ordering)


def test_the_right_number_are_knocked_out(session_track, qualifying_field):
    result = _session(session_track, qualifying_field).run()
    counts = {}
    for segment in result.eliminated_in.values():
        counts[segment] = counts.get(segment, 0) + 1
    assert counts.get("Q1", 0) == 2
    assert counts.get("Q2", 0) == 1


# -- the session is a session ------------------------------------------------


def test_the_track_comes_to_them(session_track, qualifying_field):
    """Rubber goes down as the session runs, so the later segments are quicker
    for everybody -- and nobody was given anything."""
    conditions = TrackConditions(session_track.segments)
    evolution = TrackEvolution(conditions)
    result = _session(
        session_track, qualifying_field, evolution=evolution, max_runs=1
    ).run()
    green = min(lap.lap_time for lap in result.laps if lap.segment == "Q1")
    rubbered = min(lap.lap_time for lap in result.laps if lap.segment == "Q3")
    assert conditions.mean_rubber > 0.0
    assert rubbered < green


def test_one_run_records_one_lap_per_segment(session_track, qualifying_field):
    """Three laps are driven -- out, flying, cool-down -- and one is recorded,
    which is why a set of tyres is up to temperature when the lap that counts
    starts.  Cars knocked out early simply have fewer segments."""
    result = _session(session_track, qualifying_field, max_runs=1).run()
    counted: dict[tuple[int, str], int] = {}
    for lap in result.laps:
        counted[(lap.car_number, lap.segment)] = (
            counted.get((lap.car_number, lap.segment), 0) + 1
        )
    assert set(counted.values()) == {1}
    survivors = [c for c, seg in result.eliminated_in.items() if seg == "Q3"]
    assert all((car, "Q3") in counted for car in survivors)


def test_a_flying_lap_is_on_warmed_tyres(session_track, qualifying_field):
    """A fitted set starts below its window; the out-lap is what gets it in."""
    result = _session(session_track, qualifying_field, max_runs=1).run()
    entry = qualifying_field[0]
    assert entry.tyres.peak_surface_temperature > entry.tyres.compound.optimal_temperature - (
        entry.tyres.compound.temperature_window
    )


def test_more_runs_find_more_time(session_track, qualifying_field, make_entry, lineup):
    one = _session(session_track, qualifying_field, max_runs=1).run()
    fresh = [make_entry(i + 1, d) for i, d in enumerate(lineup)]
    for entry in fresh:
        entry.compounds = qualifying_field[0].compounds
    two = _session(session_track, fresh, max_runs=2).run()
    assert min(two.best.values()) <= min(one.best.values())


def test_qualifying_is_reproducible(session_track, make_entry, lineup, compounds):
    def once():
        entries = [make_entry(i + 1, d) for i, d in enumerate(lineup)]
        for entry in entries:
            entry.compounds = tuple(compounds.slicks)
        result = _session(session_track, entries).run()
        return result.order, tuple(sorted(result.best.items()))

    assert once() == once()


def test_the_result_serialises_and_formats(session_track, qualifying_field):
    result = _session(session_track, qualifying_field).run()
    payload = result.to_dict()
    assert payload["pole"] == result.pole
    text = result.format({e.car_number: e.driver.name for e in qualifying_field})
    assert "qualifying" in text and qualifying_field[0].driver.name in text


def test_an_empty_entry_list_is_rejected(session_track):
    with pytest.raises(EntryError):
        QualifyingSession(session_track, [], segments=SHORT)


def test_a_session_needs_a_segment(session_track, qualifying_field):
    with pytest.raises(EntryError):
        QualifyingSession(session_track, qualifying_field, segments=())


def test_asking_about_a_car_that_did_not_qualify(session_track, qualifying_field):
    result = _session(session_track, qualifying_field).run()
    with pytest.raises(EntryError):
        result.slot_for(999)


# -- getting off the line ----------------------------------------------------


def test_the_grid_is_staggered_and_spaced():
    grid = starting_grid(10)
    assert grid[0].distance_back < grid[1].distance_back < grid[2].distance_back
    assert grid[2].distance_back - grid[0].distance_back == pytest.approx(8.0)


def test_a_grid_needs_a_position():
    with pytest.raises(EntryError):
        starting_grid(0)


def test_a_launch_is_an_acceleration_from_rest(car):
    launch = launch_from_rest(car, 40.0)
    assert launch.travel > 0.0
    assert launch.exit_speed > 0.0
    assert launch.distance == pytest.approx(40.0)


def test_a_car_further_back_takes_longer_to_reach_the_line(car):
    near = launch_from_rest(car, 8.0)
    far = launch_from_rest(car, 80.0)
    assert far.travel > near.travel
    assert far.exit_speed > near.exit_speed


def test_a_heavier_car_gets_away_worse(car):
    light = launch_from_rest(car, 60.0, mass=car.mass.total_mass(10.0))
    heavy = launch_from_rest(car, 60.0, mass=car.mass.total_mass(110.0))
    assert heavy.travel > light.travel


def test_a_slick_cannot_get_off_a_wet_grid(car, compounds):
    """The tyre side of it: a slick has no tread to clear the water with, and
    a full wet does."""
    from f1_race_engine.tyres import TyreState

    slick = launch_from_rest(
        car, 60.0, tyre_state=TyreState(compound=compounds["M"]), water_depth=0.004
    )
    wet = launch_from_rest(
        car, 60.0, tyre_state=TyreState(compound=compounds["W"]), water_depth=0.004
    )
    assert slick.travel > wet.travel


def test_a_slippery_grid_punishes_everybody(car, compounds):
    """The surface side of it: wet asphalt grips less whatever is on it."""
    from f1_race_engine.tyres import TyreState

    grippy = launch_from_rest(
        car, 60.0, tyre_state=TyreState(compound=compounds["W"]), surface_grip=1.0
    )
    greasy = launch_from_rest(
        car, 60.0, tyre_state=TyreState(compound=compounds["W"]), surface_grip=0.8
    )
    assert greasy.travel > grippy.travel


def test_a_reaction_happens_before_the_car_moves(lineup):
    launch_reaction = reaction_time(lineup[0])
    assert 0.15 < launch_reaction < 0.6


def test_racecraft_makes_a_better_starter(lineup):
    ranked = sorted(lineup, key=lambda d: d.attributes.racecraft)
    assert reaction_time(ranked[-1]) < reaction_time(ranked[0])


def test_a_reaction_scatters_and_is_reproducible(lineup):
    a = [reaction_time(lineup[0], RngHub(4), lap=i) for i in range(5)]
    b = [reaction_time(lineup[0], RngHub(4), lap=i) for i in range(5)]
    assert a == b
    assert len(set(a)) > 1


def test_nobody_reacts_impossibly_fast(lineup):
    for seed in range(20):
        for driver in lineup:
            assert reaction_time(driver, RngHub(seed)) > 0.05


def test_a_zero_distance_launch_is_free(car):
    launch = launch_from_rest(car, 0.0, reaction=0.2)
    assert launch.travel == 0.0
    assert launch.total == pytest.approx(0.2)


def test_the_launch_serialises(car):
    payload = launch_from_rest(car, 30.0, reaction=0.2).to_dict()
    assert payload["total"] == pytest.approx(payload["reaction"] + payload["travel"])
