"""Core state primitives."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from f1_race_engine.core.state import (
    MutableState,
    SimulationClock,
    Snapshotable,
    SnapshotRecorder,
    StateSnapshot,
    as_plain_data,
)


@dataclass
class TyreState(MutableState):
    wear: float = 0.0
    temperature: float = 90.0


@dataclass
class CarState(MutableState):
    speed: float = 0.0
    tyre: TyreState = field(default_factory=TyreState)


def test_clock_advances_and_counts_steps():
    clock = SimulationClock()
    clock.advance(1.5)
    clock.advance(2.0)
    assert clock.time == pytest.approx(3.5)
    assert clock.step_index == 2
    clock.reset()
    assert clock.time == 0.0 and clock.step_index == 0


def test_clock_rejects_time_going_backwards():
    with pytest.raises(ValueError):
        SimulationClock().advance(-1.0)


def test_clock_satisfies_the_snapshot_protocol():
    assert isinstance(SimulationClock(), Snapshotable)
    assert SimulationClock(time=2.0, step_index=3).snapshot() == {
        "time": 2.0,
        "step_index": 3,
    }


def test_state_snapshot_and_restore_round_trip():
    state = CarState(speed=80.0)
    state.tyre.wear = 0.35
    payload = state.snapshot()
    assert payload == {"speed": 80.0, "tyre": {"wear": 0.35, "temperature": 90.0}}

    restored = CarState()
    restored.restore(payload)
    assert restored.speed == 80.0
    assert restored.tyre.wear == 0.35


def test_restore_rejects_unknown_fields():
    with pytest.raises(KeyError):
        CarState().restore({"speeed": 1.0})


def test_recorder_is_opt_in_and_strided():
    recorder = SnapshotRecorder()
    for i in range(10):
        recorder.record(StateSnapshot("car", float(i), float(i), {}))
    assert len(recorder) == 0

    recorder = SnapshotRecorder(enabled=True, stride=3)
    for i in range(10):
        recorder.record(StateSnapshot("car", float(i), float(i), {"i": i}))
    assert [s.time for s in recorder.samples] == [0.0, 3.0, 6.0, 9.0]

    recorder.clear()
    assert len(recorder) == 0


def test_recorder_exports_json():
    recorder = SnapshotRecorder(enabled=True)
    recorder.record(StateSnapshot("car", 1.0, 2.0, {"speed": 80.0}))
    assert '"speed": 80.0' in recorder.to_json()


def test_as_plain_data_handles_nested_structures():
    payload = as_plain_data({"cars": [CarState(speed=5.0)], "clock": SimulationClock()})
    assert payload["cars"][0]["speed"] == 5.0
    assert payload["clock"]["time"] == 0.0
