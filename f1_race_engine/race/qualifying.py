"""Qualifying (project rule 27).

A knockout session, run for real: every car goes out, warms a set of tyres on
an out-lap, does a flying lap that counts, and comes back in.  The slowest are
eliminated and the rest go again.  The grid is whatever that produces.

Three things fall out of running it rather than ranking the cars by pace, and
all three are real:

* **the track comes to the drivers.**  Rubber goes down as the session runs, so
  a lap late in Q3 is on a quicker circuit than a lap early in Q1 -- and the
  later segments are quicker for everybody, without anybody being given
  anything.
* **the out-lap matters.**  A set of tyres comes out of the blankets below its
  window and has one lap to get into it.  That is simulated, so a compound that
  warms up quickly is worth something here that it is not worth in a race.
* **the weather does not wait.**  A shower during Q1 rearranges a grid, because
  the session asks which tyre suits the track it has and the answer changes.

Phase 9 adds traffic, tows and the scramble at the end of Q1.  Until then every
car gets a clear lap, which is honest rather than pretended.
"""

from __future__ import annotations

from collections.abc import Callable

from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from ..core.config import SimulationConfig
from ..core.errors import EntryError
from ..core.rng import RngHub
from ..core.units import Seconds, format_lap_time
from ..environment.conditions import AmbientConditions
from ..environment.evolution import TrackEvolution
from ..environment.weather import WeatherModel
from ..simulation.lap import LapSimulator
from ..track.model import Track
from ..track.surface import TrackConditions
from ..tyres.compound import TyreCompound
from .entry import RaceEntry
from .grid import GridSlot, starting_grid
from .strategy import compound_for_conditions

__all__ = [
    "DEFAULT_FORMAT",
    "QualifyingLap",
    "QualifyingResult",
    "QualifyingSegment",
    "QualifyingSession",
]


@dataclass(frozen=True, slots=True)
class QualifyingSegment:
    """One knockout segment."""

    name: str
    duration: Seconds
    eliminated: int
    """How many cars drop out at the end of it."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "duration": self.duration,
            "eliminated": self.eliminated,
        }


#: Formula 1's three-part knockout: 18, 15 and 12 minutes.
DEFAULT_FORMAT: tuple[QualifyingSegment, ...] = (
    QualifyingSegment("Q1", 1080.0, 5),
    QualifyingSegment("Q2", 900.0, 5),
    QualifyingSegment("Q3", 720.0, 0),
)


@dataclass(frozen=True, slots=True)
class QualifyingLap:
    """One flying lap that counted."""

    car_number: int
    segment: str
    run: int
    lap_time: Seconds
    compound: str
    session_time: Seconds
    """When in the session the lap was set -- a later lap is on a better track."""

    @property
    def formatted(self) -> str:
        return format_lap_time(self.lap_time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "car_number": self.car_number,
            "segment": self.segment,
            "run": self.run,
            "lap_time": self.lap_time,
            "lap_time_formatted": self.formatted,
            "compound": self.compound,
            "session_time": self.session_time,
        }


@dataclass(frozen=True)
class QualifyingResult:
    """The grid, and how it was arrived at."""

    track_name: str
    order: tuple[int, ...]
    """Car numbers, pole first."""

    best: dict[int, Seconds]
    """Each car's best lap of the session."""

    eliminated_in: dict[int, str]
    """Which segment each car went out in; the survivors map to the last one."""

    laps: tuple[QualifyingLap, ...] = field(repr=False, default=())
    grid: tuple[GridSlot, ...] = field(repr=False, default=())

    @property
    def pole(self) -> int | None:
        return self.order[0] if self.order else None

    def slot_for(self, car_number: int) -> GridSlot:
        for position, car in enumerate(self.order, start=1):
            if car == car_number:
                return self.grid[position - 1]
        raise EntryError(f"car {car_number} did not qualify")

    def best_in(self, segment: str) -> dict[int, Seconds]:
        """Each car's best lap within one segment."""
        out: dict[int, Seconds] = {}
        for lap in self.laps:
            if lap.segment != segment:
                continue
            if lap.car_number not in out or lap.lap_time < out[lap.car_number]:
                out[lap.car_number] = lap.lap_time
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "track": self.track_name,
            "order": list(self.order),
            "pole": self.pole,
            "best": {str(k): v for k, v in self.best.items()},
            "eliminated_in": {str(k): v for k, v in self.eliminated_in.items()},
            "laps": [lap.to_dict() for lap in self.laps],
        }

    def format(self, names: dict[int, str] | None = None) -> str:
        labels = names or {}
        pole_time = self.best.get(self.order[0]) if self.order else None
        lines = [
            f"{self.track_name} -- qualifying",
            "",
            f"{'pos':>3} {'car':>3} {'driver':<20}{'best':>10}{'gap':>9}{'out in':>8}",
            "-" * 55,
        ]
        for position, car in enumerate(self.order, start=1):
            time = self.best.get(car)
            gap = "" if time is None or pole_time is None or position == 1 else (
                f"+{time - pole_time:.3f}"
            )
            lines.append(
                f"{position:>3} {car:>3} {labels.get(car, ''):<20}"
                f"{format_lap_time(time) if time else '--':>10}{gap:>9}"
                f"{self.eliminated_in.get(car, ''):>8}"
            )
        return "\n".join(lines)


class QualifyingSession:
    """Runs a knockout qualifying session and produces a grid."""

    __slots__ = (
        "track", "entries", "format", "ambient", "conditions", "config", "rng",
        "weather", "evolution", "fuel_mass", "out_lap_effort", "max_runs",
        "_simulators", "_laps", "_clock",
    )

    def __init__(
        self,
        track: Track,
        entries: Iterable[RaceEntry],
        *,
        segments: Sequence[QualifyingSegment] = DEFAULT_FORMAT,
        rng: RngHub | None = None,
        ambient: AmbientConditions | None = None,
        conditions: TrackConditions | None = None,
        config: SimulationConfig | None = None,
        weather: WeatherModel | None = None,
        evolution: TrackEvolution | None = None,
        fuel_mass: float = 20.0,
        out_lap_effort: float = 0.72,
        max_runs: int = 3,
    ) -> None:
        self.entries = tuple(entries)
        if not self.entries:
            raise EntryError("a session needs at least one entry")
        numbers = [entry.car_number for entry in self.entries]
        if len(set(numbers)) != len(numbers):
            raise EntryError("car numbers must be unique within a session")
        if not segments:
            raise EntryError("qualifying needs at least one segment")

        self.track = track
        self.format = tuple(segments)
        self.config = config or self.entries[0].vehicle.config
        self.rng = rng or RngHub(self.config.randomness.seed)
        self.weather = weather
        self.evolution = evolution
        self.conditions = conditions
        if evolution is not None and conditions is None:
            self.conditions = evolution.conditions
        self.ambient = ambient or (
            weather.state.ambient if weather is not None else AmbientConditions()
        )
        self.fuel_mass = fuel_mass
        self.out_lap_effort = out_lap_effort
        self.max_runs = max_runs
        self._laps: list[QualifyingLap] = []
        self._clock = 0.0

        self._simulators = {
            entry.car_number: LapSimulator(
                track, entry.vehicle, entry.driver,
                rng=self.rng.spawn(f"qualifying.{entry.car_number}"),
                ambient=self.ambient, conditions=self.conditions, config=self.config,
            )
            for entry in self.entries
        }

    @property
    def laps(self) -> tuple[QualifyingLap, ...]:
        """Every flying lap that has counted so far.

        Readable while the session is still running, which is what lets a
        caller show the order building up rather than only the grid it ends
        with.  Reporting only: the session does not read this back.
        """
        return tuple(self._laps)

    # -- running it ----------------------------------------------------------

    def run(
        self,
        on_segment: Callable[[str, int, int], None] | None = None,
        *,
        on_lap: Callable[[QualifyingLap], None] | None = None,
    ) -> QualifyingResult:
        """Run every segment and return the grid.

        ``on_segment`` is called as each segment finishes, with its name and
        how many of how many are done.  ``on_lap`` is called with every flying
        lap that counts, as it is set, for a caller that wants to show the
        order building up rather than three jumps.  Qualifying is a couple of
        minutes of simulation and a caller that cannot say how far along it is
        has to show a spinner that never moves, which is indistinguishable
        from a hang.  Purely for reporting: nothing either does can change the
        session.
        """
        by_number = {entry.car_number: entry for entry in self.entries}
        surviving = list(by_number)
        order: list[int] = []
        eliminated_in: dict[int, str] = {}
        best: dict[int, Seconds] = {}

        for index, segment in enumerate(self.format):
            times = self._run_segment(
                segment, [by_number[c] for c in surviving], on_lap
            )
            for car, time in times.items():
                if car not in best or time < best[car]:
                    best[car] = time

            ranked = sorted(
                surviving,
                key=lambda car: (times.get(car, float("inf")), car),
            )
            drop = segment.eliminated if index < len(self.format) - 1 else 0
            drop = min(drop, max(len(ranked) - 1, 0))
            cut = len(ranked) - drop
            survivors, knocked = ranked[:cut], ranked[cut:]
            for car in knocked:
                eliminated_in[car] = segment.name

            # A knockout grid is built from the back: whoever is still in goes
            # above whoever just went out, who in turn go above everybody
            # eliminated earlier.  Rebuilding it this way each segment means the
            # front of the grid is always the latest ordering and the back never
            # moves again.
            already_out = [car for car in order if car not in ranked]
            order = survivors + knocked + already_out
            surviving = survivors
            if on_segment is not None:
                on_segment(segment.name, index + 1, len(self.format))
            if not surviving:
                break

        for car in surviving:
            eliminated_in.setdefault(car, self.format[-1].name)

        final = tuple(order)
        return QualifyingResult(
            track_name=self.track.name,
            order=final,
            best=best,
            eliminated_in=eliminated_in,
            laps=tuple(self._laps),
            grid=starting_grid(max(len(final), 1)),
        )

    # -- one segment ---------------------------------------------------------

    def _run_segment(
        self,
        segment: QualifyingSegment,
        entries: Sequence[RaceEntry],
        on_lap: Callable[[QualifyingLap], None] | None = None,
    ) -> dict[int, Seconds]:
        """Run one segment; return each car's best lap in it."""
        best: dict[int, Seconds] = {}
        remaining = segment.duration

        index = self.format.index(segment)
        for run in range(1, self.max_runs + 1):
            # Every car in a wave meets the same track, so the order of the
            # entry list cannot change anybody's lap.  Which car goes out when
            # is a question about sharing a circuit, and that is Phase 9's.
            wave_duration = 0.0
            for entry in entries:
                spent, lap = self._run_once(entry, segment, run, index)
                wave_duration = max(wave_duration, spent)
                if lap is None:
                    continue
                self._laps.append(lap)
                if on_lap is not None:
                    on_lap(lap)
                if entry.car_number not in best or lap.lap_time < best[entry.car_number]:
                    best[entry.car_number] = lap.lap_time

            remaining -= wave_duration
            self._clock += wave_duration
            self._advance_world(wave_duration, len(entries) * 3.0)
            if remaining <= wave_duration:
                break
        return best

    def _run_once(
        self,
        entry: RaceEntry,
        segment: QualifyingSegment,
        run: int,
        segment_index: int,
    ) -> tuple[Seconds, QualifyingLap | None]:
        """One out-lap, one flying lap, one in-lap.  Returns time spent.

        The lap numbers handed to the simulator are the session's own count, so
        a driver's variation on their Q2 run is drawn from a different place in
        their stream than on their Q1 run.  Without that, run one of every
        segment would produce the same mistakes.
        """
        simulator = self._simulators[entry.car_number]
        available = entry.compounds or ()
        water = self._mean_water_depth()
        compound: TyreCompound | None = (
            compound_for_conditions(available, water) if available else None
        )
        if compound is not None:
            entry.fit(compound)

        first = segment_index * 100 + run * 3 - 2
        out = simulator.simulate(
            lap=first, fuel_mass=self.fuel_mass, tyre_state=entry.tyres,
            ers_state=entry.energy, effort=self.out_lap_effort,
            record_telemetry=False,
        )
        flying = simulator.simulate(
            lap=first + 1, fuel_mass=self.fuel_mass - out.fuel_used,
            tyre_state=entry.tyres, ers_state=entry.energy, qualifying=True,
            record_telemetry=False,
        )
        cool_down = simulator.simulate(
            lap=first + 2,
            fuel_mass=self.fuel_mass - out.fuel_used - flying.fuel_used,
            tyre_state=entry.tyres, ers_state=entry.energy, effort=self.out_lap_effort,
            record_telemetry=False,
        )
        spent = out.lap_time + flying.lap_time + cool_down.lap_time
        return spent, QualifyingLap(
            car_number=entry.car_number,
            segment=segment.name,
            run=run,
            lap_time=flying.lap_time,
            compound=entry.tyres.compound.code,
            session_time=self._clock,
        )

    # -- the world moves -----------------------------------------------------

    def _advance_world(self, duration: Seconds, car_laps: float) -> None:
        state = None
        if self.weather is not None:
            state = self.weather.advance(duration)
            self.ambient = state.ambient
        if self.evolution is not None:
            if state is not None:
                self.evolution.apply_weather(state, duration)
            self.evolution.run_laps(car_laps)
        if state is None and self.evolution is None:
            return
        for simulator in self._simulators.values():
            simulator.set_conditions(
                ambient=self.ambient if state is not None else None,
                conditions=self.conditions,
            )

    def _mean_water_depth(self) -> float:
        if self.evolution is not None:
            return self.evolution.mean_water_depth
        if self.conditions is None:
            return 0.0
        count = len(self.conditions)
        if count == 0:
            return 0.0
        return sum(self.conditions[i].water_depth for i in range(count)) / count

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"QualifyingSession({self.track.name!r}, {len(self.entries)} cars, "
            f"{len(self.format)} segments)"
        )
