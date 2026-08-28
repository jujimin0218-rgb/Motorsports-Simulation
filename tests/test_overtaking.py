"""Racing another car (project rule 29).

    "추월은 단순한 확률 판정이 아니라 상황에서 나와야 한다."

There is no overtaking probability anywhere in the engine.  There is a car in
front, a gap that shrinks when one car is quicker than the other, and a place
where the road is wide enough to use it.  These tests check that what comes out
of that is racing.
"""

from __future__ import annotations

import pytest

from f1_race_engine.core.rng import RngHub
from f1_race_engine.driver import Driver, DriverAttributes
from f1_race_engine.race import RaceEntry, RaceSession
from f1_race_engine.vehicle import MEDIUM_DOWNFORCE, Vehicle


def _driver(name, pace, *, racecraft=0.90):
    return Driver(
        name=name, abbreviation=name[:3].upper(),
        attributes=DriverAttributes(
            pace=pace, qualifying=pace, racecraft=racecraft, consistency=1.0,
            tyre_management=0.90, braking=pace, cornering=pace,
            throttle_control=pace, wet_skill=0.90, risk_management=1.0,
        ),
    )


@pytest.fixture
def duel(reference_spec, compounds):
    """Two cars, the quicker one starting behind."""
    def build(slow=0.86, fast=0.97, **kwargs):
        entries = []
        for index, driver in enumerate((_driver("Slow", slow, **kwargs),
                                        _driver("Fast", fast))):
            entry = RaceEntry(
                car_number=index + 1, driver=driver,
                vehicle=Vehicle(reference_spec, MEDIUM_DOWNFORCE),
                fuel_mass=50.0, grid_position=index + 1,
            )
            entry.fit(compounds["M"])
            entries.append(entry)
        return entries

    return build


def _race(track, entries, laps=8, seed=4, **kwargs):
    kwargs.setdefault("racing", True)
    kwargs.setdefault("standing_start", True)
    return RaceSession(track, entries, laps=laps, rng=RngHub(seed), **kwargs).run()


# -- you cannot drive through people -----------------------------------------


def test_a_quicker_car_stuck_behind_loses_time(street_track, duel):
    """The whole point of traffic: the car is capable of more than it manages.

    Measured against the same cars in the same race with the racing switched
    off, so the grid, the launch and the tyres are identical and the only
    difference is whether they can see each other.
    """
    racing = _race(street_track, duel(), laps=8)
    clear = _race(street_track, duel(), laps=8, racing=False)
    assert racing.of(2).total_time > clear.of(2).total_time


def _solo(spec, compounds, driver):
    entry = RaceEntry(
        car_number=2, driver=driver, vehicle=Vehicle(spec, MEDIUM_DOWNFORCE),
        fuel_mass=50.0, grid_position=1,
    )
    entry.fit(compounds["M"])
    return entry


def test_traffic_shows_up_in_the_lap_result(session_track, duel):
    result = _race(session_track, duel())
    records = result.timing.records(2)
    assert records
    assert result.of(2).total_time > 0.0


def test_a_car_on_its_own_meets_no_traffic(session_track, reference_spec, compounds):
    result = _race(session_track, [_solo(reference_spec, compounds, _driver("Solo", 0.9))])
    assert result.overtakes == ()


def test_racing_can_be_switched_off(session_track, duel):
    """Which is Phase 6's race: everybody in clean air, and much quicker to
    run.  Useful as something to compare a real one against."""
    clean = _race(session_track, duel(), racing=False)
    assert clean.overtakes == ()


# -- getting past ------------------------------------------------------------


def test_a_much_quicker_car_gets_past(session_track, duel):
    result = _race(session_track, duel(slow=0.84, fast=0.99), laps=10)
    assert any(move.attacker == 2 for move in result.overtakes)
    assert result.of(2).position == 1


def test_a_slower_car_does_not_get_past(session_track, duel):
    result = _race(session_track, duel(slow=0.95, fast=0.82), laps=10)
    assert result.of(2).position == 2


def test_an_overtake_is_recorded_where_it_happened(session_track, duel):
    result = _race(session_track, duel(slow=0.84, fast=0.99), laps=10)
    move = next(m for m in result.overtakes if m.attacker == 2)
    assert 1 <= move.lap <= 10
    assert 0.0 <= move.distance <= session_track.length
    assert move.defender == 1


def test_the_classification_counts_the_passes(session_track, duel):
    result = _race(session_track, duel(slow=0.84, fast=0.99), laps=10)
    for row in result.classification:
        assert row.overtakes == len(
            [m for m in result.overtakes if m.attacker == row.car_number]
        )


def test_nobody_gets_an_instant_switchback(session_track, duel):
    """A driver who has just been overtaken has to regroup, get back into the
    wake and set the move up again.  That takes a lap."""
    result = _race(session_track, duel(slow=0.90, fast=0.92), laps=10)
    by_lap: dict[int, set[tuple[int, int]]] = {}
    for move in result.overtakes:
        by_lap.setdefault(move.lap, set()).add((move.attacker, move.defender))
    for lap, moves in by_lap.items():
        for attacker, defender in moves:
            assert (defender, attacker) not in moves


def test_the_result_carries_the_moves(session_track, duel):
    payload = _race(session_track, duel(slow=0.84, fast=0.99), laps=10).to_dict()
    assert "overtakes" in payload
    assert all("attacker" in move for move in payload["overtakes"])


# -- where it is possible ----------------------------------------------------


def test_passing_is_harder_where_there_is_nowhere_to_do_it(
    duel, coarse_build_config, reference_spec, compounds
):
    """Nothing in the engine knows which circuit is which.  What it knows is
    that a tow needs a straight and dirty air does not, and the rest follows."""
    from f1_race_engine.track.builder import build_track
    from f1_race_engine.track.io import load_builtin_definition

    cost = {}
    for name in ("synthetic_power_circuit", "synthetic_street_circuit"):
        track = build_track(load_builtin_definition(name), coarse_build_config)
        # Only marginally quicker: a car with a big enough advantage gets past
        # anywhere, and it is being *stuck* that the circuit decides.
        racing = _race(track, duel(slow=0.90, fast=0.93), laps=8)
        clear = _race(track, duel(slow=0.90, fast=0.93), laps=8, racing=False)
        cost[name] = racing.of(2).total_time - clear.of(2).total_time
    assert cost["synthetic_street_circuit"] > cost["synthetic_power_circuit"]


def test_a_better_racer_is_harder_to_pass(session_track, duel):
    """Racecraft acts on how much faster the attacker has to be, not on a roll."""
    soft = _race(session_track, duel(slow=0.90, fast=0.93, racecraft=0.60), laps=10)
    stout = _race(session_track, duel(slow=0.90, fast=0.93, racecraft=0.99), laps=10)
    assert len([m for m in stout.overtakes if m.attacker == 2]) <= len(
        [m for m in soft.overtakes if m.attacker == 2]
    )


# -- what a recorded overtake has to mean ------------------------------------


def test_where_a_tow_is_worth_nothing_racing_cannot_pay(street_track, duel):
    """A fight at a circuit with no straights can only cost.

    Somewhere with a long enough straight a slipstream battle really is quicker
    than running alone, and the engine says so.  Where there is nowhere to use
    a tow there is nothing to win, so a car that comes out of a fight ahead of
    the race it would have had alone is a car whose plan and whose execution
    disagreed -- it kept a plan made in clean air while banking a tow it never
    planned for.  That is Phase 5's frozen grip failing in a new costume.
    """
    racing = _race(street_track, duel(slow=0.90, fast=0.93), laps=4)
    clear = _race(street_track, duel(slow=0.90, fast=0.93), laps=4, racing=False)
    for car in (1, 2):
        assert racing.of(car).total_time >= clear.of(car).total_time - 1e-9


def test_a_car_in_clean_air_drives_exactly_the_lap_it_would_have_alone(
    street_track, car, perfect_driver
):
    """Racing is a thing that happens to a car with somebody in front of it.

    A car on its own has to be untouched by every part of it -- the stepping,
    the traffic query, the re-planning -- to the last bit, or the cost of a
    fight is being measured against the wrong reference.
    """
    from f1_race_engine.core.rng import RngHub
    from f1_race_engine.simulation import LapSimulator
    from f1_race_engine.simulation.traffic import CLEAR

    class Nobody:
        def preview(self, **_):
            return CLEAR

        def at(self, **_):
            return CLEAR

    alone = LapSimulator(street_track, car, perfect_driver, rng=RngHub(3)).simulate(
        lap=2, record_telemetry=False
    )
    drive = LapSimulator(street_track, car, perfect_driver, rng=RngHub(3)).simulate(
        lap=2, record_telemetry=False, traffic=Nobody(), stride=3, run=False
    )
    drive.run()
    assert drive.result.lap_time == alone.lap_time


def test_every_recorded_overtake_is_a_real_change_of_position(session_track, duel):
    """A pass is a fact about the road, so the trace has to agree with it: the
    attacker clearly behind before, clearly ahead after."""
    result = _race(session_track, duel(slow=0.84, fast=0.99), laps=10)
    assert result.overtakes
    length = session_track.length
    for move in result.overtakes:
        when = result.timing.time_at(move.attacker, (move.lap - 1) * length + move.distance)
        assert when is not None
        after = (
            result.timing.distance_at(move.attacker, when)
            - result.timing.distance_at(move.defender, when)
        )
        assert after > 0.0
        before = (
            result.timing.distance_at(move.attacker, when - 5.0)
            - result.timing.distance_at(move.defender, when - 5.0)
        )
        assert before < after


def test_nobody_passes_the_same_car_twice_in_one_lap(session_track, duel):
    """Two cars nose to tail trade the odd inch back and forth all lap without
    either of them having overtaken anything."""
    result = _race(session_track, duel(slow=0.90, fast=0.92), laps=10)
    seen = set()
    for move in result.overtakes:
        pair = (move.lap, frozenset((move.attacker, move.defender)))
        assert pair not in seen
        seen.add(pair)


def test_racing_leaves_the_timing_tower_able_to_answer(session_track, duel):
    """The trace is read by bisection in both directions, so a race that feeds
    it samples as it is driven has to leave it sorted -- otherwise every gap
    and every position read afterwards is quietly wrong."""
    result = _race(session_track, duel(slow=0.90, fast=0.93), laps=6)
    winner = result.classification[0]
    for row in result.classification[1:]:
        assert row.gap.seconds == pytest.approx(
            row.total_time - winner.total_time, rel=1e-9
        )
    for car in (1, 2):
        assert result.timing.time_at(car, 6 * session_track.length) is not None


def test_a_bigger_field_changes_everybody_else(fast_track, make_entry, lineup):
    """The other half of Phase 6's isolation test.

    ``test_adding_a_car_does_not_change_anyone_else`` says randomness must not
    leak between competitors.  Cars must, though: a field with three more cars
    in it puts somebody in somebody's way, and from here on that is supposed to
    show up in their race.
    """
    def race(count):
        entries = [make_entry(i + 1, d) for i, d in enumerate(lineup[:count])]
        result = RaceSession(
            fast_track, entries, laps=3, rng=RngHub(7), racing=True
        ).run()
        return {row.car_number: row.total_time for row in result.classification}

    small, large = race(2), race(5)
    assert any(small[car] != large[car] for car in small)


# -- reproducibility ---------------------------------------------------------


def test_a_race_with_traffic_is_reproducible(session_track, duel):
    def once():
        result = _race(session_track, duel(slow=0.88, fast=0.96), laps=6)
        return (
            [row.total_time for row in result.classification],
            [(m.lap, m.attacker, m.defender) for m in result.overtakes],
        )

    assert once() == once()


def test_a_stepped_lap_matches_a_whole_one(fast_track, car, perfect_driver):
    """The driving loop is the same loop whether it is paused or not, and the
    pausing is what lets a field of cars race each other."""
    from f1_race_engine.simulation import LapSimulator

    whole = LapSimulator(
        fast_track, car, perfect_driver, rng=RngHub(11)
    ).simulate(record_telemetry=False)
    drive = LapSimulator(
        fast_track, car, perfect_driver, rng=RngHub(11)
    ).simulate(record_telemetry=False, run=False)
    while drive.advance():
        pass
    assert drive.result.lap_time == whole.lap_time


def test_an_unfinished_lap_has_no_result(fast_track, car, perfect_driver):
    from f1_race_engine.core.errors import SimulationError
    from f1_race_engine.simulation import LapSimulator

    drive = LapSimulator(
        fast_track, car, perfect_driver, rng=RngHub(11)
    ).simulate(record_telemetry=False, run=False)
    with pytest.raises(SimulationError):
        drive.result
