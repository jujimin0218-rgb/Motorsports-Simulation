"""Choosing a line, and finding out whether it was the right one.

:mod:`f1_race_engine.race.traffic` decides *where on the road* a car wants to
be -- it is the module that knows who is ahead, how big the gap is and whether
there is room.  This one turns that into the two things the physics needs: which
line the car is on, and what that line costs it.

**The mechanism.**  A line has a radius, and ``v = sqrt(a / kappa)``, so a car
on a tighter path corners more slowly.  That single fact does all the work here:

* defending is expensive because the inside line is tighter, not because
  defending has a penalty attached to it;
* a dive down the inside is slow through the corner and quick to the corner,
  which is why it works when the attacker is close enough and does not when
  they are not;
* going round the outside is a longer way with a bigger radius, which is why it
  only comes off somewhere fast and wide.

Nobody chose those outcomes.  They are the same square root, applied to three
different paths.

**Running wide is not a dice roll.**  A lap is planned before it is driven --
that is how the wake and DRS are known in advance -- and the plan assumes a
line.  A driver who commits to something tighter *after* the plan was made
arrives carrying speed for a radius they are no longer on, and the difference
between the two is what puts them off the road.  So an excursion here is the
consequence of a decision plus a speed, and there is no sampling anywhere in
this file.  What the driver's attributes change is how likely they are to *try*
it, never whether it comes off.
"""

from __future__ import annotations

from ..world.line import Lines

__all__ = ["bias_of_offset", "corner_scale", "holds_the_line"]

#: Curvature below which a piece of road is straight, 1/m -- a two kilometre
#: radius.  Where the road does not turn, no choice of line costs corner speed.
STRAIGHT = 1.0 / 2000.0

#: Bounds on what a line may be worth, as a multiplier on cornering speed.
#:
#: Measured on real circuits the range a car can actually reach is about 0.92
#: to 1.05; these are far outside it and exist only so that dividing two
#: three-point curvature estimates can never produce a car that crawls.
LEAST = 0.7
MOST = 1.3

#: How much of the cornering limit a driver leaves in hand on the racing line.
#:
#: Not a fudge factor for lap time -- the speed profile is what sets that, and
#: it is unchanged.  This is the margin a driver has to *recover* with when the
#: road turns out tighter than the one they planned for, and it is what decides
#: whether a late dive is a move or an excursion.  Eight per cent of lateral
#: grip is about a car's width of run-out at a medium-speed corner.
MARGIN = 0.08

#: How much more of that margin the best racers have than the worst, as a
#: fraction of it.  A driver with the racecraft to place a car on the edge of
#: its grip can take a tighter line late and still hold it.
MARGIN_SPREAD = 0.5


def bias_of_offset(lines: Lines, index: int, offset: float) -> float:
    """Which line a car sitting at ``offset`` metres is on.

    The inverse of :meth:`Lines.at`, so that the part of the race that
    thinks in metres across the road and the part that thinks in lines agree
    about where a car is.  Clamped to the road: a car pushed wider than the
    outside line is on the outside line as far as its radius is concerned, and
    what happens to it after that is the world layer's business.
    """
    optimal = lines.optimal.offsets[index]
    moved = offset - optimal
    if moved == 0.0:
        return 0.0
    # Which edge the car has moved towards decides which reach it is measured
    # against; the two are different sizes, because the racing line is not in
    # the middle of the road.
    toward_inside = lines.inside_edge[index] - optimal
    toward_outside = lines.outside_edge[index] - optimal
    if toward_inside != 0.0 and moved * toward_inside > 0.0:
        return min(moved / toward_inside, 1.0)
    if toward_outside != 0.0 and moved * toward_outside > 0.0:
        return -min(moved / toward_outside, 1.0)
    # The racing line is already hard against the edge the car has moved
    # towards, so there is no road that way and no line to be on but this one.
    return 0.0


def corner_scale(road_curvature: float, line_curvature: float) -> float:
    """What a line does to cornering speed, as a multiplier.

    ``v = sqrt(a / kappa)`` with the same tyres either side of it, so the ratio
    of speeds is the square root of the inverse ratio of curvatures.

    **A straight is not a corner taken slowly.**  The racing line down a
    straight is straight, so its curvature is nearly zero, and a car easing
    across the road has a small curvature of its own -- the ratio of the two is
    then enormous in the wrong direction and would have a car crawling down the
    pit straight for having moved over.  Nothing is limiting that car
    laterally, so where the road does not turn, a line costs nothing.

    The result is bounded either side as well.  What is being divided is two
    three-point estimates taken four metres apart, and near the ends of their
    range that arithmetic is noise rather than radius; the bounds are wide
    enough that every real line measured on a real circuit falls inside them.
    """
    road = abs(road_curvature)
    line = abs(line_curvature)
    if road < STRAIGHT or line < STRAIGHT:
        return 1.0
    return min(MOST, max(LEAST, (road / line) ** 0.5))


def holds_the_line(
    planned_scale: float, actual_scale: float, racecraft: float
) -> bool:
    """Whether a car can hold a line tighter than the one it planned for.

    The car arrives with the speed the plan gave it.  If the line it is now on
    would have been driven more slowly, the difference has to come out of the
    grip the driver kept in hand -- and if it is more than they kept, the car
    goes where its speed is taking it, which is off the outside of the corner.

    ``racecraft`` is the driver's, from 0 to 1, and widens the margin by half
    again across the field.  It changes who can pull a late move off; it does
    not change what happens when the move is beyond them.
    """
    if actual_scale >= planned_scale:
        return True
    margin = MARGIN * (1.0 + MARGIN_SPREAD * (racecraft - 0.5) * 2.0)
    return actual_scale >= planned_scale * (1.0 - max(margin, 0.0))
