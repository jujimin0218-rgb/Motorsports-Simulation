"""Core state primitives shared by every simulated entity.

Project rule 4 keeps the physics core and the race core apart, and rule 27
requires each car to own an independent state.  This module holds only the
pieces both sides need:

* :class:`SimulationClock` -- the single source of simulated time;
* :class:`Snapshotable` -- the contract every state object implements so that
  results can be exported (rule 45) and streamed to an external 3D client
  (rule 44) without the engine knowing anything about the consumer;
* :class:`StateSnapshot` / :class:`SnapshotRecorder` -- capture of state over
  time, which is what telemetry export and debug visualisation both consume.

Vehicle, tyre and race state arrive in later phases and build on
:class:`MutableState`.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Snapshotable(Protocol):
    """Anything that can describe itself as plain, JSON-compatible data."""

    def snapshot(self) -> dict[str, Any]:  # pragma: no cover - protocol
        ...


@dataclass
class MutableState:
    """Base class for evolving state objects (vehicle, tyre, race, ...).

    Subclasses stay plain mutable dataclasses -- the simulation updates them in
    place every step, and allocating a new frozen object per segment per car
    per lap would dominate the runtime.
    """

    def snapshot(self) -> dict[str, Any]:
        """Return a deep, plain-data copy of this state."""
        return asdict(self)

    def restore(self, data: dict[str, Any]) -> None:
        """Restore field values from :meth:`snapshot` output."""
        known = {f.name for f in fields(self)}
        unknown = set(data) - known
        if unknown:
            raise KeyError(
                f"unknown {type(self).__name__} field(s): {', '.join(sorted(unknown))}"
            )
        for key, value in data.items():
            current = getattr(self, key)
            if isinstance(current, MutableState) and isinstance(value, dict):
                current.restore(value)
            else:
                setattr(self, key, value)


@dataclass
class SimulationClock:
    """Simulated time.

    Time is advanced by the lap simulation as ``dt = ds / v`` (rule 26), never
    by a wall clock.  ``step_index`` counts integration steps, which makes
    reproducibility failures easy to bisect.
    """

    time: float = 0.0
    step_index: int = 0

    def advance(self, dt: float) -> float:
        """Advance by ``dt`` seconds and return the new time."""
        if dt < 0.0:
            raise ValueError(f"cannot advance the clock by {dt} s")
        self.time += dt
        self.step_index += 1
        return self.time

    def reset(self, time: float = 0.0) -> None:
        self.time = time
        self.step_index = 0

    def snapshot(self) -> dict[str, Any]:
        return {"time": self.time, "step_index": self.step_index}


@dataclass(frozen=True, slots=True)
class StateSnapshot:
    """One immutable capture of some state at a point in simulated time."""

    label: str
    time: float
    distance: float
    data: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "time": self.time,
            "distance": self.distance,
            "data": self.data,
        }


@dataclass
class SnapshotRecorder:
    """Collects snapshots for telemetry export and debug plots.

    Recording is opt-in and bounded: a full race at 1 m resolution is millions
    of samples, so ``stride`` keeps the volume sane while still producing a
    faithful trace.
    """

    enabled: bool = False
    stride: int = 1
    _samples: list[StateSnapshot] = field(default_factory=list, repr=False)
    _seen: int = field(default=0, repr=False)

    def record(self, snapshot: StateSnapshot) -> None:
        if not self.enabled:
            return
        if self._seen % self.stride == 0:
            self._samples.append(snapshot)
        self._seen += 1

    @property
    def samples(self) -> tuple[StateSnapshot, ...]:
        return tuple(self._samples)

    def clear(self) -> None:
        self._samples.clear()
        self._seen = 0

    def to_dict(self) -> dict[str, Any]:
        return {"samples": [s.to_dict() for s in self._samples]}

    def to_json(self, *, indent: int | None = None) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    def __len__(self) -> int:
        return len(self._samples)


def as_plain_data(value: Any) -> Any:
    """Best-effort conversion of engine objects to JSON-compatible data."""
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, Snapshotable):
        return value.snapshot()
    if isinstance(value, (list, tuple)):
        return [as_plain_data(v) for v in value]
    if isinstance(value, dict):
        return {k: as_plain_data(v) for k, v in value.items()}
    return value
