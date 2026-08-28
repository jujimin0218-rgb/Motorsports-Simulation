"""A session with more than one car in it.

Phase 6's job is not to make cars fight each other -- that is Phase 9 -- but to
establish that many cars can share a circuit, a clock and a set of conditions
while each one keeps its own state, and that the result is the same every time.

Two properties matter more than anything else here, and both are tested:

**Cars do not perturb each other.** Every entry gets its own hub spawned from
the session seed, so the field can grow or shrink without changing anybody
else's lap times.  Randomness that leaks between competitors is the single
easiest way to make a race simulator irreproducible, and rule 36 forbids it.

**Position and gap come from distance and time.** The session never sorts by
lap time or accumulates differences; it feeds distances and times to
:mod:`~f1_race_engine.race.timing`, which answers both questions properly
(rule 28).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Sequence

from ..core.config import SimulationConfig
from ..core.errors import EntryError
from ..core.events import Event, EventBus
from ..core.rng import RngHub
from ..core.units import Seconds, format_lap_time
from ..environment.conditions import AmbientConditions
from ..environment.evolution import TrackEvolution
from ..environment.weather import WeatherModel
from ..simulation.lap import LapResult, LapSimulator
from ..track.model import Track
from ..track.surface import TrackConditions
from .entry import PitStop, RaceEntry
from .grid import Launch, launch_from_rest, reaction_time, starting_grid
from .pitlane import PitLane, pit_loss
from .timing import Gap, LapRecord, TimingTower

__all__ = ["Classification", "LapCompleted", "RaceResult", "RaceSession"]


@dataclass(frozen=True)
class LapCompleted(Event):
    """Published when a car crosses the line.  Phase 11 listens to this."""

    car_number: int = 0
    lap: int = 0
    lap_time: Seconds = 0.0
    position: int = 0


@dataclass(frozen=True)
class Classification:
    """One car's finishing position."""

    position: int
    car_number: int
    driver_name: str
    abbreviation: str
    team: str
    vehicle_name: str
    laps_completed: int
    total_time: Seconds
    gap: Gap
    """To the winner, at the moment the winner finished."""

    interval: Gap
    """To the car classified ahead, at the same moment."""

    best_lap: Seconds
    compound: str
    tyre_wear: float
    fuel_remaining: float
    mistakes: int
    pit_stops: int = 0

    @property
    def formatted_time(self) -> str:
        return format_lap_time(self.total_time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "position": self.position,
            "car_number": self.car_number,
            "driver": self.driver_name,
            "abbreviation": self.abbreviation,
            "team": self.team,
            "vehicle": self.vehicle_name,
            "laps_completed": self.laps_completed,
            "total_time": self.total_time,
            "gap": self.gap.formatted,
            "interval": self.interval.formatted,
            "best_lap": self.best_lap,
            "best_lap_formatted": format_lap_time(self.best_lap),
            "compound": self.compound,
            "tyre_wear": self.tyre_wear,
            "fuel_remaining": self.fuel_remaining,
            "mistakes": self.mistakes,
            "pit_stops": self.pit_stops,
        }


@dataclass(frozen=True)
class RaceResult:
    """Everything that happened, and who won."""

    track_name: str
    laps: int
    classification: tuple[Classification, ...]
    timing: TimingTower = field(repr=False)
    entries: tuple[RaceEntry, ...] = field(default=(), repr=False)
    fastest_lap: LapRecord | None = None

    @property
    def winner(self) -> Classification | None:
        return self.classification[0] if self.classification else None

    def of(self, car_number: int) -> Classification:
        for row in self.classification:
            if row.car_number == car_number:
                return row
        raise EntryError(f"car {car_number} did not take part")

    def to_dict(self, *, include_laps: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "track": self.track_name,
            "laps": self.laps,
            "classification": [row.to_dict() for row in self.classification],
        }
        if self.fastest_lap is not None:
            payload["fastest_lap"] = self.fastest_lap.to_dict()
        if include_laps:
            payload["lap_records"] = {
                str(car): [record.to_dict() for record in self.timing.records(car)]
                for car in self.timing.cars
            }
        return payload

    def format(self) -> str:
        """The timing screen, as a human would read it."""
        lines = [
            f"{self.track_name} -- {self.laps} laps",
            "",
            f"{'pos':>3} {'car':>3} {'driver':<20}{'laps':>5}{'time':>11}"
            f"{'gap':>11}{'interval':>10}{'best':>10}{'tyre':>7}",
            "-" * 83,
        ]
        for row in self.classification:
            lines.append(
                f"{row.position:>3} {row.car_number:>3} {row.driver_name:<20}"
                f"{row.laps_completed:>5}{row.formatted_time:>11}"
                f"{row.gap.formatted if row.position > 1 else '':>11}"
                f"{row.interval.formatted if row.position > 1 else '':>10}"
                f"{format_lap_time(row.best_lap):>10}"
                f"{row.compound + ' ' + format(row.tyre_wear, '.0%'):>7}"
            )
        if self.fastest_lap is not None:
            lines.append("")
            lines.append(
                f"fastest lap: car {self.fastest_lap.car_number} "
                f"{self.fastest_lap.formatted} on lap {self.fastest_lap.lap}"
            )
        return "\n".join(lines)


class RaceSession:
    """Runs a field of cars over a number of laps."""

    __slots__ = (
        "track", "entries", "laps", "ambient", "conditions", "config",
        "rng", "events", "timing", "weather", "evolution", "pit_lane",
        "standing_start", "launches", "_simulators", "_sector_lengths",
    )

    def __init__(
        self,
        track: Track,
        entries: Iterable[RaceEntry],
        *,
        laps: int,
        rng: RngHub | None = None,
        ambient: AmbientConditions | None = None,
        conditions: TrackConditions | None = None,
        config: SimulationConfig | None = None,
        events: EventBus | None = None,
        weather: WeatherModel | None = None,
        evolution: TrackEvolution | None = None,
        pit_lane: PitLane | None = None,
        standing_start: bool = False,
    ) -> None:
        self.entries = tuple(entries)
        if not self.entries:
            raise EntryError("a session needs at least one entry")
        numbers = [entry.car_number for entry in self.entries]
        if len(set(numbers)) != len(numbers):
            raise EntryError("car numbers must be unique within a session")
        if laps < 1:
            raise EntryError("a session must run at least one lap")

        self.track = track
        self.laps = laps
        self.ambient = ambient or AmbientConditions()
        self.config = config or self.entries[0].vehicle.config
        self.conditions = conditions
        self.rng = rng or RngHub(self.config.randomness.seed)
        self.events = events
        self.weather = weather
        self.evolution = evolution
        self.pit_lane = pit_lane or PitLane.for_track(track.length)
        if evolution is not None and conditions is None:
            self.conditions = evolution.conditions
        if weather is not None:
            self.ambient = weather.state.ambient
        self.standing_start = standing_start
        self.launches: dict[int, Launch] = {}
        self.timing = TimingTower(track.length)
        self._sector_lengths = _sector_lengths(track)

        # One hub per car, derived from the session seed by name.  Adding or
        # removing an entry cannot shift anybody else's draws.
        self._simulators = {
            entry.car_number: LapSimulator(
                track, entry.vehicle, entry.driver,
                rng=self.rng.spawn(f"car.{entry.car_number}"),
                ambient=self.ambient, conditions=self.conditions, config=self.config,
            )
            for entry in self.entries
        }

    # -- running it ----------------------------------------------------------

    def run(
        self,
        *,
        qualifying: bool = False,
        on_lap: Callable[[RaceEntry, LapResult], None] | None = None,
    ) -> RaceResult:
        """Run the session and classify it."""
        elapsed = {entry.car_number: 0.0 for entry in self.entries}
        for entry in self.entries:
            self.timing.start(entry.car_number)
        if self.standing_start:
            self.launches = self._launch_field()
            for car, launch in self.launches.items():
                elapsed[car] = launch.total

        for lap in range(1, self.laps + 1):
            lap_times: list[float] = []
            for entry in self.entries:
                simulator = self._simulators[entry.car_number]
                launch = self.launches.get(entry.car_number) if lap == 1 else None
                result = simulator.simulate(
                    lap=lap,
                    fuel_mass=entry.fuel_mass,
                    tyre_state=entry.tyres,
                    ers_state=entry.energy,
                    qualifying=qualifying,
                    record_telemetry=False,
                    start_speed=launch.exit_speed if launch is not None else None,
                )
                entry.fuel_mass = max(entry.fuel_mass - result.fuel_used, 0.0)
                lap_time = result.lap_time

                stop = self._pit_stop(entry, result, lap)
                if stop is not None:
                    lap_time += stop.loss

                lap_times.append(lap_time)
                elapsed[entry.car_number] += lap_time

                self.timing.record(
                    LapRecord(
                        car_number=entry.car_number,
                        lap=lap,
                        lap_time=lap_time,
                        elapsed=elapsed[entry.car_number],
                        distance=lap * self.track.length,
                        sector_times=result.sector_times,
                        compound=entry.compound,
                        tyre_wear=entry.tyres.wear,
                        fuel_mass=entry.fuel_mass,
                        energy_remaining=entry.energy.energy_remaining,
                        mistakes=len(result.mistakes),
                        pitted=stop is not None,
                    ),
                    sector_lengths=self._sector_lengths,
                )
                if on_lap is not None:
                    on_lap(entry, result)
                if self.events is not None:
                    self.events.emit(
                        LapCompleted(
                            time=elapsed[entry.car_number],
                            car_number=entry.car_number,
                            lap=lap,
                            lap_time=lap_time,
                            position=0,
                        )
                    )

            self._advance_world(lap_times)

        return self._classify()

    # -- getting off the line ------------------------------------------------

    def _launch_field(self) -> dict[int, Launch]:
        """Every car's start: a reaction, then a real acceleration from rest.

        The grid slot is a distance behind the line, so a car starting tenth
        has further to go than the car on pole and pays for it in seconds --
        which is the whole of the grid penalty in this engine.  The launch
        itself is the car's own acceleration model integrated from zero, so a
        car with more traction gets away better and a wet grid punishes
        everybody.
        """
        grid = starting_grid(max(len(self.entries), 1))
        slots = {slot.position: slot for slot in grid}
        water = self._mean_water_depth()
        # The grid is on the road like everything else, so it has the road's
        # grip: green, rubbered in, or wet.
        start_line = self.track.state_at(0.0, self.conditions)
        launches: dict[int, Launch] = {}
        for index, entry in enumerate(
            sorted(
                self.entries,
                key=lambda e: (e.grid_position is None, e.grid_position or 0),
            ),
            start=1,
        ):
            slot = slots.get(entry.grid_position or index, grid[-1])
            limits = self._simulators[entry.car_number]
            reaction = reaction_time(
                entry.driver, limits.rng, lap=0, config=self.config
            )
            launches[entry.car_number] = launch_from_rest(
                entry.vehicle,
                slot.distance_back,
                ambient=self.ambient,
                mass=entry.vehicle.mass.total_mass(entry.fuel_mass),
                tyre_state=entry.tyres,
                surface_grip=start_line.grip,
                water_depth=max(water, start_line.water_depth),
                reaction=reaction,
            )
        return launches

    # -- the world moves while they race -------------------------------------

    def _advance_world(self, lap_times: Sequence[float]) -> None:
        """Move the weather and the track surface on by one lap of running.

        Applied once per lap of the field rather than once per car, so every
        car in a lap meets the same track and the entry list's order still
        cannot change anybody's result.  Which car is on a slightly greener
        track than which other car is a question about cars sharing a circuit,
        and that is Phase 9's.
        """
        if not lap_times:
            return
        duration = sum(lap_times) / len(lap_times)

        state = None
        if self.weather is not None:
            state = self.weather.advance(duration)
            self.ambient = state.ambient
        if self.evolution is not None:
            if state is not None:
                self.evolution.apply_weather(state, duration)
            self.evolution.run_laps(float(len(lap_times)))
        if state is None and self.evolution is None:
            return
        for simulator in self._simulators.values():
            simulator.set_conditions(
                ambient=self.ambient if state is not None else None,
                conditions=self.conditions,
            )

    # -- stopping ------------------------------------------------------------

    def _pit_stop(
        self, entry: RaceEntry, result: LapResult, lap: int
    ) -> PitStop | None:
        """Ask this car's strategist whether to come in, and charge it if so."""
        strategy = entry.strategy
        if strategy is None:
            return None
        strategy.lap_completed()
        if not strategy.compounds:
            strategy.compounds = entry.compounds
        if not strategy.compounds:
            return None

        water = self._mean_water_depth()
        wanted = strategy.decide(
            lap=lap,
            laps_remaining=self.laps - lap,
            tyres=entry.tyres,
            water_depth=water,
            speed=result.average_speed,
        )
        if wanted is None:
            return None

        loss = pit_loss(
            entry.vehicle,
            self.pit_lane,
            result.profile,
            ambient=self.ambient,
            mass=entry.vehicle.mass.total_mass(entry.fuel_mass),
            tyre_state=entry.tyres,
            water_depth=water,
        )
        reason = (
            "conditions"
            if wanted.is_wet_weather != entry.tyres.is_wet_weather
            else ("worn" if entry.tyres.wear >= strategy.wear_limit else "plan")
        )
        stop = PitStop(
            lap=lap,
            from_compound=entry.tyres.compound.code,
            to_compound=wanted.code,
            loss=loss.total,
            reason=reason,
        )
        entry.pit_stops.append(stop)
        entry.fit(wanted)
        strategy.record_stop(wanted)
        return stop

    def _mean_water_depth(self) -> float:
        if self.evolution is not None:
            return self.evolution.mean_water_depth
        if self.conditions is None:
            return 0.0
        count = len(self.conditions)
        if count == 0:
            return 0.0
        return sum(self.conditions[i].water_depth for i in range(count)) / count

    # -- classifying it ------------------------------------------------------

    def _classify(self) -> RaceResult:
        """Order the field the way a race is actually ordered.

        The chequered flag falls when the winner finishes, and every other car
        takes it the next time it crosses the line.  So each car's race is its
        first lap completed at or after that moment -- which is 20 laps for
        somebody two seconds behind and 19 for somebody a lap down, exactly as
        a result sheet reads.  Laps run past the flag are simulated (the field
        is stepped in lockstep) and then not classified.

        The gaps are measured at the finish line, because that is the place
        both cars actually passed: same place, two times.  A car that never
        reached it is reported as laps down, which is the only honest thing to
        say about it.
        """
        finish = min(
            records[-1].elapsed
            for car in self.timing.cars
            if (records := self.timing.records(car))
        )
        flags = {car: _flag_lap(self.timing.records(car), finish)
                 for car in self.timing.cars}
        order = sorted(
            flags,
            key=lambda car: (-flags[car].lap, flags[car].elapsed, car),
        )
        by_number = {entry.car_number: entry for entry in self.entries}
        leader = order[0]
        line = flags[leader].lap * self.track.length

        classification: list[Classification] = []
        fastest: LapRecord | None = None
        for index, car in enumerate(order):
            entry = by_number[car]
            flag = flags[car]
            ahead = order[index - 1] if index else car
            run = [r for r in self.timing.records(car) if r.lap <= flag.lap]
            # A car classified on fewer laps is a lap down, whatever its clock
            # says: it never covered the winner's distance before the flag.
            for record in run:
                if fastest is None or record.lap_time < fastest.lap_time:
                    fastest = record
            gap = _behind(self.timing, car, leader, flags, line)
            interval = _behind(self.timing, car, ahead, flags, line)
            classification.append(
                Classification(
                    position=index + 1,
                    car_number=car,
                    driver_name=entry.driver.name,
                    abbreviation=entry.driver.abbreviation,
                    team=entry.team,
                    vehicle_name=entry.vehicle.name,
                    laps_completed=flag.lap,
                    total_time=flag.elapsed,
                    gap=gap,
                    interval=interval,
                    best_lap=min((r.lap_time for r in run), default=0.0),
                    compound=flag.compound,
                    tyre_wear=flag.tyre_wear,
                    fuel_remaining=flag.fuel_mass,
                    mistakes=sum(r.mistakes for r in run),
                    pit_stops=sum(1 for r in run if r.pitted),
                )
            )

        return RaceResult(
            track_name=self.track.name,
            laps=self.laps,
            classification=tuple(classification),
            timing=self.timing,
            entries=self.entries,
            fastest_lap=fastest,
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"RaceSession({self.track.name!r}, {len(self.entries)} cars, "
            f"{self.laps} laps)"
        )


def _sector_lengths(track: Track) -> tuple[float, ...]:
    """Distance covered in each sector, m."""
    edges: Sequence[float] = (0.0, *track.sector_boundaries, track.length)
    return tuple(b - a for a, b in zip(edges, edges[1:]))


def _behind(
    timing: TimingTower,
    car: int,
    ahead: int,
    flags: dict[int, LapRecord],
    line: float,
) -> Gap:
    """How far ``car`` finished behind ``ahead``.

    Laps when the two took the flag on different laps, seconds when they took
    it on the same one -- measured where they both crossed it.
    """
    down = flags[ahead].lap - flags[car].lap
    if down > 0:
        return Gap(seconds=0.0, laps=down)
    return timing.gap_at(car, ahead, line)


def _flag_lap(records: Sequence[LapRecord], finish: Seconds) -> LapRecord:
    """The lap on which this car took the chequered flag.

    The first one it completed at or after the winner did; a car that somehow
    never got there is classified on its last completed lap.
    """
    for record in records:
        if record.elapsed >= finish:
            return record
    return records[-1]
