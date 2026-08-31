"""The road has a width, and a race happens across it.

Until this, a circuit was a line: every car sat on the same point at the same
distance, an overtake was a number comparison, and a screen drawing two cars
racing had to draw one on top of the other.  The width was in the model the
whole time -- the racing line solver is bounded by it -- and nothing was
allowed to be anywhere on it.

What these pin down is the part a race can be read off: how much road there is
for a car's middle, when two of them count as alongside, whether a move exists
at all where the road is narrow, and that the timing tower remembers where
across the road a car was as well as how far along.
"""

from __future__ import annotations

import pytest

from f1_race_engine import load_track
from f1_race_engine.race.timing import LapRecord, TimingTower
from f1_race_engine.track.racing_line import CAR_WIDTH


@pytest.fixture
def bahrain():
    return load_track("bahrain")


# -- how much road there is ---------------------------------------------------


def test_the_road_has_room_for_a_cars_middle_either_side_of_the_line(bahrain):
    state = bahrain.state_at(1200.0)

    assert state.track_width > 10.0, "a grand prix circuit is not a lane"
    # Less the bit nobody uses and less half a car, because the number says
    # where the middle of the car goes.
    assert 0 < state.usable_half_width < state.track_width * 0.5


def test_two_cars_a_car_width_apart_are_alongside(bahrain):
    state = bahrain.state_at(1200.0)

    assert state.is_alongside(-CAR_WIDTH / 2, CAR_WIDTH / 2)
    assert not state.is_alongside(-0.4, 0.4), "that is one car, not two"


def test_a_real_circuit_has_room_for_two_cars(bahrain):
    """The gate every overtake is measured against."""
    state = bahrain.state_at(1200.0)

    assert state.usable_half_width >= CAR_WIDTH


def test_a_road_too_narrow_to_hold_two_cars_reports_no_room():
    """Half a car wide is a pit lane, not a place to pass."""
    from f1_race_engine.track.model import TrackState
    from f1_race_engine.track.segment import SegmentKind
    from f1_race_engine.track.surface import SurfaceType
    from f1_race_engine.track.definitions import KerbType

    narrow = TrackState(
        distance=0.0, curvature=0.0, radius=float("inf"), gradient=0.0,
        elevation=0.0, banking=0.0, grip=1.0, surface_type=SurfaceType.ASPHALT,
        roughness=0.0, track_width=4.0, sector=1, corner_id=None,
        corner_name=None, drs_zone=None, kerb=KerbType.NONE,
        kind=SegmentKind.STRAIGHT, segment_index=0, x=0.0, y=0.0, heading=0.0,
    )

    assert narrow.usable_half_width < CAR_WIDTH, "no room to put a second car"


# -- the line the road describes ----------------------------------------------


def test_the_line_stays_on_the_road(bahrain):
    """Whatever the solver decided, a car is never off the circuit."""
    for distance in range(0, int(bahrain.length), 40):
        state = bahrain.state_at(float(distance))
        assert abs(state.line_offset) <= state.track_width * 0.5


def test_a_circuit_surveyed_as_a_driven_line_needs_no_offset():
    """Every circuit shipped is a driven line already, so the line is the road
    and the offset is zero -- which is a fact worth stating rather than a
    coincidence to rely on."""
    track = load_track("bahrain")

    assert all(
        track.state_at(float(d)).line_offset == 0.0
        for d in range(0, int(track.length), 200)
    )


# -- the tower remembers where across the road ---------------------------------


def test_the_tower_remembers_where_across_the_road_a_car_was():
    tower = TimingTower(lap_length=1000.0)
    tower.start(7)
    tower.record_trace(7, (10.0, 20.0), (100.0, 200.0), (0.0, 2.0))

    assert tower.offset_at(7, 10.0) == pytest.approx(0.0)
    assert tower.offset_at(7, 20.0) == pytest.approx(2.0)
    assert tower.offset_at(7, 15.0) == pytest.approx(1.0), "interpolated, like distance"


def test_a_car_that_has_stopped_is_parked_where_it_stopped():
    tower = TimingTower(lap_length=1000.0)
    tower.start(7)
    tower.record_trace(7, (10.0,), (100.0,), (1.5,))

    assert tower.offset_at(7, 900.0) == pytest.approx(1.5), "not still drifting"


def test_a_trace_without_offsets_keeps_the_car_on_the_line():
    """Qualifying and practice do not race anybody, so they send none."""
    tower = TimingTower(lap_length=1000.0)
    tower.start(3)
    tower.record_trace(3, (5.0, 9.0), (50.0, 90.0))

    assert tower.offset_at(3, 9.0) == 0.0


def test_a_lap_record_does_not_lose_the_offsets_beside_it():
    """The three tables are index-aligned; a lap being written down displaces
    the trace samples it covers, and the offsets have to go with them."""
    tower = TimingTower(lap_length=1000.0)
    tower.start(4)
    tower.record_trace(4, (10.0, 20.0), (300.0, 600.0), (1.0, -1.0))
    tower.record(
        LapRecord(car_number=4, lap=1, lap_time=30.0, elapsed=30.0, distance=1000.0)
    )

    assert tower.offset_at(4, 30.0) == pytest.approx(0.0)
    assert tower.distance_at(4, 30.0) == pytest.approx(1000.0)


# -- a move needs room --------------------------------------------------------


def _traffic(track, **kwargs):
    from f1_race_engine.driver.model import DriverAttributes
    from f1_race_engine.race.traffic import Traffic

    return Traffic(
        track=track,
        timing=TimingTower(lap_length=track.length),
        car_number=1,
        lap=1,
        attributes=DriverAttributes(),
        **kwargs,
    )


def test_a_move_needs_two_cars_worth_of_road(bahrain):
    """Quick enough and straight enough is not the whole of it: a driver
    alongside on a road with room for one is not overtaking."""
    traffic = _traffic(bahrain)
    quick = 80.0

    assert traffic._is_passable(0.0, quick, room=CAR_WIDTH * 2)
    assert not traffic._is_passable(0.0, quick, room=CAR_WIDTH * 0.4)


def test_a_move_still_needs_a_straight(bahrain):
    """Room is necessary, not sufficient -- a hairpin is wide and unpassable."""
    traffic = _traffic(bahrain)
    hairpin = 1.0 / 25.0

    assert not traffic._is_passable(hairpin, 80.0, room=CAR_WIDTH * 2)


def test_changing_line_takes_road(bahrain):
    """A car crosses the road at a rate.  Asked to move two metres over one
    metre of road, it moves what it can and no more."""
    traffic = _traffic(bahrain)

    moved = traffic._hold_line(2.0, room=4.0, step=1.0)

    assert 0.0 < moved < 2.0, "a manoeuvre, not a teleport"


def test_a_car_never_leaves_the_road(bahrain):
    traffic = _traffic(bahrain)
    traffic.offset = 3.0

    for _ in range(50):
        traffic.offset = traffic._hold_line(99.0, room=3.5, step=10.0)

    assert traffic.offset == pytest.approx(3.5), "clamped to the road it has"
