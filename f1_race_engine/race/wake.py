"""What a car in front does to the air behind it (project rule 29).

Two effects, opposite in sign, and both of them are the same hole in the air:

**Dirty air.** A wing works by bending clean air.  Behind another car the air is
already bent, slow and turbulent, so the wing makes less downforce -- and
downforce is what a Formula 1 car corners on.  A car half a second behind loses
a few per cent of it, which is a few tenths of a lap; enough that following is
work, not enough that the gap opens on its own.  That balance is the whole
reason "he was quicker but couldn't get past" is a sentence about aerodynamics
rather than about drivers, and it is also why DRS trains form.

**The tow.** The same hole in the air is a hole: the following car has less air
to push out of the way, so it has less drag.  On a straight that is worth
speed, and it is why a slipstream is a real overtaking tool.

Both decay with the *time* gap rather than the distance gap, because the wake
is convected downstream with the car: at 300 km/h a second is 83 metres and at
100 km/h it is 28, and the aerodynamic effect is much the same in both.  That is
also how the sport talks about it -- "within a second" -- which is not a
coincidence.

Nothing here is a lap-time penalty.  The wake changes two aerodynamic
coefficients and the rest of the engine works out what that costs, which is why
it costs more at a circuit with fast corners than at one without, and why a
draggy car gains more from a tow than a slippery one does.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from ..core.config import WakeConfig
from ..core.interpolation import clamp

__all__ = ["WakeEffect", "wake_effect"]


@dataclass(frozen=True, slots=True)
class WakeEffect:
    """What the air behind another car does to this one."""

    gap: float
    """Time gap to the car ahead, s.  ``inf`` in clean air."""

    downforce_factor: float = 1.0
    """Multiplier on downforce.  Below one in dirty air."""

    drag_factor: float = 1.0
    """Multiplier on drag.  Below one in a tow."""

    @property
    def in_traffic(self) -> bool:
        return self.downforce_factor < 1.0 or self.drag_factor < 1.0

    @property
    def downforce_loss(self) -> float:
        return 1.0 - self.downforce_factor

    @property
    def drag_saving(self) -> float:
        return 1.0 - self.drag_factor

    def to_dict(self) -> dict[str, Any]:
        return {
            "gap": None if math.isinf(self.gap) else self.gap,
            "downforce_factor": self.downforce_factor,
            "drag_factor": self.drag_factor,
        }


#: Clean air: the answer whenever there is nobody in front.
CLEAN_AIR = WakeEffect(gap=float("inf"))


def wake_effect(gap: float, config: WakeConfig | None = None) -> WakeEffect:
    """The wake a car ``gap`` seconds behind another one is sitting in.

    Both terms decay exponentially with the gap, which is the shape a convected
    wake actually has and which has the useful property of never quite reaching
    zero -- a car three seconds back is still very slightly affected, as it is
    in reality.
    """
    if gap <= 0.0:
        gap = 0.0
    if math.isinf(gap):
        return CLEAN_AIR
    cfg = config or WakeConfig()
    if gap > cfg.range:
        return WakeEffect(gap=gap)

    downforce_loss = cfg.peak_downforce_loss * math.exp(-gap / cfg.downforce_scale)
    drag_saving = cfg.peak_drag_saving * math.exp(-gap / cfg.drag_scale)
    return WakeEffect(
        gap=gap,
        downforce_factor=clamp(1.0 - downforce_loss, cfg.minimum_downforce, 1.0),
        drag_factor=clamp(1.0 - drag_saving, 0.1, 1.0),
    )
