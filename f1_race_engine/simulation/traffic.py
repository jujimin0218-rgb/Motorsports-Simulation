"""What the lap simulation asks about the cars in front of it.

The split here is deliberate and it is the whole of Phase 9's architecture:

* the **lap simulator does physics.**  It asks, once per segment, "what is the
  air like here, may I open DRS, and how fast am I allowed to go" -- and then
  applies the answers through the same force balance it has always used.
* the **traffic model does racing.**  Where the cars are, who is in whose wake,
  who is trying to pass and whether they get by is a question about a field of
  cars, and it belongs to whoever owns the field.

Neither knows how the other works.  A lap with no traffic model is a lap in
clean air, which is what every phase before this one was.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ..core.units import MetresPerSecond, Seconds
from ..race.wake import CLEAN_AIR, WakeEffect

__all__ = ["CLEAR", "TrafficModel", "TrafficState"]


@dataclass(frozen=True, slots=True)
class TrafficState:
    """What the road ahead is like at one point of one lap."""

    wake: WakeEffect = CLEAN_AIR
    """The air, as left by whoever is in front."""

    drs_allowed: bool = False
    """Whether this car was close enough at the detection point."""

    speed_limit: MetresPerSecond = float("inf")
    """Fastest this car may go here without driving into the one in front."""

    off_line: bool = False
    """Whether the car is off the racing line -- committed to a move, and on
    the surface where the marbles are."""

    offset: float = 0.0
    """Where the car is across the road, m from the line, left positive.

    The road has a width and this is the car's place on it.  Two cars are
    racing side by side when their offsets differ by a car width, and a move
    only exists at all where the road is wide enough to hold both."""

    passed: int | None = None
    """Car number just overtaken, if the move completed on this segment."""

    bias: float = 0.0
    """Which line the car is on: -1 hard outside, 0 the racing line, +1 hard
    inside.  Where ``offset`` is the metres, this is the choice that produced
    them, and it is the choice that has a radius."""

    corner_scale: float = 1.0
    """What this car's line does to its cornering speed, as a multiplier.

    The whole price of racecraft, in one number.  A car on the racing line goes
    round the radius the circuit was authored with and this is 1.0; a car
    holding the inside to defend is on a tighter path, and since
    ``v = sqrt(a / kappa)`` its corner speed scales by the square root of the
    ratio of the two curvatures.  Nothing adds a penalty for defending: the
    defender is simply driving a smaller circle."""

    ran_wide: bool = False
    """Whether the car asked for more than its line and its grip could give and
    is on its way off the road because of it."""

    @property
    def is_clear(self) -> bool:
        return self.speed_limit == float("inf") and not self.wake.in_traffic

    def to_dict(self) -> dict[str, Any]:
        return {
            "wake": self.wake.to_dict(),
            "drs_allowed": self.drs_allowed,
            "speed_limit": None if self.speed_limit == float("inf") else self.speed_limit,
            "off_line": self.off_line,
            "offset": self.offset,
            "passed": self.passed,
            "bias": self.bias,
            "corner_scale": self.corner_scale,
            "ran_wide": self.ran_wide,
        }


#: Nobody in front, nothing in the way.
CLEAR = TrafficState()


class TrafficModel(Protocol):
    """What a lap simulation needs to know about everybody else.

    Implemented by :class:`f1_race_engine.race.traffic.Traffic`, which is the
    only thing that knows where the other cars actually are.
    """

    def preview(
        self, *, distance: float, elapsed: Seconds, speed: MetresPerSecond
    ) -> TrafficState:
        """The state of the road, without racing anybody for it.

        Asked *before* the lap, to work out what plan is even available: a
        driver following another car brakes earlier for the corner because they
        know the downforce will not be there, rather than discovering it at the
        apex.  It races nobody and completes no moves, so asking it changes
        nothing about who is where.
        """
        ...

    def at(
        self, *, distance: float, elapsed: Seconds, speed: MetresPerSecond
    ) -> TrafficState:
        """The state of the road for this car, here and now.

        Called once per segment while the lap is driven, and allowed to change
        the model's mind about who is where -- this is where a move completes.
        """
        ...
