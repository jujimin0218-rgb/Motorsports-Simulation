"""Racing another car (project rule 29).

    "추월은 단순한 확률 판정이 아니라 상황에서 나와야 한다."

So there is no overtaking probability here.  There is a car in front, a road
gap that shrinks when one car is quicker than the other, and a place where the
road is wide enough to complete a move.  Everything else falls out:

* **you cannot drive through the car in front.**  A car that catches another
  and cannot get by is held to its pace, which is what makes traffic cost time.
* **following is hard.**  At the gap where a pass becomes possible the follower
  has lost a third of its downforce, so it is slower exactly where it needs to
  be quicker.  That is the sport's central problem and it is not written down
  anywhere -- it comes out of :mod:`f1_race_engine.race.wake`.
* **the tow is the answer to it.**  Less drag in the hole in the air means more
  speed on the straight, which is where the overlap gets built.
* **DRS is the answer to the answer.**  Within a second at the detection point,
  the flap opens in the zone and the tow becomes a real advantage.

A move is on where the road is wide and quick enough for two cars and where the
attacker arrives with the speed advantage the defender's racecraft demands.
What completes it is not a judgement but a fact: a car that was clearly behind
another one is now clearly ahead of it.  So a car half a second a lap quicker
spends laps in dirty air waiting for a big enough run, and a car two seconds a
lap quicker is past at the first place there is room -- which is what happens.

Committing to a move means leaving the racing line, and off the racing line are
the marbles Phase 10 put there.  So an attempt that does not come off costs
something, and nobody had to price it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Any

from ..core.config import OvertakingConfig, WakeConfig
from ..core.units import MetresPerSecond, Seconds
from ..driver.model import DriverAttributes
from ..simulation.traffic import CLEAR, TrafficState
from ..track.model import Track
from ..track.racing_line import CAR_WIDTH
from ..world.track import TrackWorld
from .racecraft import bias_of_offset, corner_scale, holds_the_line
from .timing import TimingTower
from .wake import CLEAN_AIR, WakeEffect, wake_effect

__all__ = ["OvertakeAttempt", "Traffic"]

#: Metres across the road a car can move per metre along it.
#:
#: A line change is a manoeuvre, not a teleport.  At this rate covering a car's
#: width takes about two hundred metres of road, which at racing speed is the
#: two or three seconds a real move alongside actually lasts -- and long enough
#: that a replay sampling every couple of seconds sees the fight rather than
#: only its result.
LINE_CHANGE_RATE = 0.01

#: How quickly a car that has lost the corner travels towards the outside of
#: it, as a fraction of the remaining distance per step.  Running wide is a car
#: understeering off over a second or two, not a car teleporting into the
#: gravel.
WIDE_RATE = 0.08

#: How far past the edge of the road a car that has run out of it is heading,
#: as a multiple of the road's own half-width.  Beyond one is off the circuit,
#: and what is out there -- kerb, tarmac, gravel -- is the world layer's to say.
BEYOND = 1.6

#: Car lengths behind at which a driver stops sitting directly behind.
#:
#: Not the same as being able to pass.  This close the car in front is taking
#: the air, so the one behind eases off the line to find some -- which is also
#: where it would have to be to have a look, so a fight starts here rather than
#: at the moment the move is on.
LOOKING_LENGTHS = 5.0

#: How much of a car width a driver takes while only looking.
LOOKING_FRACTION = 0.6

#: Extra metres an attacker aims for beyond simply being alongside.
#:
#: Aiming at exactly a car width leaves a move that never quite lands: the car
#: being passed is moving across too, so the two of them chase each other and
#: settle a handful of centimetres short of the room a pass needs.
CLAIM_MARGIN = 0.4

#: How far off the line, m, counts as being on the dirty part of the road.
#:
#: Beyond it the car is where the marbles are, which the surface model already
#: prices; inside it the car is still on the rubber.
OFF_LINE = 0.75


@dataclass(frozen=True, slots=True)
class OvertakeAttempt:
    """A move that came off."""

    lap: int
    distance: float
    attacker: int
    defender: int
    overlap: float
    """Metres of advantage the attacker had built when the move completed."""

    drs: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "lap": self.lap,
            "distance": self.distance,
            "attacker": self.attacker,
            "defender": self.defender,
            "overlap": self.overlap,
            "drs": self.drs,
        }


@dataclass
class Traffic:
    """One car's view of everybody in front of it, for the length of one lap.

    Built fresh each lap by the session, which is what knows where everybody
    is.  Stateful across the lap, because building an overlap is a thing that
    happens over a stretch of road rather than at a point.
    """

    track: Track
    timing: TimingTower
    car_number: int
    lap: int
    attributes: DriverAttributes
    start_time: Seconds = 0.0
    """Session time at which this car began the lap.

    The lap simulation counts from zero every lap; everybody else is somewhere
    on a race clock.  This is the only place the two are reconciled."""

    world: TrackWorld | None = None
    """The circuit as a place, which is where the lines are.

    Optional so that a race can still be run without one -- qualifying builds a
    :class:`Traffic` with nobody in it -- but with one the car's place across
    the road becomes a *line*, and the line has a radius that the physics
    charges it for."""

    others: dict[int, DriverAttributes] = field(default_factory=dict)
    config: OvertakingConfig | None = None
    wake_config: WakeConfig | None = None

    lap_passes: set[tuple[int, int]] | None = None
    """Passes made anywhere in the field on this lap, shared by every car.

    Two cars cannot swap places twice in one lap: whoever came off worse has to
    regroup first.  The set is shared because that is a fact about the lap
    rather than about either car's view of it."""

    just_passed_by: set[int] = field(default_factory=set)
    """Cars that got past this one on the previous lap.

    A driver who has just been overtaken does not get an instant switchback.
    They have to regroup, get back into the wake and set the move up again, and
    that takes a lap -- which is why real fights swap places over a stint
    rather than at every corner."""

    ahead_of: set[int] = field(default_factory=set)
    """Cars this one is already in front of, carried in from earlier laps.

    Without it a car that passes on the last corner of a lap, and so does not
    have time to build a lead before the line, meets the same car ahead again
    next lap and passes it all over again.  Who is in front of whom is a fact
    about the race, not about the lap."""

    _overlap: float = field(default=0.0, repr=False)
    _target: int | None = field(default=None, repr=False)
    _blocked: set[int] = field(default_factory=set, repr=False)
    _drs_gap: dict[int, float] = field(default_factory=dict, repr=False)
    _passed: set[int] = field(default_factory=set, repr=False)
    _was_behind: set[int] = field(default_factory=set, repr=False)
    _last_distance: float = field(default=0.0, repr=False)
    offset: float = field(default=0.0, repr=False)
    """Where this car is across the road, m from the line, left positive."""

    _planned: dict[int, float] = field(default_factory=dict, repr=False)
    """The cornering scale this car's lap was *planned* with, per sample.

    Filled in by :meth:`preview` while the lap is being worked out and read
    back by :meth:`at` while it is being driven.  The gap between the two is a
    driver committing to something after the plan was made, and it is the whole
    of how a car ends up off the road."""

    passes: list[OvertakeAttempt] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        if self.config is None:
            self.config = OvertakingConfig()
        if self.wake_config is None:
            self.wake_config = WakeConfig()
        self._passed = set(self.ahead_of)
        self._blocked = set(self.just_passed_by)
        if self.lap_passes is None:
            self.lap_passes = set()

    # -- the question the lap simulation asks --------------------------------

    def preview(  # noqa: D401 - see the protocol
        self, *, distance: float, elapsed: Seconds, speed: MetresPerSecond
    ) -> TrafficState:
        """The road ahead, without racing anybody for it.

        The lap simulation asks this before the lap, to work out what plan is
        available.  A driver following another car brakes earlier for the
        corner because they know the downforce will not be there, not because
        they discover it at the apex.

        It races nobody and completes no moves.  The one thing it does leave
        behind is the gap it read at each DRS detection point, which is the
        point: the detection point is passed before the zone, so whether the
        flap opens is settled by the time the car gets there, and the driven
        lap has to agree with the planned one about it.
        """
        elapsed += self.start_time
        nearest = self._nearest_ahead(distance, elapsed, speed)
        if nearest is None:
            return CLEAR

        car, road_gap, ahead_speed = nearest
        gap = road_gap / max(speed, 1.0)
        cfg = self.config
        here = self.track.state_at(distance)

        # A driver lining somebody up plans to be off the racing line by the
        # time they get there, and plans the corner for the line they will be
        # on.  Recording it is what lets the driven lap tell a move that was
        # set up from one that was decided at the braking point -- the second
        # is the one that puts a car in the run-off.
        planned_bias = 0.0
        if road_gap <= cfg.car_length * LOOKING_LENGTHS:
            planned_bias = LOOKING_FRACTION
        scale = self._line_scale(distance, planned_bias)
        self._planned[self._sample(distance)] = scale

        return TrafficState(
            wake=self._wake(
                gap, self._is_passable(here.curvature, speed, here.usable_half_width)
            ),
            drs_allowed=self._drs_allowed(distance, elapsed, car),
            speed_limit=ahead_speed if gap <= cfg.minimum_gap else float("inf"),
            bias=planned_bias,
            corner_scale=scale,
        )

    def at(
        self, *, distance: float, elapsed: Seconds, speed: MetresPerSecond
    ) -> TrafficState:
        """The state of the road for this car, here and now."""
        step = max(distance - self._last_distance, 0.0)
        self._last_distance = distance
        elapsed += self.start_time

        # An overtake is not a separate event that has to be detected: it is
        # simply the moment a car that was in front stops being in front.  So
        # that is what is looked for, and every position change goes through
        # here whether it took a lunge down the inside or ten laps of pressure.
        overtook = self._check_passed(distance, elapsed)

        here = self.track.state_at(distance)
        room = here.usable_half_width

        nearest = self._nearest_ahead(distance, elapsed, speed)
        if nearest is None:
            self._target = None
            # Nobody to race: back to the line, at the rate a car changes line.
            self.offset = self._hold_line(0.0, room, step)
            bias, scale, wide, _, self.offset = self._line_state(
                distance, self.offset
            )
            return TrafficState(
                wake=CLEAN_AIR,
                off_line=abs(self.offset) > OFF_LINE,
                offset=self.offset,
                passed=overtook,
                bias=bias,
                corner_scale=scale,
                ran_wide=wide,
            )

        car, road_gap, ahead_speed = nearest
        gap = road_gap / max(speed, 1.0)
        cfg = self.config
        drs = self._drs_allowed(distance, elapsed, car)

        passable = self._is_passable(here.curvature, speed, room)
        wake = self._wake(gap, passable)
        required = self._required_overlap(car)

        self._target = car
        self._overlap = road_gap

        # The car in front cannot be driven through, and how close the follower
        # may get depends on where it is and on who it is racing.  A move is on
        # where the road is wide and quick *and* the attacker has the speed
        # advantage the defender's racecraft demands; short of that, the gap
        # stops at a car length and the two of them run like that.
        move_on = (
            passable
            and speed - ahead_speed >= required
            and car not in self._blocked
            and (car, self.car_number) not in self.lap_passes
        )

        # Where to put the car.  A driver who has caught somebody does not wait
        # until the move is on to leave the line: they sit out of the worst of
        # the dirty air and show a wheel, and then take the rest of the road
        # when the move is actually there.  So there are two distances here --
        # lining up, and committed.
        theirs = self.timing.offset_at(car, elapsed)
        committed = move_on and road_gap <= cfg.car_length * cfg.commitment_gap
        lining_up = road_gap <= cfg.car_length * LOOKING_LENGTHS
        target = 0.0
        if committed or lining_up:
            wanted = (
                CAR_WIDTH + CLAIM_MARGIN if committed else CAR_WIDTH * LOOKING_FRACTION
            )
            # Take the side of the road there is more of.
            side = 1.0 if theirs <= 0.0 else -1.0
            target = theirs + side * wanted
            if abs(target) > room:
                target = theirs - side * wanted
                if abs(target) > room:
                    target = self.offset
                    committed = False
        self.offset = self._hold_line(target, room, step)

        # The car in front cannot be driven through, and it cannot be driven
        # *over* either: getting past means getting alongside first, which
        # takes road and time.  Until the two of them are a car's width apart
        # the follower is held at a car length, which is what makes a fight
        # something that happens over a stretch of track rather than a swap
        # that resolves the instant the maths says it can.
        alongside = abs(self.offset - theirs) >= CAR_WIDTH
        closing = max(speed - ahead_speed, 0.0) * step / max(speed, 1.0)
        floor = (
            0.0 if move_on and alongside
            else (cfg.car_length if passable else cfg.minimum_gap * max(speed, 1.0))
        )
        limit = (
            float("inf") if floor <= 0.0
            else (ahead_speed if road_gap - closing <= floor else float("inf"))
        )

        bias, scale, wide, _, self.offset = self._line_state(distance, self.offset)
        return TrafficState(
            wake=wake,
            drs_allowed=drs,
            speed_limit=limit,
            off_line=abs(self.offset) > OFF_LINE or wide,
            offset=self.offset,
            passed=overtook,
            bias=bias,
            corner_scale=scale,
            ran_wide=wide,
        )

    # -- which line, and what it costs ---------------------------------------

    def _sample(self, distance: float) -> int:
        """Which world sample a lap distance falls on."""
        if self.world is None:
            return 0
        return self.world.sample_of(distance)

    def _line_scale(self, distance: float, bias: float) -> float:
        """What driving line ``bias`` here does to cornering speed.

        One over the square root of how much tighter the path is than the
        racing line.  Everything a driver gains or loses by their choice of
        line goes through this number and nothing else does.
        """
        if self.world is None or self.world.lines is None:
            return 1.0
        index = self.world.sample_of(distance)
        road = self.world.lines.optimal.curvature[index]
        line = self.world.curvature_of_line(distance, bias)
        return corner_scale(road, line)

    def _line_state(
        self, distance: float, offset: float
    ) -> tuple[float, float, bool, str, float]:
        """The line this car is on, its price, whether it holds it, and where
        that leaves it.

        Called once per step of the driven lap.  The car's place across the
        road has already been decided by the racing logic above; this says what
        the choice was in the language the physics understands, and moves the
        car if the choice was beyond it.
        """
        if self.world is None or self.world.lines is None:
            return 0.0, 1.0, False, "line", offset

        index = self.world.sample_of(distance)
        # The race carries a car's place as metres from the *racing line*,
        # because that is what a driver moves off and back onto.  The world
        # measures from the middle of the road.  Adding the line's own offset
        # is the whole of the conversion, and leaving it out reads a car
        # sitting perfectly on the line as one halfway to the grass.
        across = self.world.lines.optimal.offsets[index] + offset
        bias = bias_of_offset(self.world.lines, index, across)
        scale = self._line_scale(distance, bias)

        # The lap was planned for a line.  If the car is now on a tighter one,
        # the speed it is carrying was worked out for a bigger radius, and the
        # difference has to come out of the grip the driver kept back.
        planned = self._planned.get(index, 1.0)
        wide = not holds_the_line(planned, scale, self.attributes.racecraft)

        if wide:
            intent = "wide"
        elif bias > 0.15:
            intent = "attack" if self._target is not None else "defend"
        elif bias < -0.15:
            intent = "around"
        else:
            intent = "line"

        if wide:
            # The car goes where its speed was taking it, which is off the
            # outside of the corner -- and it keeps going that way until it is
            # on a radius it can actually hold, which for a car that has run
            # out of road means the run-off.  Nothing decides how far it goes:
            # the drift stops when the geometry stops asking for grip the car
            # has not got, which is why a small over-commitment is a wide exit
            # and a large one is a trip through the gravel.
            optimal = self.world.lines.optimal.offsets[index]
            outside = self.world.lines.outside_edge[index] - optimal
            offset += (outside * BEYOND - offset) * WIDE_RATE

        return bias, scale, wide, intent, offset

    def _covered(self, distance: float) -> float:
        """How far this car has come since the start, m."""
        return (self.lap - 1) * self.track.length + distance

    def _check_passed(self, distance: float, elapsed: Seconds) -> int | None:
        """Whoever this car has just got clear of, if anybody.

        An overtake is not an event to be detected but the moment a car that
        was in front stops being in front, so this asks the only question there
        is: who was clearly ahead of me and is now clearly behind?  Asking it of
        positions rather than of whoever happens to be under the nose right now
        matters, because the moment a move completes is exactly the moment the
        car being passed stops being the car in front -- so anything that hangs
        on still chasing them loses the pass it just made.
        """
        cfg = self.config
        mine = self._covered(distance)
        done: int | None = None
        for car in self.timing.cars:
            if car == self.car_number:
                continue
            # Only where the other car's progress is actually on record.  Cars
            # are stepped a stretch at a time, so a car in the middle of its
            # stretch has run past everybody else's clock, and where they are
            # from there is a guess extended at the speed they were last doing.
            # Good enough for the air; not good enough to decide a position on,
            # because a car accelerating out of a corner is well ahead of its
            # own extrapolation and would be recorded as having been passed.
            if elapsed > self.timing.recorded_until(car):
                continue
            lead = mine - self.timing.distance_at(car, elapsed)
            # An overtake is going from clearly behind to clearly ahead, and
            # both halves have to happen.  Two cars running nose to tail are
            # separated by less than their own length and trade the odd inch
            # back and forth all lap; without the first half every one of those
            # inches is an overtake, and the same car "passes" the same car at
            # the same corner on every lap while never being behind it.
            if lead <= -cfg.car_length:
                self._was_behind.add(car)
                continue
            if done is not None or lead < cfg.car_length:
                continue
            if car not in self._was_behind:
                continue
            # One position change per pair per lap, in either direction, and
            # none at all against somebody who has just been past: a driver who
            # has lost a place has to regroup before taking it back.
            if car in self._blocked:
                continue
            if (car, self.car_number) in self.lap_passes:
                continue
            if (self.car_number, car) in self.lap_passes:
                continue
            self.passes.append(
                OvertakeAttempt(
                    lap=self.lap, distance=distance, attacker=self.car_number,
                    defender=car, overlap=lead,
                    drs=self._drs_gap.get(0, float("inf")) <= cfg.drs_detection_gap,
                )
            )
            self.lap_passes.add((self.car_number, car))
            self._passed.add(car)
            self._was_behind.discard(car)
            if self._target == car:
                self._target = None
            done = car
        return done

    def _wake(self, gap: Seconds, lined_up: bool) -> WakeEffect:
        """The air at this gap, here.

        Two cars are nose to tail down a straight and side by side through a
        corner, so the hole in the air is only worth anything in one of those
        places.  The turbulence is not so fussy: it fills the corner too, which
        is exactly why following is hard and slipstreaming is not enough.
        """
        effect = wake_effect(gap, self.wake_config)
        if lined_up or not self.wake_config.tow_needs_a_straight:
            return effect
        return replace(effect, drag_factor=1.0)

    # -- who is in front -----------------------------------------------------

    def _nearest_ahead(
        self, distance: float, elapsed: Seconds, speed: MetresPerSecond
    ) -> tuple[int, float, float] | None:
        """The closest car ahead on the road: its number, the gap, its speed.

        On the *road*, not in the classification, so a leader closing on a car
        a lap down finds it exactly the way it would find a rival.
        """
        length = self.track.length
        mine = distance % length
        # The wake's range is a time gap, so how far up the road it reaches
        # depends on how fast this car is going: three seconds is 250 m down a
        # straight and 70 m through a hairpin.
        reach = self.wake_config.range * max(speed, 1.0)
        ours = self._covered(distance)
        best: tuple[int, float, float] | None = None
        for car in self.timing.cars:
            if car == self.car_number:
                continue
            covered = self.timing.distance_at(car, elapsed, extrapolate=True)
            if covered <= 0.0:
                continue
            # Somebody already got past stays got past -- but only for as long
            # as they are actually still behind.  Having overtaken a car once
            # is not a reason to stop seeing it, and a car that comes back at
            # you is traffic again, which is the difference between a pass
            # holding and a pass being remembered as though it did.
            if car in self._passed and covered <= ours:
                continue
            theirs = covered % length
            gap = (theirs - mine) % length
            if gap <= 0.0 or gap > reach:
                continue
            if best is None or gap < best[1]:
                best = (car, gap, self.timing.speed_at(car, elapsed))
        return best

    # -- DRS -----------------------------------------------------------------

    def _drs_allowed(self, distance: float, elapsed: Seconds, car: int) -> bool:
        """Whether this car may open the flap here.

        The gap is measured at the detection point, which is not the same place
        as the zone -- being within a second at one and not the other is a real
        thing that happens, and it needs the two to be different places.
        """
        state = self.track.state_at(distance)
        if state.drs_zone is None:
            return False
        zone = state.drs_zone
        remembered = self._drs_gap.get(zone)
        if remembered is None:
            remembered = self._gap_at_detection(distance, elapsed, zone)
            self._drs_gap[zone] = remembered
        return remembered <= self.config.drs_detection_gap

    def _gap_at_detection(self, distance: float, elapsed: Seconds, zone: int) -> float:
        """The gap this car had at the detection point for ``zone``, s."""
        length = self.track.length
        detection = (distance - self.config.drs_detection_offset) % length
        speed = max(self.timing.speed_at(self.car_number, elapsed), 1.0)
        when = elapsed - self.config.drs_detection_offset / speed
        mine = detection
        best = float("inf")
        for car in self.timing.cars:
            if car == self.car_number:
                continue
            covered = self.timing.distance_at(car, when, extrapolate=True)
            if covered <= 0.0:
                continue
            gap = ((covered % length) - mine) % length
            if 0.0 < gap < best * speed:
                best = gap / speed
        return best

    # -- the move ------------------------------------------------------------

    def _required_overlap(self, defender: int) -> float:
        """How much quicker the attacker has to be, in m/s, to get the move done.

        Nothing, against a driver who leaves the door open.  A defender takes
        the line the attacker wants, so against a better racer being marginally
        faster is not enough -- and against a worse one, being alongside is.
        """
        theirs = self.others.get(defender)
        if theirs is None:
            return 0.0
        edge = theirs.racecraft - self.attributes.racecraft
        return max(self.config.defence_margin * edge, 0.0)

    def _is_passable(
        self, curvature: float, speed: MetresPerSecond, room: float
    ) -> bool:
        """Whether a move can be completed here.

        Where the road is straight and the car is quick -- which is the end of
        a straight and the braking zone at the end of it, because that is where
        a car carrying more speed ends up alongside -- *and* where the road is
        wide enough to hold two cars at once.  A driver alongside on a road
        with room for one is not overtaking, it is crashing.
        """
        if speed < self.config.passing_speed:
            return False
        if room < CAR_WIDTH:
            return False
        radius = math.inf if curvature == 0.0 else abs(1.0 / curvature)
        return radius > self.config.passing_radius

    def _hold_line(self, target: float, room: float, step: float) -> float:
        """Move this car across the road towards ``target``, as far as it can.

        A car changes line at a speed, not instantly: the rate is metres across
        per metre along, which is what keeps a dive to the inside a manoeuvre
        rather than a teleport.
        """
        target = max(-room, min(room, target))
        allowed = LINE_CHANGE_RATE * max(step, 0.0)
        delta = target - self.offset
        if abs(delta) <= allowed:
            return target
        return self.offset + math.copysign(allowed, delta)

    # -- reporting -----------------------------------------------------------

    @property
    def overlap(self) -> float:
        return self._overlap

    def to_dict(self) -> dict[str, Any]:
        return {
            "car_number": self.car_number,
            "lap": self.lap,
            "passes": [attempt.to_dict() for attempt in self.passes],
        }
