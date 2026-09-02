"""The things beside the road that say which circuit this is.

None of this is raced on.  A grandstand is not collided with, a corner number
does not change a lap time, and nothing here is ever asked about by the
physics -- these are the furniture that makes a picture of a circuit read as a
circuit rather than as a grey loop.

**Where the numbers come from.**  Only the placement is invented; what is being
placed is the engine's.  Corners are numbered because the track model numbers
them, the sector lines are where the track model puts its sector boundaries,
the start line is its start line, and a grandstand goes where there is a long
enough piece of straight to build one beside -- which is where circuits put
them, and for the same reason.

Built once with the world and sent to the client as plain points, because
deciding where a grandstand goes is not something to redo sixty times a second.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .geometry import Vec2

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..track.model import Track

__all__ = ["Decor", "Grandstand", "build_decor"]

#: Shortest run of straight worth building a grandstand beside, m.
STAND_LEAST_M = 190.0

#: How far a stand sits beyond the barrier, and how deep it is, m.
STAND_GAP_M = 9.0
STAND_DEPTH_M = 26.0

#: Curvature at or below which the road counts as straight enough to build
#: alongside, 1/m -- an eight hundred metre radius.
STAND_STRAIGHT = 1.0 / 800.0

#: How many stands a circuit gets at most.  A circuit is mostly not a
#: grandstand, and a ring of them reads as a wall rather than as a crowd.
STAND_MOST = 6


@dataclass(frozen=True, slots=True)
class Grandstand:
    """A stand beside the road, as the quad it is drawn as."""

    corners: tuple[Vec2, Vec2, Vec2, Vec2]
    side: int
    """+1 if it is to the left of the road, -1 to the right."""

    rows: int
    """How many banks of seating to draw, purely so it does not read flat."""


@dataclass(frozen=True, slots=True)
class Decor:
    """Everything beside the road, ready to draw."""

    grandstands: tuple[Grandstand, ...]
    start_line: tuple[Vec2, Vec2] | None
    sector_lines: tuple[tuple[Vec2, Vec2], ...]
    corner_marks: tuple[tuple[Vec2, str], ...]
    """Where to write a corner's number, and what to write."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "grandstands": [
                {
                    "polygon": [[round(p.x, 2), round(p.y, 2)] for p in stand.corners],
                    "rows": stand.rows,
                }
                for stand in self.grandstands
            ],
            "start_line": (
                None
                if self.start_line is None
                else [[round(p.x, 2), round(p.y, 2)] for p in self.start_line]
            ),
            "sector_lines": [
                [[round(p.x, 2), round(p.y, 2)] for p in pair]
                for pair in self.sector_lines
            ],
            "corner_marks": [
                {"x": round(point.x, 2), "y": round(point.y, 2), "label": label}
                for point, label in self.corner_marks
            ],
        }


def build_decor(
    track: "Track",
    centre: tuple[Vec2, ...],
    headings: tuple[float, ...],
    half_width: tuple[float, ...],
    reach: tuple[float, ...],
    step: float,
) -> Decor:
    """Dress a laid-out circuit.

    ``reach`` is how far from the centreline the barrier is at each sample, so
    that a stand is built outside the wall rather than in the run-off.
    """
    count = len(centre)
    if count < 8:
        return Decor((), None, (), ())

    across = tuple(
        Vec2(math.cos(heading), math.sin(heading)).left for heading in headings
    )
    curvature = _curvature(centre)

    return Decor(
        grandstands=_stands(centre, across, reach, curvature, step),
        start_line=_across_road(centre, across, half_width, 0),
        sector_lines=_sectors(track, centre, across, half_width, step, count),
        corner_marks=_corners(track, centre, across, reach, step, count),
    )


# -- the pieces --------------------------------------------------------------


def _stands(
    centre: tuple[Vec2, ...],
    across: tuple[Vec2, ...],
    reach: tuple[float, ...],
    curvature: tuple[float, ...],
    step: float,
) -> tuple[Grandstand, ...]:
    """Build a stand beside every long enough straight, biggest first.

    Only along a straight, because that is the only place a run of road is
    both long enough to seat a crowd and far enough from where cars leave the
    circuit to put one.
    """
    count = len(centre)
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index in range(count):
        straight = abs(curvature[index]) <= STAND_STRAIGHT
        if straight and start is None:
            start = index
        elif not straight and start is not None:
            runs.append((start, index - 1))
            start = None
    if start is not None:
        runs.append((start, count - 1))

    long_enough = [
        run for run in runs if (run[1] - run[0]) * step >= STAND_LEAST_M
    ]
    long_enough.sort(key=lambda run: run[0] - run[1])  # longest first, stably

    stands: list[Grandstand] = []
    for first, last in long_enough[:STAND_MOST]:
        # Inset from the ends so a stand does not run into the corner at
        # either end of the straight it is beside.
        inset = max(1, int(30.0 / step))
        a, b = first + inset, last - inset
        if b - a < 2:
            continue
        # The outside of the road at a straight is a toss-up, so both sides get
        # one on the longest straights and the near side on the rest -- which
        # is what a circuit looks like from above.
        for side in (1, -1) if len(stands) < 2 else (1,):
            near = tuple(
                centre[index] + across[index] * (side * (reach[index] + STAND_GAP_M))
                for index in range(a, b + 1)
            )
            far = tuple(
                centre[index]
                + across[index]
                * (side * (reach[index] + STAND_GAP_M + STAND_DEPTH_M))
                for index in range(a, b + 1)
            )
            stands.append(
                Grandstand(
                    corners=(near[0], near[-1], far[-1], far[0]),
                    side=side,
                    rows=4,
                )
            )
    return tuple(stands)


def _across_road(
    centre: tuple[Vec2, ...],
    across: tuple[Vec2, ...],
    half_width: tuple[float, ...],
    index: int,
) -> tuple[Vec2, Vec2]:
    """A line painted right across the road at one sample."""
    edge = half_width[index]
    return (
        centre[index] + across[index] * edge,
        centre[index] - across[index] * edge,
    )


def _sectors(
    track: "Track",
    centre: tuple[Vec2, ...],
    across: tuple[Vec2, ...],
    half_width: tuple[float, ...],
    step: float,
    count: int,
) -> tuple[tuple[Vec2, Vec2], ...]:
    return tuple(
        _across_road(centre, across, half_width, min(int(at / step), count - 1))
        for at in track.sector_boundaries
    )


def _corners(
    track: "Track",
    centre: tuple[Vec2, ...],
    across: tuple[Vec2, ...],
    reach: tuple[float, ...],
    step: float,
    count: int,
) -> tuple[tuple[Vec2, str], ...]:
    """One number per corner, written on the inside of it.

    Placed at the corner's own middle rather than at its entry, and only once
    however many samples the corner covers.
    """
    seen: dict[int, list[int]] = {}
    for index in range(count):
        state = track.state_at(index * step)
        if state.corner_id is None:
            continue
        seen.setdefault(state.corner_id, []).append(index)

    marks: list[tuple[Vec2, str]] = []
    for corner_id in sorted(seen):
        samples = seen[corner_id]
        middle = samples[len(samples) // 2]
        # Just outside the barrier, on the outside of the bend, where a real
        # board goes and where it will not sit under the cars.
        marks.append(
            (
                centre[middle] + across[middle] * (reach[middle] + 4.0),
                str(corner_id),
            )
        )
    return tuple(marks)


def _curvature(points: tuple[Vec2, ...]) -> tuple[float, ...]:
    from .line import curvature_of

    return curvature_of(points)
