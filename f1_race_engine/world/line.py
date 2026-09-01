"""The line a car drives, and what that line costs it.

**The problem this solves.**  A circuit in this engine is authored as a
*driven line*: the radii are the ones a car actually goes round on, chosen so
the lap time comes out right.  That is a good way to author a circuit and a
bad way to have a race in one, because it leaves no road.  The world layer laid
its asphalt symmetrically around those radii, so the thing under the cars was
the racing line with a verge either side -- and a line that *is* the road
cannot be left, so going round the outside and going round the inside were the
same lap, and an overtake had to be decided by a model rather than by driving.

So the road is put back.  :func:`road_under_line` asks the racing-line solver
where a car would go if the authored path were a road, and then treats that
answer as the shape of the *weave* rather than as a new line: the road is slid
the other way by it, leaving the authored path sitting across the road exactly
where a racing line sits -- wide, apex, wide.

**What this is and is not.**  It is a construction, not a fixed point.  A true
inverse would be the road whose own quickest line comes back as the authored
path, and iterating towards it does not converge here: the solve pins against
the edges of the road for long stretches, so a small move in the road flips
which edge is pinned and the iteration limit-cycles at around a metre.  It was
measured, damped, and abandoned.  One solve is used instead, which is
well-defined, cheap and stable, and gives a road that is plausibly the one this
line belongs to rather than provably so.

**Why that is enough.**  Correctness here does not rest on the reconstruction.
The racing line is *declared* to be the authored path, so a car on it drives
exactly the radii the circuit was validated with, whatever road is drawn around
it -- every lap time this engine has ever produced is unchanged to the last
decimal, and the test at the bottom of ``test_line.py`` is that identity.  What
the reconstruction buys is only that there is now somewhere else to be, and
that being there has a radius of its own.

**Where a car can be.**  One line and two edges.  The racing line is the
authored path; the edges are as far towards the inside and the outside of the
corner as a car can get without leaving the road.  A driver's choice is a
single number, ``bias``, running from -1 at the outside edge through 0 on the
racing line to +1 at the inside, and where they end up is the blend.

This was two more solved lines to begin with -- a defensive line and an
overtaking one, each its own biharmonic solve held to half the road -- and it
was wrong.  Neither solved line reliably sits *on the side of the racing line*
its name claims: through a corner exit the racing line is hard against the
outside edge, so the relaxed "outside" line is inboard of it, and a bias
sweeping from -1 to +1 then doubled back on itself.  A place across the road no
longer had one line that produced it, which broke reading a car's choice back
out of where it is.  Blending towards an edge is monotonic by construction, so
that cannot happen; it is also two fewer solves per circuit.

:meth:`Lines.at` and :func:`curvature_between` are the runtime pair, called for
every car on every step, so they touch three samples and nothing else.  The
solving happens once per circuit.

**Sign convention**, shared with the rest of the world package: positive is to
the left, and a positive curvature turns left.  The inside of a corner is
therefore always ``side * room``, and there is no left/right special case
anywhere below.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..track.racing_line import USABLE_FRACTION, solve_racing_line
from .body import CAR_WIDTH
from .geometry import Vec2

__all__ = [
    "Line",
    "Lines",
    "curvature_at",
    "curvature_between",
    "curvature_of",
    "road_under_line",
    "solve_lines",
]

#: Curvature below which a piece of road counts as straight, 1/m -- a two
#: kilometre radius.  Used only to decide which side of the road is the inside
#: of a corner; no physics rounds curvature off.
STRAIGHT = 1.0 / 2000.0

#: How far the corner-side decision is smoothed, m.  A sample-by-sample answer
#: flips back and forth along a straight, which would send the inside line
#: weaving wall to wall down it; a corner's length of smoothing leaves the line
#: where the last real corner put it, which is also where a driver leaves it.
SIDE_SMOOTH_M = 90.0


def curvature_at(before: Vec2, here: Vec2, after: Vec2) -> float:
    """Curvature of the circle through three points, 1/m, positive to the left.

    Menger's formula, written from the cross product rather than from three
    lengths and an area because the sign falls out of it -- and the sign is
    what says which way the corner goes.
    """
    first = here - before
    second = after - here
    span = after - before
    denominator = first.length * second.length * span.length
    if denominator == 0.0:
        return 0.0
    return 2.0 * first.cross(second) / denominator


def curvature_of(points: tuple[Vec2, ...]) -> tuple[float, ...]:
    """Curvature at every point of a closed polyline."""
    count = len(points)
    if count < 3:
        return tuple(0.0 for _ in points)
    return tuple(
        curvature_at(points[index - 1], points[index], points[(index + 1) % count])
        for index in range(count)
    )


@dataclass(frozen=True, slots=True)
class Line:
    """One path round the circuit, as a place across the road at each sample."""

    offsets: tuple[float, ...]
    """Metres left of the road's centreline at each sample."""

    points: tuple[Vec2, ...]
    curvature: tuple[float, ...]
    """Curvature of *this path*, 1/m -- not of the road under it."""

    def offset_at(self, length: float, step: float, distance: float) -> float:
        """Where this line is across the road at a lap distance, m."""
        wrapped = distance % length
        exact = wrapped / step
        index = int(exact)
        nudge = exact - index
        count = len(self.offsets)
        here = self.offsets[index % count]
        there = self.offsets[(index + 1) % count]
        return here + (there - here) * nudge

    @property
    def lap_length(self) -> float:
        """How far a lap of this line is, m.

        The quickest line is not the shortest one, and this is what says so.
        """
        count = len(self.points)
        return sum(
            (self.points[(index + 1) % count] - self.points[index]).length
            for index in range(count)
        )


@dataclass(frozen=True, slots=True)
class Lines:
    """The racing line, and the road either side of it to move into."""

    optimal: Line
    """The quickest way round: out, in, out.  The authored path."""

    inside_edge: tuple[float, ...]
    """As far towards the inside of the corner as a car can go, m.

    Not a solved line.  A defender does not drive a second racing line, they
    take the road on the inside and give up the radius -- so the far end of the
    choice is the edge of the road, and every line between here and the racing
    line is a blend of the two."""

    outside_edge: tuple[float, ...]
    room: tuple[float, ...]
    """Half the usable road at each sample, m, with the car's width taken off."""

    side: tuple[float, ...]
    """Which way each sample turns, from -1 (right) to +1 (left).

    Continuous rather than a flag.  Which side of the road is "the inside"
    changes at every corner, and a value that jumped from one to the other
    between two samples would put a nine metre kink in the line a defending car
    is on -- and a kink is a radius, which the physics would then charge for."""

    def at(self, index: int, bias: float) -> float:
        """The offset of a car sitting ``bias`` off the racing line, m.

        ``bias`` runs from -1 (hard against the outside of the corner) through
        0 (the racing line) to +1 (hard against the inside), and is the one
        number a driver chooses.  Deliberately not metres: the inside of a
        corner is a different distance away at every point on a circuit, and a
        driver thinks "tighter", not "one point four metres to the left".

        Monotonic in ``bias`` by construction, and therefore invertible -- the
        race carries a car's place in metres and asks for it back as a line, so
        the two have to agree.
        """
        optimal = self.optimal.offsets[index]
        edge = self.inside_edge[index] if bias >= 0.0 else self.outside_edge[index]
        return optimal + abs(bias) * (edge - optimal)

    def room_at(self, index: int, bias: float) -> float:
        """How much road is left on the inside of a car on ``bias``, m.

        What an attacker actually asks: is there a car's width between that car
        and the edge of the road on the side I want to be.
        """
        return abs(self.inside_edge[index] - self.at(index, bias))


def curvature_between(
    centre: tuple[Vec2, ...],
    headings: tuple[float, ...],
    lines: Lines,
    index: int,
    bias: float,
) -> float:
    """Curvature of the path a car on ``bias`` is actually driving, 1/m.

    This is the number the tyres are asked about, and it is the whole reason
    choosing a line has a price.  Taken from the three samples around the car
    rather than from a stored table, because the line a car is on is its own --
    no two cars in a battle are on the same one, and neither of them is on a
    line that was ever solved for.
    """
    count = len(centre)
    before = (index - 1) % count
    after = (index + 1) % count
    return curvature_at(
        _place(centre, headings, before, lines.at(before, bias)),
        _place(centre, headings, index, lines.at(index, bias)),
        _place(centre, headings, after, lines.at(after, bias)),
    )


def road_under_line(
    line: tuple[Vec2, ...],
    headings: tuple[float, ...],
    width: tuple[float, ...],
    step: float,
) -> tuple[float, ...]:
    """How far the racing line sits from the road's centreline, m.

    The circuit was authored as the path a car takes.  A path is not a road,
    and a race needs the road: somewhere to be that is not the racing line.

    So the solver is asked where a car would weave if this path were a road,
    and the answer is used as the weave itself -- the road is slid the other
    way by it.  The shape is the solver's, which means it is wide before a
    corner, against the inside at the apex and wide again at the exit; only its
    role is reversed.  See the module docstring for why this is a construction
    rather than an inverse, and why that is enough.

    Returned as the offset **of the line from the road**, so the road is at
    ``line - offset`` and the racing line is at ``+offset`` across it.  A
    positive number is to the left, as everywhere else here.
    """
    if len(line) < 8:
        return tuple(0.0 for _ in line)
    return solve_racing_line(curvature_of(line), width, step).offset


def solve_lines(
    line: tuple[Vec2, ...],
    headings: tuple[float, ...],
    width: tuple[float, ...],
    step: float,
) -> tuple[tuple[Vec2, ...], Lines]:
    """Reconstruct the road under a driven line and work out where a car may go.

    Returns the road's centreline and the choices across it.  Done once per
    circuit and cached by the caller: a multigrid biharmonic solve over a few
    thousand samples is far too much per car per lap, and none of it depends on
    the car.
    """
    count = len(line)
    normals = _normals(headings)
    optimal_offset = road_under_line(line, headings, width, step)
    centre = tuple(line[i] - normals[i] * optimal_offset[i] for i in range(count))

    room = tuple(
        max(0.0, (width[i] - CAR_WIDTH) * 0.5 * USABLE_FRACTION) for i in range(count)
    )
    # Which way the corners go is read off the *line*, not the road: the line is
    # what a driver is looking down, and through a sequence of quick kinks it is
    # straighter than the road, which is exactly where the road's own curvature
    # would send a defending car weaving across it.
    side = _sides(curvature_of(line), step)

    inside = tuple(side[i] * room[i] for i in range(count))
    outside = tuple(-side[i] * room[i] for i in range(count))
    return centre, Lines(
        optimal=_line(centre, normals, optimal_offset),
        inside_edge=inside,
        outside_edge=outside,
        room=room,
        side=side,
    )


# -- internals ---------------------------------------------------------------


def _line(
    centre: tuple[Vec2, ...], normals: tuple[Vec2, ...], offsets: tuple[float, ...]
) -> Line:
    points = tuple(centre[i] + normals[i] * offsets[i] for i in range(len(centre)))
    return Line(
        offsets=tuple(offsets), points=points, curvature=curvature_of(points)
    )


def _sides(curvature: tuple[float, ...], step: float) -> tuple[float, ...]:
    """Which way each sample turns, from -1 (right) to +1 (left).

    Two passes of smoothing, and both are needed for different reasons.  The
    first is over the curvature, so that a corner that wobbles either side of
    straight is one corner rather than three.  The second is over the answer,
    so that where the road really does change hands -- an esse, a chicane --
    the inside of the road crosses over gradually instead of jumping the width
    of the circuit between two samples four metres apart.

    That second pass is the whole reason this returns a float.  A jump would be
    a kink, a kink is a radius, and the physics downstream would dutifully
    charge a defending car for a corner that only exists because of how this
    function rounded.
    """
    count = len(curvature)
    reach = max(1, int(SIDE_SMOOTH_M / step))
    smoothed = [
        sum(curvature[(index + shift) % count] for shift in range(-reach, reach + 1))
        / (2 * reach + 1)
        for index in range(count)
    ]

    # Hard answer first: which side, carrying the last real corner through the
    # straights, because a straight belongs to the corner it leads into.
    hard = [0.0] * count
    last = 0.0
    for index in range(count):
        if abs(smoothed[index]) > STRAIGHT:
            last = 1.0 if smoothed[index] > 0.0 else -1.0
        hard[index] = last
    if last == 0.0:
        return tuple(1.0 for _ in hard)
    for index in range(count):
        if hard[index] != 0.0:
            break
        hard[index] = last

    # Then take the corners off it.
    blur = max(1, int(SIDE_SMOOTH_M / (2.0 * step)))
    return tuple(
        sum(hard[(index + shift) % count] for shift in range(-blur, blur + 1))
        / (2 * blur + 1)
        for index in range(count)
    )


def _normals(headings: tuple[float, ...]) -> tuple[Vec2, ...]:
    return tuple(
        Vec2(math.cos(heading), math.sin(heading)).left for heading in headings
    )


def _place(
    centre: tuple[Vec2, ...], headings: tuple[float, ...], index: int, offset: float
) -> Vec2:
    heading = headings[index]
    return centre[index] + Vec2(math.cos(heading), math.sin(heading)).left * offset
