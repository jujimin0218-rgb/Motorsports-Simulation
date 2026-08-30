"""Race control: the flag state, and what it does to a race.

The separation this module exists to keep is between **what happened** and
**what is done about it**.  Incidents happen to cars; flags are a decision
taken about the circuit.  The same failure produces a local yellow at one point
on the lap and a red flag at another, and none of that belongs in the failure.

Four states matter, and each is a different activity rather than a slower
version of racing:

``GREEN``
    Racing.  Nothing here touches the lap.
``VSC``
    A delta every car must stay above.  Gaps are preserved, because everybody
    slows by the same proportion -- which is the whole point of it, and why a
    stop under a virtual safety car is worth less than one under the real one.
``SAFETY_CAR``
    A different activity.  The field is bunched up behind a car doing about
    two thirds of racing speed, so gaps are destroyed and a stop costs about
    half what it would have.
``RED_FLAG``
    The race is stopped.  Cars go back to the pit lane, tyres may be changed
    for nothing, and the race restarts in the order it was stopped in.

Nothing in here decides *whether* an incident happens; that is
:mod:`f1_race_engine.events.reliability` and
:mod:`f1_race_engine.events.collision`.  What is decided here is only the
response, and the shares it is drawn from are what race control actually does:
most stopped cars are recovered under a local yellow, a good many need a
virtual safety car, fewer need the real one, and a handful of races a season
are stopped altogether.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Sequence

from ..core.config import RaceControlConfig
from ..core.events import Event
from ..core.rng import RandomStream
from ..core.units import Seconds
from .incident import Incident, IncidentSeverity

__all__ = [
    "FlagState",
    "Neutralisation",
    "RaceControl",
    "RaceControlDecision",
    "FlagChanged",
]


class FlagState(str, Enum):
    """What the circuit is doing."""

    GREEN = "green"
    YELLOW = "yellow"
    VSC = "virtual_safety_car"
    SAFETY_CAR = "safety_car"
    RED_FLAG = "red_flag"

    @property
    def is_neutralised(self) -> bool:
        """Whether racing is suspended, in the sense that pace is dictated."""
        return self in (FlagState.VSC, FlagState.SAFETY_CAR, FlagState.RED_FLAG)

    @property
    def allows_overtaking(self) -> bool:
        return self is FlagState.GREEN


@dataclass(frozen=True)
class FlagChanged(Event):
    """Bus event: the circuit changed state."""

    previous: FlagState = FlagState.GREEN
    current: FlagState = FlagState.GREEN
    lap: int = 0
    reason: str = ""


@dataclass(frozen=True, slots=True)
class Neutralisation:
    """What a flag does to one lap, for one car."""

    flag: FlagState
    pace_factor: float = 1.0
    """Multiplier on the green lap time."""

    pit_saving: float = 0.0
    """Share of a green-flag stop's cost that disappears."""

    bunches: bool = False
    """Whether the field is compressed to a single file."""

    racing: bool = True
    """Whether cars may fight each other."""

    @property
    def is_green(self) -> bool:
        return self.flag is FlagState.GREEN


GREEN = Neutralisation(FlagState.GREEN)


@dataclass
class RaceControlDecision:
    """The outcome of assessing one lap's incidents."""

    flag: FlagState
    laps: int = 0
    reason: str = ""
    triggered_by: Incident | None = None

    @property
    def changed(self) -> bool:
        return self.flag is not FlagState.GREEN


class RaceControl:
    """The flag state machine for one race."""

    __slots__ = ("config", "_stream", "_flag", "_remaining", "_green_laps", "_log", "_deployed_lap")

    def __init__(
        self,
        stream: RandomStream,
        config: RaceControlConfig | None = None,
    ) -> None:
        self.config = config or RaceControlConfig()
        self._stream = stream
        self._flag = FlagState.GREEN
        self._remaining = 0
        self._green_laps = self.config.minimum_green_laps
        self._deployed_lap = 0
        self._log: list[tuple[int, FlagState, str]] = []

    # -- state ---------------------------------------------------------------

    @property
    def flag(self) -> FlagState:
        return self._flag

    @property
    def laps_remaining(self) -> int:
        """Laps this neutralisation still has to run."""
        return self._remaining

    @property
    def log(self) -> tuple[tuple[int, FlagState, str], ...]:
        """Every flag change, as ``(lap, flag, reason)``."""
        return tuple(self._log)

    def neutralisation(self) -> Neutralisation:
        """What the current flag does to a lap."""
        cfg = self.config
        if self._flag is FlagState.SAFETY_CAR:
            return Neutralisation(
                FlagState.SAFETY_CAR,
                pace_factor=cfg.safety_car_pace,
                pit_saving=cfg.safety_car_pit_saving,
                bunches=True,
                racing=False,
            )
        if self._flag is FlagState.VSC:
            return Neutralisation(
                FlagState.VSC,
                pace_factor=cfg.vsc_pace,
                pit_saving=cfg.vsc_pit_saving,
                bunches=False,
                racing=False,
            )
        if self._flag is FlagState.RED_FLAG:
            return Neutralisation(
                FlagState.RED_FLAG,
                pace_factor=cfg.safety_car_pace,
                pit_saving=1.0,
                bunches=True,
                racing=False,
            )
        return GREEN

    # -- running it ----------------------------------------------------------

    def assess(self, lap: int, incidents: Sequence[Incident]) -> RaceControlDecision:
        """Decide what the circuit does after ``lap``.

        Called once per lap with everything that went wrong on it.  Returns the
        decision so the caller can log or publish it; the state is updated here.
        """
        if self._flag.is_neutralised:
            self._remaining -= 1
            if self._remaining <= 0:
                self._to_green(lap)
            return RaceControlDecision(self._flag, self._remaining, "running")

        self._green_laps += 1
        recoverable = [i for i in incidents if i.needs_recovery]
        if not recoverable or self._green_laps < self.config.minimum_green_laps:
            return RaceControlDecision(FlagState.GREEN, 0, "clear")

        # The worst of them decides, and multiple cars stopping on the same lap
        # makes a stronger response more likely -- which is why a first-corner
        # pile-up stops a race and one car in a gravel trap does not.
        worst = max(recoverable, key=lambda i: (i.severity is IncidentSeverity.BLOCKING, len(i.involved)))
        weight = min(len(recoverable), 4)
        return self._respond(lap, worst, weight)

    def _respond(self, lap: int, incident: Incident, weight: int) -> RaceControlDecision:
        cfg = self.config
        roll = self._stream.derive("response", lap).random()
        red = min(cfg.red_flag_share * weight, 1.0)
        safety = min(cfg.safety_car_share * weight, 1.0 - red)
        virtual = min(cfg.vsc_share * weight, 1.0 - red - safety)

        if roll < red:
            return self._deploy(lap, FlagState.RED_FLAG, cfg.red_flag_restart_laps + 1,
                                "race stopped", incident)
        if roll < red + safety:
            low, high = cfg.safety_car_laps
            laps = self._stream.derive("sc_laps", lap).integer(low, high)
            return self._deploy(lap, FlagState.SAFETY_CAR, laps, "safety car", incident)
        if roll < red + safety + virtual:
            low, high = cfg.vsc_laps
            laps = self._stream.derive("vsc_laps", lap).integer(low, high)
            return self._deploy(lap, FlagState.VSC, laps, "virtual safety car", incident)
        return RaceControlDecision(FlagState.GREEN, 0, "recovered under yellow", incident)

    def _deploy(
        self, lap: int, flag: FlagState, laps: int, reason: str, incident: Incident
    ) -> RaceControlDecision:
        self._flag = flag
        self._remaining = max(laps, 1)
        self._green_laps = 0
        self._deployed_lap = lap
        self._log.append((lap, flag, reason))
        return RaceControlDecision(flag, self._remaining, reason, incident)

    def _to_green(self, lap: int) -> None:
        if self._flag is not FlagState.GREEN:
            self._log.append((lap, FlagState.GREEN, "green flag"))
        self._flag = FlagState.GREEN
        self._remaining = 0
        self._green_laps = 0

    # -- what a neutralisation does to the field -----------------------------

    def bunch(self, elapsed: dict[int, float], order: Sequence[int]) -> dict[int, float]:
        """Compress the field behind the safety car.

        Gaps become the interval a queue of cars running to a delta actually
        holds, which is why a safety car is the single biggest thing that can
        happen to a race: a thirty-second lead is worth one second again.
        """
        if not order:
            return elapsed
        leader = elapsed[order[0]]
        gap = self.config.bunching_gap
        return {
            car: (leader + index * gap if car in elapsed else elapsed[car])
            for index, car in enumerate(order)
        } | {car: value for car, value in elapsed.items() if car not in order}

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"RaceControl(flag={self._flag.value}, remaining={self._remaining})"
