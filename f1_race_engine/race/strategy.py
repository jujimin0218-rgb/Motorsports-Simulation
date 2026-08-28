"""Strategy (project rule 31).

    "타이어 전략은 하드코딩된 규칙이 아니라 계산 결과여야 한다."

Nothing here says a soft tyre is for a short stint or that an intermediate is
for a damp track.  What it does instead is ask the rest of the engine two
questions and act on the answers:

* **what does this compound actually do over a stint?**  Simulated, not fitted:
  a set is bolted on and driven until it is finished, and the lap times that
  come back are the degradation curve.  Everything about a compound's character
  is already in there, including the parts nobody thought to model.
* **what does a stop actually cost here?**  Answered by
  :mod:`~f1_race_engine.race.pitlane`, which prices it as the difference
  between two journeys between the same two points.

A plan is then arithmetic over those two: total race time for each way of
splitting the distance, and the smallest one wins.  Which compound to start on,
how many stops to make and when to make them all fall out, and they come out
different at different circuits because the inputs are different -- never
because the circuit is named.

Rain changes the question rather than the answer.  A wet track makes the tyre
choice a grip calculation instead of a durability one, so the strategist asks
the wet model which tread can cope with the water that is actually down, and
swaps when the answer changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from ..core.errors import EntryError
from ..core.units import Seconds, format_lap_time
from ..tyres.compound import TyreCompound
from ..tyres.state import TyreState
from ..tyres.wet import wet_grip_factor

__all__ = [
    "Stint",
    "StrategyPlan",
    "RaceStrategy",
    "compound_for_conditions",
    "degradation_curve",
    "plan_strategy",
]


# ---------------------------------------------------------------------------
# Which tyre suits the track as it is right now
# ---------------------------------------------------------------------------


def compound_for_conditions(
    compounds: Sequence[TyreCompound],
    water_depth: float,
    *,
    speed: float = 55.0,
) -> TyreCompound:
    """The compound with the most grip on a track in this condition.

    Scored, not matched: each compound's peak friction is multiplied by what
    the wet model says it can actually deliver with this much water under it at
    a representative speed.  On a dry track that picks the softest slick; as the
    water deepens the slicks score zero long before the intermediate does, and
    the intermediate before the full wet.  No compound is labelled as being for
    anything.
    """
    if not compounds:
        raise EntryError("no compounds to choose from")
    return max(
        compounds,
        key=lambda compound: compound.peak_friction
        * wet_grip_factor(compound, water_depth, speed),
    )


# ---------------------------------------------------------------------------
# What a compound does over a stint
# ---------------------------------------------------------------------------


def degradation_curve(
    simulate_lap: Callable[[int, TyreState], Seconds],
    compound: TyreCompound,
    laps: int,
    *,
    temperature: float | None = None,
) -> tuple[Seconds, ...]:
    """Lap times a fresh set of ``compound`` gives over ``laps`` laps.

    ``simulate_lap`` is called with the lap number and the live tyre state and
    must return that lap's time, having driven it -- so the curve is whatever
    the physics does, warm-up and cliff included, rather than a fitted
    exponential.  It is the expensive part of planning a race and it is the
    only honest one.
    """
    if laps < 1:
        return ()
    state = TyreState()
    state.fit(compound, temperature=temperature)
    return tuple(simulate_lap(lap, state) for lap in range(1, laps + 1))


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Stint:
    """One set of tyres, and how long it is meant to last."""

    compound: TyreCompound
    laps: int

    def to_dict(self) -> dict[str, Any]:
        return {"compound": self.compound.code, "laps": self.laps}


@dataclass(frozen=True)
class StrategyPlan:
    """A way of covering the race distance, and what it is projected to cost."""

    stints: tuple[Stint, ...]
    projected_time: Seconds
    pit_loss: Seconds
    """Cost of one stop at this circuit, in seconds."""

    @property
    def stops(self) -> int:
        return max(len(self.stints) - 1, 0)

    @property
    def laps(self) -> int:
        return sum(stint.laps for stint in self.stints)

    @property
    def compounds(self) -> tuple[str, ...]:
        return tuple(stint.compound.code for stint in self.stints)

    def pit_laps(self) -> tuple[int, ...]:
        """The laps this plan stops on."""
        laps: list[int] = []
        running = 0
        for stint in self.stints[:-1]:
            running += stint.laps
            laps.append(running)
        return tuple(laps)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stints": [stint.to_dict() for stint in self.stints],
            "stops": self.stops,
            "pit_laps": list(self.pit_laps()),
            "projected_time": self.projected_time,
            "projected_time_formatted": format_lap_time(self.projected_time),
            "pit_loss": self.pit_loss,
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        legs = " -> ".join(f"{s.compound.code}{s.laps}" for s in self.stints)
        return f"StrategyPlan({legs}, {format_lap_time(self.projected_time)})"


def plan_strategy(
    curves: dict[str, Sequence[Seconds]],
    compounds: Sequence[TyreCompound],
    race_laps: int,
    pit_loss: Seconds,
    *,
    max_stops: int = 3,
    minimum_stint: int = 5,
    require_two_compounds: bool = True,
) -> StrategyPlan:
    """Pick the fastest way of covering ``race_laps``.

    ``curves`` maps a compound code to the lap times a fresh set of it gives,
    lap by lap, as produced by :func:`degradation_curve`.  A plan's projected
    time is then the sum of the laps it actually runs plus the stops it makes,
    and the search is over every split that respects the minimum stint length.

    The two-compound rule is a regulation, so it is a constraint on the search
    rather than a term in the objective.  Turn it off and the same search
    happily runs one compound all race, which is what happens in the wet.
    """
    if race_laps < 1:
        raise EntryError("a race needs at least one lap")
    usable = [c for c in compounds if c.code in curves and curves[c.code]]
    if not usable:
        raise EntryError("no degradation curves to plan with")

    best: StrategyPlan | None = None

    def stint_time(compound: TyreCompound, laps: int) -> Seconds | None:
        """Total time for ``laps`` on a fresh set, or None if it cannot last."""
        curve = curves[compound.code]
        if laps > len(curve):
            return None
        return sum(curve[:laps])

    def search(remaining: int, used: list[Stint], elapsed: Seconds) -> None:
        nonlocal best
        if best is not None and elapsed >= best.projected_time:
            return  # this branch is already slower than something that works
        if remaining == 0:
            if require_two_compounds and len({s.compound.code for s in used}) < 2:
                return
            total = elapsed + pit_loss * (len(used) - 1)
            if best is None or total < best.projected_time:
                best = StrategyPlan(
                    stints=tuple(used), projected_time=total, pit_loss=pit_loss
                )
            return
        if len(used) > max_stops:
            return
        for compound in usable:
            longest = min(remaining, len(curves[compound.code]))
            for laps in range(minimum_stint, longest + 1):
                if remaining - laps != 0 and remaining - laps < minimum_stint:
                    continue
                cost = stint_time(compound, laps)
                if cost is None:
                    continue
                used.append(Stint(compound, laps))
                search(remaining - laps, used, elapsed + cost)
                used.pop()

    search(race_laps, [], 0.0)
    if best is None:
        # Nothing satisfied the constraints -- run whatever lasts longest.
        fallback = max(usable, key=lambda c: len(curves[c.code]))
        curve = curves[fallback.code]
        laps = min(race_laps, len(curve))
        best = StrategyPlan(
            stints=(Stint(fallback, laps),),
            projected_time=sum(curve[:laps]),
            pit_loss=pit_loss,
        )
    return best


# ---------------------------------------------------------------------------
# Deciding during the race
# ---------------------------------------------------------------------------


@dataclass
class RaceStrategy:
    """A plan, and the judgement to abandon it.

    A plan made before the race is a projection of a race that has not happened
    yet.  What makes a strategist is reacting when it stops describing reality:
    the tyres go off early, or it starts raining.  Both are handled here, and
    both are decided by asking the car and the track rather than by a rule
    about lap numbers.
    """

    plan: StrategyPlan | None = None
    compounds: tuple[TyreCompound, ...] = ()
    minimum_stint: int = 5
    wear_limit: float = 0.92
    """Wear at which a set is changed whatever the plan says."""

    grip_margin: float = 0.06
    """How much better a different compound has to be, in grip, before the
    strategist gives up track position to fit it."""

    require_two_compounds: bool = True
    """The regulation that a dry race must be run on two different slicks.

    Suspended the moment it rains, as the real one is: a race that has been run
    on wet-weather tyres has no such requirement, and the strategist stops
    trying to satisfy it rather than throwing away a stop on it."""

    _stint_laps: int = field(default=0, repr=False)
    _stops: int = field(default=0, repr=False)
    _forced: bool = field(default=False, repr=False)
    _used: set[str] = field(default_factory=set, repr=False)
    _wet_running: bool = field(default=False, repr=False)

    # -- bookkeeping ---------------------------------------------------------

    def start_stint(self, compound: TyreCompound | None = None) -> None:
        self._stint_laps = 0
        if compound is not None:
            self._used.add(compound.code)
            if compound.is_wet_weather:
                self._wet_running = True

    @property
    def compounds_used(self) -> frozenset[str]:
        return frozenset(self._used)

    def lap_completed(self) -> None:
        self._stint_laps += 1

    @property
    def stint_laps(self) -> int:
        return self._stint_laps

    @property
    def stops_made(self) -> int:
        return self._stops

    # -- the decision --------------------------------------------------------

    def decide(
        self,
        *,
        lap: int,
        laps_remaining: int,
        tyres: TyreState,
        water_depth: float,
        speed: float = 55.0,
    ) -> TyreCompound | None:
        """The compound to fit at the end of this lap, or ``None`` to stay out.

        Three reasons to stop, in the order a pit wall would weigh them:

        1. the tyre on the car is the wrong one for the track as it now is --
           which is what a shower does, and it does not wait for the plan;
        2. the set is finished, whatever the plan said;
        3. the plan said so.
        """
        if laps_remaining <= 0 or not self.compounds:
            return None

        # 1. Conditions.  Ask which tread copes best with the water that is
        #    actually down, and compare it with what is fitted.
        wanted = compound_for_conditions(self.compounds, water_depth, speed=speed)
        if wanted.code != tyres.compound.code:
            fitted_grip = tyres.compound.peak_friction * wet_grip_factor(
                tyres.compound, water_depth, speed
            )
            wanted_grip = wanted.peak_friction * wet_grip_factor(
                wanted, water_depth, speed
            )
            if wanted_grip > fitted_grip * (1.0 + self.grip_margin):
                self._forced = True
                return wanted

        if self._stint_laps < self.minimum_stint and not self._forced:
            return None

        # 2. The set is finished.
        if tyres.wear >= self.wear_limit and laps_remaining > self.minimum_stint:
            return self._planned_next(water_depth, speed)

        # 3. The plan.
        if self.plan is not None and lap in self.plan.pit_laps():
            return self._planned_next(water_depth, speed)
        return None

    def _planned_next(self, water_depth: float, speed: float) -> TyreCompound:
        """The next compound the plan calls for, or the best one available."""
        if self.plan is not None:
            index = self._stops + 1
            if index < len(self.plan.stints):
                return self.plan.stints[index].compound

        best = compound_for_conditions(self.compounds, water_depth, speed=speed)
        if not self._needs_a_second_compound(best):
            return best

        # The regulation says two different slicks, so among the ones that
        # still work here, take the best that has not been used.
        unused = [
            compound
            for compound in self.compounds
            if compound.code not in self._used and not compound.is_wet_weather
        ]
        if not unused:
            return best
        return compound_for_conditions(unused, water_depth, speed=speed)

    def _needs_a_second_compound(self, wanted: TyreCompound) -> bool:
        """Whether the two-compound rule still has to be satisfied."""
        if not self.require_two_compounds or self._wet_running:
            return False
        if wanted.is_wet_weather:
            return False
        wet_codes = {c.code for c in self.compounds if c.is_wet_weather}
        dry_used = self._used - wet_codes
        return len(dry_used) < 2 and wanted.code in dry_used

    def record_stop(self, compound: TyreCompound | None = None) -> None:
        self._stops += 1
        self._forced = False
        self.start_stint(compound)
