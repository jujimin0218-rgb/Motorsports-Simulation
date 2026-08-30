"""Wet-weather grip (project rule 30).

Two different things happen to a car when it rains, and conflating them is how
wet weather ends up as a lap-time multiplier.

**The asphalt gets slippery.** A wet road has a lower friction coefficient than
a dry one even with no standing water on it at all.  That is a property of the
*surface*, it applies to every tyre equally, and it lives in
:class:`~f1_race_engine.track.surface.TrackConditions`.

**The tyre has to get the water out of the way.** Standing water has to be
evacuated through the tread in the time the contact patch is over it, and that
time shrinks as the car goes faster.  Whatever is not evacuated lifts the tyre
off the road.  That is a property of the *tyre*, it is what tread pattern is
for, and it lives here.

The second one is why a slick on a wet track is undrivable rather than merely
slow, why a full wet works in standing water that destroys an intermediate, and
why aquaplaning is a speed limit rather than a coin flip: the faster you go, the
less water you can clear, so for any depth there is a speed above which the tyre
is floating.  None of that is written down below -- there is one clearance
model, and all of it follows.
"""

from __future__ import annotations

from ..core.config import WetConfig
from ..core.interpolation import clamp
from .compound import TyreCompound

__all__ = ["aquaplaning_speed", "water_clearance", "wet_grip_factor"]


def water_clearance(
    compound: TyreCompound, speed: float, config: WetConfig | None = None
) -> float:
    """Depth of water this tread can evacuate at ``speed``, m.

    A slick has no tread and clears nothing, at any speed.  A grooved tyre
    clears its rated depth up to the reference speed and less above it, because
    the contact patch spends less time over each piece of road.
    """
    cfg = config or WetConfig()
    capacity = compound.peak_water_depth
    if capacity <= 0.0:
        return 0.0
    if speed <= cfg.reference_clearance_speed:
        return capacity
    return capacity * (cfg.reference_clearance_speed / speed) ** cfg.clearance_exponent


def wet_grip_factor(
    compound: TyreCompound,
    water_depth: float,
    speed: float,
    config: WetConfig | None = None,
) -> float:
    """Grip multiplier from the water this tyre cannot get rid of.

    1.0 on a dry track, and near enough 1.0 in the light water a tread is built
    for -- the surface penalty for a wet road has already been charged
    elsewhere, so this is only the film left under the contact patch.

    That film is not zero right up to the tread's limit and then everything all
    at once.  Evacuation is a rate: the closer the water gets to what the
    grooves can move in the time the patch is over it, the more of it stays
    behind.  So the loss arrives gradually as the tread runs out of room and
    only then turns into flotation.  Modelled as a switch instead, an
    intermediate in 0.2 mm of water and one in 2 mm lap identically and then
    the tyre falls off a cliff between one shower and the next, which is not
    what a wet race looks like.
    """
    if water_depth <= 0.0:
        return 1.0
    cfg = config or WetConfig()
    clearance = water_clearance(compound, speed, cfg)
    if clearance <= 0.0:
        # A slick has no grooves: every millimetre of it stays under the tyre.
        film = water_depth
    else:
        utilisation = min(water_depth / clearance, 1.0)
        film = clearance * cfg.residual_film_fraction * (
            utilisation**cfg.residual_film_exponent
        )
        film += max(water_depth - clearance, 0.0)
    if film <= 0.0:
        return 1.0
    return clamp(1.0 / (1.0 + film / cfg.aquaplaning_depth), cfg.min_wet_grip, 1.0)


def aquaplaning_speed(
    compound: TyreCompound, water_depth: float, config: WetConfig | None = None
) -> float:
    """Speed above which this tyre starts floating in this depth, m/s.

    ``inf`` when the tread out-clears the water at any speed, and zero for a
    tyre that cannot cope with the depth even at walking pace.  Solved from the
    clearance model rather than tabulated, so it moves when the tyre does.
    """
    cfg = config or WetConfig()
    capacity = compound.peak_water_depth
    if capacity <= 0.0:
        return 0.0 if water_depth > 0.0 else float("inf")
    if water_depth <= 0.0:
        return float("inf")
    if water_depth >= capacity:
        # Already beyond the tread's rated depth at the reference speed.
        return 0.0 if water_depth > capacity else cfg.reference_clearance_speed
    # clearance(v) = capacity * (v_ref / v)^n = depth  ->  v = v_ref * (capacity/depth)^(1/n)
    return cfg.reference_clearance_speed * (capacity / water_depth) ** (
        1.0 / cfg.clearance_exponent
    )
