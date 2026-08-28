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
from .timing import TimingTower
from .wake import CLEAN_AIR, WakeEffect, wake_effect

__all__ = ["OvertakeAttempt", "Traffic"]


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
        return TrafficState(
            wake=self._wake(gap, self._is_passable(here.curvature, speed)),
            drs_allowed=self._drs_allowed(distance, elapsed, car),
            speed_limit=ahead_speed if gap <= cfg.minimum_gap else float("inf"),
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

        nearest = self._nearest_ahead(distance, elapsed, speed)
        if nearest is None:
            self._target = None
            return TrafficState(
                wake=CLEAN_AIR, off_line=overtook is not None, passed=overtook
            )

        car, road_gap, ahead_speed = nearest
        gap = road_gap / max(speed, 1.0)
        cfg = self.config
        drs = self._drs_allowed(distance, elapsed, car)

        here = self.track.state_at(distance)
        passable = self._is_passable(here.curvature, speed)
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
        closing = max(speed - ahead_speed, 0.0) * step / max(speed, 1.0)
        floor = (
            0.0 if move_on
            else (cfg.car_length if passable else cfg.minimum_gap * max(speed, 1.0))
        )
        limit = (
            float("inf") if floor <= 0.0
            else (ahead_speed if road_gap - closing <= floor else float("inf"))
        )
        return TrafficState(
            wake=wake,
            drs_allowed=drs,
            speed_limit=limit,
            off_line=move_on and road_gap <= cfg.car_length * cfg.commitment_gap,
            passed=overtook,
        )

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

    def _is_passable(self, curvature: float, speed: MetresPerSecond) -> bool:
        """Whether a move can be completed here.

        Where the road is straight and the car is quick -- which is the end of
        a straight and the braking zone at the end of it, because that is where
        a car carrying more speed ends up alongside.
        """
        if speed < self.config.passing_speed:
            return False
        radius = math.inf if curvature == 0.0 else abs(1.0 / curvature)
        return radius > self.config.passing_radius

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
