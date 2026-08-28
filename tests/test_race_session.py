"""A field of cars on one circuit (Phase 6).

Phase 6 does not make the cars interact -- that is Phase 9.  What it has to get
right is everything underneath racing: that each car keeps its own state, that
the field can grow without disturbing anyone, that the result is the same every
time, and that positions and gaps come from distance and time (rule 28).
"""

from __future__ import annotations

import pytest

from f1_race_engine.core.errors import EntryError
from f1_race_engine.core.events import EventBus
from f1_race_engine.core.rng import RngHub
from f1_race_engine.race import RaceEntry, RaceSession
from f1_race_engine.race.session import LapCompleted
from f1_race_engine.vehicle import MEDIUM_DOWNFORCE, Vehicle
from f1_race_engine.vehicle.io import load_builtin_vehicle


def _run(track, entries, laps=3, seed=7, **kwargs):
    return RaceSession(track, entries, laps=laps, rng=RngHub(seed), **kwargs).run()


# -- the session runs --------------------------------------------------------

def test_a_race_produces_a_classified_field(fast_track, small_field):
    result = _run(fast_track, small_field)
    assert len(result.classification) == len(small_field)
    assert [row.position for row in result.classification] == [1, 2, 3, 4]
    assert result.winner is result.classification[0]
    assert result.laps == 3


def test_everyone_covers_the_race_distance(fast_track, small_field):
    result = _run(fast_track, small_field, laps=4)
    assert all(row.laps_completed == 4 for row in result.classification)


def test_the_classification_is_ordered_by_time(fast_track, small_field):
    result = _run(fast_track, small_field)
    times = [row.total_time for row in result.classification]
    assert times == sorted(times)


def test_the_gap_is_the_difference_at_the_line(fast_track, small_field):
    """Rule 28: the gap between two cars on the same lap is the time between
    them crossing the same place, which at the flag is their finishing times."""
    result = _run(fast_track, small_field)
    winner = result.classification[0]
    for row in result.classification[1:]:
        assert row.gap.seconds == pytest.approx(
            row.total_time - winner.total_time, rel=1e-9
        )


def test_intervals_telescope_into_the_gap(fast_track, small_field):
    result = _run(fast_track, small_field)
    running = 0.0
    for row in result.classification[1:]:
        running += row.interval.seconds
        assert row.gap.seconds == pytest.approx(running, rel=1e-9)


def test_the_fastest_lap_is_somebody_s_fastest_lap(fast_track, small_field):
    result = _run(fast_track, small_field)
    best = result.fastest_lap
    assert best is not None
    assert best.lap_time == min(
        record.lap_time
        for car in result.timing.cars
        for record in result.timing.records(car)
    )


# -- rule 36: cars must not perturb each other -------------------------------


def test_a_race_is_reproducible(fast_track, make_entry, lineup):
    def once():
        entries = [make_entry(i + 1, d) for i, d in enumerate(lineup[:4])]
        return [row.total_time for row in _run(fast_track, entries).classification]

    assert once() == once()


def test_adding_a_car_does_not_change_anyone_else(fast_track, make_entry, lineup):
    """The single easiest way to make a race simulator irreproducible is to let
    randomness leak between competitors.  Every entry gets its own hub."""
    def race(count):
        entries = [make_entry(i + 1, d) for i, d in enumerate(lineup[:count])]
        return {row.car_number: row.total_time for row in _run(fast_track, entries).classification}

    small, large = race(2), race(5)
    for car in small:
        assert small[car] == large[car]


def test_the_order_of_the_entry_list_does_not_matter(fast_track, make_entry, lineup):
    forwards = [make_entry(i + 1, d) for i, d in enumerate(lineup[:4])]
    backwards = list(reversed([make_entry(i + 1, d) for i, d in enumerate(lineup[:4])]))
    a = {row.car_number: row.total_time for row in _run(fast_track, forwards).classification}
    b = {row.car_number: row.total_time for row in _run(fast_track, backwards).classification}
    assert a == b


def test_a_different_seed_changes_the_race(fast_track, make_entry, lineup):
    entries_a = [make_entry(i + 1, d) for i, d in enumerate(lineup[:4])]
    entries_b = [make_entry(i + 1, d) for i, d in enumerate(lineup[:4])]
    a = _run(fast_track, entries_a, seed=1).classification[0].total_time
    b = _run(fast_track, entries_b, seed=2).classification[0].total_time
    assert a != b


# -- the field is not all the same -------------------------------------------


def test_a_better_driver_finishes_ahead_in_equal_machinery(
    fast_track, make_entry, lineup
):
    ranked = sorted(lineup, key=lambda d: d.attributes.pace)
    entries = [make_entry(1, ranked[0]), make_entry(2, ranked[-1])]
    result = _run(fast_track, entries, laps=4)
    assert result.classification[0].car_number == 2


def test_a_faster_car_finishes_ahead_with_the_same_driver(
    fast_track, make_entry, lineup
):
    """Rule 40, Test C, in a race: the machinery has to matter."""
    driver = lineup[0]
    entries = [
        make_entry(1, driver, spec=load_builtin_vehicle("reference_2024")),
        make_entry(2, driver, spec=load_builtin_vehicle("power_biased")),
    ]
    result = _run(fast_track, entries, laps=3)
    times = {row.car_number: row.total_time for row in result.classification}
    assert times[1] != times[2]


def test_a_heavier_fuel_load_costs_the_race(fast_track, make_entry, lineup):
    driver = lineup[0]
    entries = [
        make_entry(1, driver, fuel_mass=20.0),
        make_entry(2, driver, fuel_mass=100.0),
    ]
    result = _run(fast_track, entries, laps=3)
    assert result.classification[0].car_number == 1


def test_a_lapped_car_is_classified_in_laps(fast_track, make_entry, lineup, compounds):
    """A long enough race between mismatched cars produces the real thing."""
    ranked = sorted(lineup, key=lambda d: d.attributes.pace)
    quick = make_entry(1, ranked[-1], spec=load_builtin_vehicle("power_biased"),
                       fuel_mass=20.0)
    slow = make_entry(2, ranked[0], spec=load_builtin_vehicle("aero_biased"),
                      fuel_mass=110.0)
    slow.fit(compounds["S"])
    result = RaceSession(fast_track, [quick, slow], laps=30, rng=RngHub(3)).run()
    trailing = result.classification[-1]
    assert trailing.laps_completed < result.classification[0].laps_completed
    assert trailing.gap.is_lapped
    assert trailing.gap.formatted.endswith("lap") or trailing.gap.formatted.endswith("laps")


# -- consumables carry across the race ---------------------------------------


def test_the_tyres_wear_over_a_race(fast_track, small_field, compounds):
    for entry in small_field:
        entry.fit(compounds["M"])
    result = _run(fast_track, small_field, laps=6)
    assert all(row.tyre_wear > 0.0 for row in result.classification)
    assert all(entry.tyres.age_laps == 6 for entry in small_field)


def test_fuel_is_burned_over_the_race(fast_track, small_field):
    start = [entry.fuel_mass for entry in small_field]
    result = _run(fast_track, small_field, laps=4)
    assert all(entry.fuel_mass < before for entry, before in zip(small_field, start))
    assert all(row.fuel_remaining < 50.0 for row in result.classification)


def test_a_tyre_management_specialist_finishes_with_more_tread(
    fast_track, make_entry, lineup, compounds
):
    ranked = sorted(lineup, key=lambda d: d.attributes.tyre_management)
    careless, careful = make_entry(1, ranked[0]), make_entry(2, ranked[-1])
    for entry in (careless, careful):
        entry.fit(compounds["M"])
    result = RaceSession(fast_track, [careless, careful], laps=8, rng=RngHub(3)).run()
    assert result.of(2).tyre_wear < result.of(1).tyre_wear


# -- entries and errors ------------------------------------------------------


def test_an_empty_field_is_rejected(fast_track):
    with pytest.raises(EntryError):
        RaceSession(fast_track, [], laps=3)


def test_duplicate_car_numbers_are_rejected(fast_track, make_entry, lineup):
    entries = [make_entry(1, lineup[0]), make_entry(1, lineup[1])]
    with pytest.raises(EntryError):
        RaceSession(fast_track, entries, laps=3)


def test_a_race_needs_at_least_one_lap(fast_track, small_field):
    with pytest.raises(EntryError):
        RaceSession(fast_track, small_field, laps=0)


def test_a_car_number_must_be_real(reference_spec, lineup):
    with pytest.raises(EntryError):
        RaceEntry(car_number=0, driver=lineup[0],
                  vehicle=Vehicle(reference_spec, MEDIUM_DOWNFORCE))


def test_asking_for_a_car_that_did_not_race(fast_track, small_field):
    result = _run(fast_track, small_field)
    with pytest.raises(EntryError):
        result.of(99)


# -- reporting ---------------------------------------------------------------


def test_the_result_serialises(fast_track, small_field):
    payload = _run(fast_track, small_field).to_dict(include_laps=True)
    assert payload["laps"] == 3
    assert len(payload["classification"]) == 4
    assert set(payload["lap_records"]) == {"1", "2", "3", "4"}


def test_the_result_formats_as_a_timing_screen(fast_track, small_field):
    text = _run(fast_track, small_field).format()
    assert "pos" in text and "interval" in text
    assert small_field[0].driver.name in text


def test_lap_events_are_published(fast_track, small_field):
    bus = EventBus()
    seen: list[LapCompleted] = []
    bus.subscribe(LapCompleted, seen.append)
    RaceSession(fast_track, small_field, laps=2, rng=RngHub(7), events=bus).run()
    assert len(seen) == 2 * len(small_field)
    assert {event.car_number for event in seen} == {1, 2, 3, 4}


def test_a_lap_callback_sees_every_lap(fast_track, small_field):
    seen = []
    RaceSession(fast_track, small_field, laps=2, rng=RngHub(7)).run(
        on_lap=lambda entry, result: seen.append((entry.car_number, result.lap))
    )
    assert len(seen) == 2 * len(small_field)


def test_an_entry_snapshot_is_plain_data(small_field):
    payload = small_field[0].snapshot()
    assert payload["car_number"] == 1
    assert "tyres" in payload and "energy" in payload
