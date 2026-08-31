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
from ..events import (
    ContactRisk,
    FlagChanged,
    IncidentRaised,
    FlagState,
    Incident,
    IncidentSeverity,
    Neutralisation,
    RaceControl,
    sample_contact,
    sample_failure,
    sample_spin,
)
from ..events.reliability import stress_from_lap
from .traffic import OvertakeAttempt, Traffic

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
    overtakes: int = 0
    """Cars this one got past."""

    retired: bool = False
    """Whether the car's race ended before the flag."""

    retirement_reason: str = ""
    """What ended it, for a car that did not finish."""

    @property
    def classified(self) -> bool:
        """Whether the car is a finisher.

        A retired car still appears on the sheet with the laps it completed --
        that is what a result sheet does -- but it is not racing anybody.
        """
        return not self.retired

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
            "overtakes": self.overtakes,
            "retired": self.retired,
            "retirement_reason": self.retirement_reason,
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
    overtakes: tuple[OvertakeAttempt, ...] = field(default=(), repr=False)
    incidents: tuple[Incident, ...] = field(default=(), repr=False)
    """Everything that went wrong, in the order it went wrong."""

    flags: tuple[tuple[int, str, str], ...] = field(default=(), repr=False)
    """Every flag change, as ``(lap, flag, reason)``."""

    @property
    def winner(self) -> Classification | None:
        """The car that won -- which is a finisher, not merely the first row."""
        for row in self.classification:
            if row.classified:
                return row
        return None

    @property
    def finishers(self) -> tuple[Classification, ...]:
        return tuple(row for row in self.classification if row.classified)

    @property
    def retirements(self) -> tuple[Classification, ...]:
        return tuple(row for row in self.classification if row.retired)

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
            "incidents": [incident.to_dict() for incident in self.incidents],
            "flags": [
                {"lap": lap, "flag": flag, "reason": reason}
                for lap, flag, reason in self.flags
            ],
        }
        if self.fastest_lap is not None:
            payload["fastest_lap"] = self.fastest_lap.to_dict()
        payload["overtakes"] = [move.to_dict() for move in self.overtakes]
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
            if row.retired:
                lines.append(
                    f"{'DNF':>3} {row.car_number:>3} {row.driver_name:<20}"
                    f"{row.laps_completed:>5}{'':>11}"
                    f"{row.retirement_reason:>32}"
                )
                continue
            lines.append(
                f"{row.position:>3} {row.car_number:>3} {row.driver_name:<20}"
                f"{row.laps_completed:>5}{row.formatted_time:>11}"
                f"{row.gap.formatted if row.position > 1 else '':>11}"
                f"{row.interval.formatted if row.position > 1 else '':>10}"
                f"{format_lap_time(row.best_lap):>10}"
                f"{row.compound + ' ' + format(row.tyre_wear, '.0%'):>7}"
            )
        if self.flags:
            lines.append("")
            for lap, flag, reason in self.flags:
                lines.append(f"  lap {lap:>3}: {reason}")
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
        "standing_start", "launches", "racing", "overtakes",
        "race_control", "incidents", "hazards", "telemetry",
        "_simulators", "_sector_lengths", "_ahead_of", "_just_passed",
        "_combat_laps", "_green_reference", "_green_profiles",
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
        racing: bool = True,
        weather: WeatherModel | None = None,
        evolution: TrackEvolution | None = None,
        pit_lane: PitLane | None = None,
        standing_start: bool = False,
        hazards: bool = True,
        telemetry: int = 0,
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
        self.racing = racing
        """Whether the cars can see each other.  Off, this is Phase 6's race:
        every car in clean air, which is a useful thing to be able to compare
        against and a much faster thing to run."""

        self.hazards = hazards
        # Keep every Nth sample of each car's lap, or nothing at zero.  A race
        # is twenty cars simulated on every lap, so recording all of it is a
        # deliberate choice a caller makes rather than the default.
        self.telemetry = telemetry
        """Whether cars can break, spin and hit each other.

        On by default, because a race simulation in which nothing ever goes
        wrong is not one.  Off, this is Phase 10's race -- every car reaches
        the flag -- which is the right thing to compare a real one against and
        the right thing for a test that is about something else."""

        self.race_control = RaceControl(
            self.rng.stream("race_control"), self.config.race_control
        )
        self.incidents: list[Incident] = []
        self._combat_laps: dict[int, float] = {
            entry.car_number: 0.0 for entry in self.entries
        }
        self._green_reference: dict[int, tuple[float, float, float, float]] = {}
        self._green_profiles: dict[int, Any] = {}

        # A session is one race.  An entry handed to it starts that race
        # running and in one piece, whatever happened to it in the last one --
        # cars get repaired between races, and a retirement does not carry.
        for entry in self.entries:
            entry.retirement = None
            entry.damage = 0.0

        self.overtakes: list[OvertakeAttempt] = []
        self._ahead_of: dict[int, set[int]] = {
            entry.car_number: set() for entry in self.entries
        }
        self._just_passed: dict[int, set[int]] = {
            entry.car_number: set() for entry in self.entries
        }
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
        if self.standing_start:
            self.launches = self._launch_field()
            for car, launch in self.launches.items():
                elapsed[car] = launch.total
        # Each car joins the tower when it reaches the line, not when the
        # lights go out.  Anchoring the whole field at zero has them away
        # together, and everything that reads a position between two lines --
        # the running order, a gap, whether a car is close enough to attack --
        # then works off a first lap that never happened.
        for entry in self.entries:
            self.timing.start(entry.car_number, elapsed=elapsed[entry.car_number])

        for lap in range(1, self.laps + 1):
            lap_times: list[float] = []
            running = [entry for entry in self.entries if entry.running]
            if not running:
                break
            neutralisation = self.race_control.neutralisation()

            if not neutralisation.is_green:
                neutral_times = self._neutralised_lap(
                    running, lap, neutralisation, elapsed
                )
                self._advance_world(neutral_times)
                self._close_lap(
                    lap,
                    running,
                    elapsed,
                    incidents=[
                        incident
                        for entry in running
                        if self.hazards
                        and (incident := self._sample_incident(entry, lap, None))
                    ],
                )
                continue

            # Cars are simulated in the order they start the lap, earliest
            # first.  That is not a convenience: it is what makes the model
            # causal.  Anybody physically in front of a car when it is out
            # there started their lap before it did -- including a car a lap up
            # the road -- so their trace already exists to be raced against,
            # and nobody has to guess where anybody is.
            drives: dict[int, Any] = {}
            traffics: dict[int, Traffic | None] = {}
            lap_passes: set[tuple[int, int]] = set()
            lap_incidents: list[Incident] = []
            for entry in self._running_order(elapsed):
                simulator = self._simulators[entry.car_number]
                traffic = self._traffic_for(
                    entry, lap, elapsed[entry.car_number], lap_passes
                )
                traffics[entry.car_number] = traffic
                launch = self.launches.get(entry.car_number) if lap == 1 else None
                drives[entry.car_number] = simulator.simulate(
                    lap=lap,
                    fuel_mass=entry.fuel_mass,
                    tyre_state=entry.tyres,
                    ers_state=entry.energy,
                    qualifying=qualifying,
                    record_telemetry=self.telemetry > 0,
                    telemetry_stride=max(1, self.telemetry),
                    traffic=traffic,
                    stride=self._interaction_stride(),
                    run=traffic is None,
                    on_step=self._recorder(entry.car_number, elapsed[entry.car_number], lap),
                    start_speed=launch.exit_speed if launch is not None else None,
                )

            # Step everybody forward together.  Whoever is furthest behind on
            # the clock goes next, so a car is never simulated past a moment
            # that the cars in front of it have not reached yet -- which is
            # what makes an overtake something the loser finds out about.
            if any(not isinstance(d, LapResult) for d in drives.values()):
                self._step_together(drives, elapsed)

            for entry in running:
                drive = drives[entry.car_number]
                result = drive if isinstance(drive, LapResult) else drive.result
                traffic = traffics[entry.car_number]
                entry.fuel_mass = max(entry.fuel_mass - result.fuel_used, 0.0)
                lap_time = result.lap_time
                if traffic is not None:
                    for move in traffic.passes:
                        self.overtakes.append(move)
                        # Who is in front of whom is a fact about the race, so
                        # it outlives the lap it happened on.
                        self._ahead_of[move.attacker].add(move.defender)
                        self._ahead_of[move.defender].discard(move.attacker)

                stop = self._pit_stop(entry, result, lap)
                if stop is not None:
                    lap_time += stop.loss

                # What went wrong is drawn before the lap is written down, so a
                # spin costs the lap it happened on rather than the next one.
                incident = (
                    self._sample_incident(entry, lap, result) if self.hazards else None
                )
                if incident is not None:
                    lap_incidents.append(incident)
                    lap_time += incident.time_lost

                lap_times.append(lap_time)
                elapsed[entry.car_number] += lap_time
                # What a green lap of this race costs this car, kept so that a
                # neutralised lap has something real to be scaled from.
                previous_wear = self._green_reference.get(
                    entry.car_number, (0.0, 0.0, 0.0, 0.0)
                )[3]
                self._green_reference[entry.car_number] = (
                    result.lap_time,
                    result.fuel_used,
                    max(entry.tyres.wear - previous_wear, 0.0),
                    entry.tyres.wear,
                )

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
            # A driver who was overtaken this lap regroups before trying again.
            for car in self._just_passed:
                self._just_passed[car] = {
                    move.attacker for move in self.overtakes
                    if move.lap == lap and move.defender == car
                }
            self._close_lap(lap, running, elapsed, incidents=lap_incidents)

        return self._classify()

    # -- neutralised running --------------------------------------------------

    def _neutralised_lap(
        self,
        running: Sequence[RaceEntry],
        lap: int,
        neutralisation: Neutralisation,
        elapsed: dict[int, float],
    ) -> list[float]:
        """Run one lap to a delta rather than racing it.

        A safety car lap is not a slow racing lap, it is a different activity,
        and scaling a racing lap would get the consumables wrong in both
        directions.  What actually happens is that the car does far less work:
        drag and tyre forces both fall with the square of speed, so a lap run
        at ``1/f`` of racing pace does about ``1/f^2`` of the work.  That is
        where the fuel saving comes from, why the tyres cool rather than merely
        wearing more slowly, and why a long neutralisation leaves everybody
        with a full battery and cold tyres to restart on.
        """
        factor = neutralisation.pace_factor
        work_share = 1.0 / (factor * factor)
        lap_times: list[float] = []
        for entry in running:
            reference, fuel_reference, wear_reference, _ = self._green_reference.get(
                entry.car_number, (0.0, 0.0, 0.0, 0.0)
            )
            if reference <= 0.0:
                reference = self.track.length / 60.0
            lap_time = reference * factor

            entry.fuel_mass = max(entry.fuel_mass - fuel_reference * work_share, 0.0)
            entry.tyres.wear = min(1.0, entry.tyres.wear + wear_reference * work_share)
            # The tread cools because the heat going into it has collapsed --
            # the real thermal model doing it, not a rule.  Not to nothing,
            # though: a driver behind the safety car weaves and brakes to keep
            # temperature in the tyres, and that work is why a restart is a
            # race rather than a queue of cars on cold rubber.
            keep_warm = (
                entry.vehicle.mass.total_mass(entry.fuel_mass)
                * self.config.physics.gravity
                * self.config.race_control.tyre_work_share
            )
            entry.tyres.update(
                friction_force=keep_warm,
                speed=self.track.length / lap_time,
                distance=self.track.length,
                dt=lap_time,
                air_temperature=self.ambient.air_temperature,
                track_temperature=self.ambient.track_temperature,
                thermal_config=self.config.tyre_thermal,
                wear_config=self.config.tyre_wear,
            )
            entry.energy.energy_remaining = min(
                entry.vehicle.spec.ers.capacity,
                entry.energy.energy_remaining
                + entry.vehicle.spec.ers.max_harvest_power * lap_time * 0.25,
            )

            stop = self._pit_stop(entry, None, lap, saving=neutralisation.pit_saving)
            if stop is not None:
                lap_time += stop.loss

            elapsed[entry.car_number] += lap_time
            lap_times.append(lap_time)
            self.timing.record(
                LapRecord(
                    car_number=entry.car_number,
                    lap=lap,
                    lap_time=lap_time,
                    elapsed=elapsed[entry.car_number],
                    distance=lap * self.track.length,
                    sector_times=tuple(
                        lap_time * length / self.track.length
                        for length in self._sector_lengths
                    ),
                    compound=entry.compound,
                    tyre_wear=entry.tyres.wear,
                    fuel_mass=entry.fuel_mass,
                    energy_remaining=entry.energy.energy_remaining,
                    mistakes=0,
                    pitted=stop is not None,
                ),
                sector_lengths=self._sector_lengths,
            )
        return lap_times

    # -- what went wrong, and what race control did about it -------------------

    def _close_lap(
        self,
        lap: int,
        running: Sequence[RaceEntry],
        elapsed: dict[int, float],
        *,
        incidents: Sequence[Incident] = (),
    ) -> None:
        """Apply what went wrong on this lap and let race control respond."""
        by_number = {entry.car_number: entry for entry in self.entries}
        for incident in incidents:
            self.incidents.append(incident)
            if incident.retires:
                by_number[incident.car_number].retirement = incident
            elif incident.damage > 0.0:
                self._damage(incident)
            if self.events is not None:
                self.events.emit(
                    IncidentRaised(
                        time=elapsed.get(incident.car_number, 0.0), incident=incident
                    )
                )

        was = self.race_control.flag
        decision = self.race_control.assess(lap, incidents)
        now = self.race_control.flag
        if now is not was:
            if self.events is not None:
                self.events.emit(
                    FlagChanged(
                        time=max(elapsed.values(), default=0.0),
                        previous=was, current=now, lap=lap, reason=decision.reason,
                    )
                )
            if self.race_control.neutralisation().bunches:
                order = sorted(
                    (e.car_number for e in self.entries if e.running),
                    key=lambda car: elapsed[car],
                )
                elapsed.update(self.race_control.bunch(elapsed, order))

    def _sample_incident(
        self, entry: RaceEntry, lap: int, result: LapResult | None
    ) -> Incident | None:
        """Draw whether anything went wrong for one car on one lap.

        One stream per car per lap, addressed by name, so adding a car to the
        grid cannot change what happens to any other car (rule 36).
        """
        stream = self.rng.stream("hazard", car=entry.car_number, lap=lap)
        distance = self.track.length
        cfg = self.config.reliability

        if result is not None:
            stress = stress_from_lap(
                fuel_used=result.fuel_used,
                energy_harvested=result.energy_harvested,
                distance=distance,
                commitment=(
                    result.commitment.cornering
                    + result.commitment.braking
                    + result.commitment.traction
                ) / 3.0,
                config=cfg,
            )
        else:
            # Running to a delta works nothing hard.
            kilometres = distance / 1000.0
            stress = stress_from_lap(
                fuel_used=0.4 * cfg.reference_fuel_per_km * kilometres,
                energy_harvested=0.3 * cfg.reference_harvest_per_km * kilometres,
                distance=distance,
                commitment=0.4,
                config=cfg,
            )

        failure = sample_failure(
            stream.derive("mechanical"),
            car_number=entry.car_number,
            lap=lap,
            distance=distance,
            stress=stress,
            air_temperature=self.ambient.air_temperature,
            config=cfg,
        )
        if failure is not None:
            return failure
        if result is None:
            return None

        attributes = entry.driver.attributes
        skill = 0.5 * (attributes.racecraft + attributes.risk_management)
        combat = float(getattr(result, "traffic_fraction", 0.0) or 0.0)
        self._combat_laps[entry.car_number] += combat
        contact = sample_contact(
            stream.derive("contact"),
            ContactRisk(
                laps_in_combat=max(combat, 1.0) if lap == 1 else combat,
                first_lap=lap == 1,
                attacker_skill=skill,
                rival_skill=skill,
                track_width=min(
                    (segment.track_width for segment in self.track.segments),
                    default=13.0,
                ),
            ),
            car_number=entry.car_number,
            lap=lap,
            config=self.config.incidents,
        )
        if contact is not None:
            return contact

        return sample_spin(
            stream.derive("spin"),
            car_number=entry.car_number,
            lap=lap,
            mistakes=len(result.mistakes),
            risk_management=attributes.risk_management,
            config=self.config.incidents,
        )

    def _damage(self, incident: Incident) -> None:
        """Give a car the aerodynamics it has left.

        Damage is not a lap-time penalty.  The car is given the aerodynamics it
        has left and the rest of the engine works out what that is worth, which
        is why the same broken wing costs different amounts at different
        circuits: the downforce it is no longer making is missed most where the
        corners are fast, and the drag it is still making is felt most where the
        straights are long.
        """
        from dataclasses import replace as _replace

        by_number = {e.car_number: e for e in self.entries}
        entry = by_number[incident.car_number]
        entry.damage = min(1.0, entry.damage + incident.damage)
        cfg = self.config.incidents
        aero = entry.vehicle.spec.aero

        # A broken wing is not a trimmed wing.  Trimming a wing out takes away
        # downforce *and* the induced drag that came with it, which is why a
        # Monza package is quick in a straight line; if damage were modelled
        # that way a car would leave the barrier faster than it arrived.  What
        # a damaged wing actually is is a bluff body with the flow separated
        # behind it: the downforce is gone and the drag is not.  So the drag
        # is pinned to what the intact car had, plus a penalty, and the
        # zero-lift term absorbs whatever the smaller wing no longer induces.
        kept = 1.0 - cfg.damage_downforce_loss * entry.damage
        wing = entry.vehicle.wing_level
        intact_lift = aero.downforce_area(wing)
        intact_drag = aero.drag_area(wing)
        target_drag = intact_drag * (1.0 + cfg.damage_drag_penalty * entry.damage)
        induced = aero.induced_drag_factor * (intact_lift * kept) ** 2
        zero_lift = max(target_drag - induced, aero.zero_lift_drag_area)

        spec = _replace(
            entry.vehicle.spec,
            aero=_replace(
                aero,
                min_downforce_area=aero.min_downforce_area * kept,
                max_downforce_area=aero.max_downforce_area * kept,
                zero_lift_drag_area=zero_lift,
            ),
        )
        damaged = entry.vehicle.with_spec(spec)
        self._simulators[entry.car_number] = LapSimulator(
            self.track, damaged, entry.driver,
            rng=self.rng.spawn(f"car.{entry.car_number}.damaged.{incident.lap}"),
            ambient=self.ambient, conditions=self.conditions, config=self.config,
        )

    # -- racing each other ---------------------------------------------------

    def _running_order(self, elapsed: dict[int, float]) -> list[RaceEntry]:
        """The order to simulate this lap in: whoever is out there first.

        Ordering by elapsed time is what makes the model causal.  Anybody
        physically in front of a car when it is out there started their lap
        before it did -- including a car a lap up the road -- so their trace
        already exists to be raced against, and nobody has to guess where
        anybody is.
        """
        return sorted(
            (entry for entry in self.entries if entry.running),
            key=lambda e: (elapsed[e.car_number], e.car_number),
        )

    def _recorder(self, car: int, started: Seconds, lap: int):
        """A callback that puts this car's progress on the timing tower as it
        happens, so everybody racing it can see where it is now."""
        base = (lap - 1) * self.track.length
        timing = self.timing

        def record(at: Seconds, covered: float) -> None:
            timing.record_trace(car, (started + at,), (base + covered,))

        return record

    def _interaction_stride(self) -> int:
        """How many segments a car drives between re-synchronisations.

        The config asks for a number of stops per lap, which is the thing with
        a meaning -- so many seconds of racing before everybody is lined up on
        the clock again.  How many segments that is depends on the circuit.
        """
        steps = self.config.overtaking.interaction_steps
        return max(1, len(self.track.segments) // steps)

    def _step_together(self, drives: dict[int, Any], elapsed: dict[int, float]) -> None:
        """Advance every car in progress, always the one furthest behind.

        Nobody is ever simulated past a moment the cars in front of them have
        not reached, so the answer to "who is in front" is never a guess -- and
        a car that gets overtaken finds out about it on the lap it happened,
        rather than driving the rest of it as though nothing had.
        """
        pending = {
            car: drive for car, drive in drives.items()
            if not isinstance(drive, LapResult)
        }
        while pending:
            car = min(pending, key=lambda c: elapsed[c] + pending[c].elapsed)
            if not pending[car].advance():
                del pending[car]

    def _traffic_for(
        self,
        entry: RaceEntry,
        lap: int,
        started: Seconds,
        lap_passes: set[tuple[int, int]],
    ) -> Traffic | None:
        """This car's view of everybody in front of it, for one lap."""
        if not self.racing or len(self.entries) < 2:
            return None
        return Traffic(
            track=self.track,
            timing=self.timing,
            car_number=entry.car_number,
            lap=lap,
            attributes=entry.driver.attributes,
            start_time=started,
            others={
                other.car_number: other.driver.attributes
                for other in self.entries
                if other.car_number != entry.car_number
            },
            ahead_of=set(self._ahead_of[entry.car_number]),
            just_passed_by=set(self._just_passed[entry.car_number]),
            lap_passes=lap_passes,
            config=self.config.overtaking,
            wake_config=self.config.wake,
        )

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
        self,
        entry: RaceEntry,
        result: LapResult | None,
        lap: int,
        *,
        saving: float = 0.0,
    ) -> PitStop | None:
        """Ask this car's strategist whether to come in, and charge it if so.

        ``saving`` is the share of the stop's cost that disappears because the
        race is neutralised.  It is the reason a safety car reshuffles a race:
        the road the pit lane replaces is being covered slowly, so replacing it
        costs much less -- and a strategist who is already close to a stop will
        take one the moment the flag comes out.
        """
        strategy = entry.strategy
        if strategy is None:
            return None
        strategy.lap_completed()
        if not strategy.compounds:
            strategy.compounds = entry.compounds
        if not strategy.compounds:
            return None

        water = self._mean_water_depth()
        reference = self._reference_profile(entry, result)
        wanted = strategy.decide(
            lap=lap,
            laps_remaining=self.laps - lap,
            tyres=entry.tyres,
            water_depth=water,
            speed=(
                result.average_speed
                if result is not None
                else self.track.length / max(self._green_reference.get(
                    entry.car_number, (60.0, 0.0, 0.0, 0.0))[0], 1.0)
            ),
        )
        if wanted is None or reference is None:
            return None

        loss = pit_loss(
            entry.vehicle,
            self.pit_lane,
            reference,
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
            loss=loss.total * (1.0 - min(max(saving, 0.0), 1.0)),
            reason=reason if saving <= 0.0 else f"{reason} (neutralised)",
        )
        entry.pit_stops.append(stop)
        entry.fit(wanted)
        strategy.record_stop(wanted)
        return stop

    def _reference_profile(self, entry: RaceEntry, result: LapResult | None):
        """A speed profile to price a pit stop against.

        A stop taken under a neutralisation has no lap of its own to compare
        with, so the car's last green-flag profile is used: what the stop costs
        is measured against the road it replaces, and that road is the racing
        one whether or not the race is currently green.
        """
        if result is not None:
            self._green_profiles[entry.car_number] = result.profile
            return result.profile
        return self._green_profiles.get(entry.car_number)

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
        still_running = {
            entry.car_number for entry in self.entries if entry.running
        }
        finish = min(
            (
                records[-1].elapsed
                for car in self.timing.cars
                if car in still_running and (records := self.timing.records(car))
            ),
            default=min(
                records[-1].elapsed
                for car in self.timing.cars
                if (records := self.timing.records(car))
            ),
        )
        flags = {car: _flag_lap(self.timing.records(car), finish)
                 for car in self.timing.cars}
        by_number = {entry.car_number: entry for entry in self.entries}
        # A retired car is classified on the laps it completed, behind everyone
        # who was still running at the flag.  That is what a result sheet does,
        # and it is the only honest place to put a car that stopped: it did not
        # beat anybody who was still going.
        order = sorted(
            flags,
            key=lambda car: (
                by_number[car].running is False,
                -flags[car].lap,
                flags[car].elapsed,
                car,
            ),
        )
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
                    overtakes=sum(
                        1 for move in self.overtakes
                        if move.attacker == car and move.lap <= flag.lap
                    ),
                    retired=not entry.running,
                    retirement_reason=(
                        entry.retirement.description if entry.retirement else ""
                    ),
                )
            )

        return RaceResult(
            track_name=self.track.name,
            laps=self.laps,
            classification=tuple(classification),
            timing=self.timing,
            entries=self.entries,
            fastest_lap=fastest,
            overtakes=tuple(self.overtakes),
            incidents=tuple(self.incidents),
            flags=tuple(
                (lap, flag.value, reason)
                for lap, flag, reason in self.race_control.log
            ),
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
