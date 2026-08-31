"""A circuit as a place, not as a distance.

The engine's track model answers "what is the road like ``s`` metres round the
lap".  That is what the physics needs and all it needs.  A car that can be
somewhere -- beside another car, on the kerb, in the gravel, against a wall --
needs the other half: where those metres are, and what is either side of them.

So this takes the distance model and lays it out.  The centreline and its width
come straight off the engine; everything outside the white line -- the kerb, the
run-off, the grass, the gravel, the barrier -- is generated here, because the
engine has no opinion about it.  Nothing generated here feeds back into a lap
time.

**Where the numbers come from.**  Widths, kerbs, corners and the pit lane's
entry and exit are the engine's.  How far the run-off extends and what is in it
is a convention stated in the constants below: a corner gets a deeper run-off
than a straight and gravel beyond the tarmac, a straight gets a verge and a
wall closer in.  It is a plausible circuit rather than a surveyed one, and it
is the same every time it is built.
"""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

from .geometry import Vec2, closest_point_on_segment, project_polyline
from .space import SampleGrid

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..track.model import Track

__all__ = ["Surface", "SurfaceBand", "Barrier", "TrackWorld", "build_world"]


#: How finely the world is laid out, m.  Fine enough that a car two metres wide
#: is never between two samples on a corner, coarse enough that a five
#: kilometre lap is a few thousand points rather than a hundred thousand.
STEP_M = 4.0

#: Metres of kerb outside the white line, where there is a kerb at all.
KERB_M = 1.2

#: Metres of run-off outside the kerb, on a straight and at a corner.
RUNOFF_STRAIGHT_M = 6.0
RUNOFF_CORNER_M = 18.0

#: Where the gravel starts inside a corner's run-off, as a fraction of it.
GRAVEL_FROM = 0.45

#: A corner is anywhere the road bends tighter than this radius, m.
CORNER_RADIUS_M = 400.0

#: How far either side of a corner its run-off reaches, m.  The braking zone
#: before it and the exit after are part of the same piece of circuit.
RUNOFF_REACH_M = 60.0

#: Over how many metres the run-off depth is blended, so a wall moves rather
#: than jumps.
SMOOTH_M = 40.0


class Surface(str, Enum):
    """What is under a car at a point on the plane.

    Only the first is the road.  The rest is what a car finds when it leaves
    it, in the order it finds them.
    """

    TRACK = "track"
    KERB = "kerb"
    RUNOFF = "runoff"
    GRAVEL = "gravel"
    GRASS = "grass"
    PIT = "pit"
    BARRIER = "barrier"

    @property
    def grip(self) -> float:
        """Roughly what a car can use here, as a fraction of the road's.

        A convention of this layer, not a measurement: the engine prices grip
        on the road and has never been asked about anything else.
        """
        return {
            Surface.TRACK: 1.0,
            Surface.KERB: 0.85,
            Surface.PIT: 1.0,
            Surface.RUNOFF: 0.7,
            Surface.GRASS: 0.35,
            Surface.GRAVEL: 0.25,
            Surface.BARRIER: 0.0,
        }[self]


@dataclass(frozen=True, slots=True)
class SurfaceBand:
    """A strip of one surface running alongside the road.

    ``inner`` and ``outer`` are metres from the centreline, signed: negative is
    to the right, positive to the left.  A band is drawn as the quad between
    the two offsets over the span it covers.
    """

    surface: Surface
    inner: tuple[float, ...]
    outer: tuple[float, ...]

    def polygon(self, centre: tuple[Vec2, ...]) -> tuple[Vec2, ...]:
        """The band as one closed ring round the whole lap."""
        near = project_polyline(centre, self.inner)
        far = project_polyline(centre, self.outer)
        return near + tuple(reversed(far))

    def rings(self, centre: tuple[Vec2, ...], *, least: float = 0.05) -> list[tuple[Vec2, ...]]:
        """The band as the pieces of it that actually have width.

        A gravel trap exists at the corners and nowhere else, and grass exists
        everywhere the gravel does not.  Carried as one ring round the lap each
        would be mostly a line of zero width -- points that draw nothing and
        cost as much to send as the ones that do.
        """
        near = project_polyline(centre, self.inner)
        far = project_polyline(centre, self.outer)
        out: list[tuple[Vec2, ...]] = []
        run: list[int] = []
        count = len(centre)
        for index in range(count + 1):
            at = index % count
            wide = abs(self.outer[at] - self.inner[at]) > least
            if wide and index < count:
                run.append(at)
                continue
            if len(run) > 1:
                out.append(
                    tuple(near[i] for i in run) + tuple(far[i] for i in reversed(run))
                )
            run = []
        return out


@dataclass(frozen=True, slots=True)
class Barrier:
    """A wall.  A car that reaches one stops going that way.

    Carries an index of its own segments: a lap's wall is over a thousand of
    them and it is asked "am I near you" once per car per pass, so walking all
    of them is the difference between a world that steps in a millisecond and
    one that takes half a second.
    """

    points: tuple[Vec2, ...]
    grid: SampleGrid

    @classmethod
    def of(cls, points: tuple[Vec2, ...], *, cell: float) -> Barrier:
        return cls(points=points, grid=SampleGrid.of(points, cell=cell))

    def segments_near(self, point: Vec2) -> tuple[int, ...]:
        """Segment indices that could be the nearest to a point."""
        near = {index for index in self.grid.near(point, rings=1)}
        last = len(self.points) - 2
        return tuple(
            sorted({min(max(index - 1, 0), last) for index in near} | {min(max(index, 0), last) for index in near})
        )

    def nearest(self, point: Vec2) -> tuple[Vec2, float]:
        """The closest point on the wall, and how far away it is."""
        candidates = self.segments_near(point)
        if not candidates:
            candidates = tuple(range(len(self.points) - 1))
        best = self.points[candidates[0]]
        best_distance = (point - best).length_squared
        for index in candidates:
            candidate = closest_point_on_segment(
                point, self.points[index], self.points[index + 1]
            )
            distance = (point - candidate).length_squared
            if distance < best_distance:
                best = candidate
                best_distance = distance
        return best, math.sqrt(best_distance)


@dataclass(frozen=True, slots=True)
class TrackWorld:
    """A circuit laid out on the plane."""

    name: str
    length: float
    step: float
    centre: tuple[Vec2, ...]
    """The road's centreline, every ``step`` metres, start line first."""

    headings: tuple[float, ...]
    half_width: tuple[float, ...]
    """Half the road, m, at each sample -- the white line either side."""

    kerb_width: tuple[float, ...]
    """Kerb outside the white line, m.  Zero where the bands drew none, so
    what the world says is under a car is what the picture shows."""

    bands: tuple[SurfaceBand, ...]
    barriers: tuple[Barrier, ...]
    pit_path: tuple[Vec2, ...]
    corners: tuple[bool, ...]
    """Whether each sample is inside a corner, which is what widens the run-off."""

    grid: "SampleGrid"
    """Where the samples are, so finding the nearest is not a lap-long scan."""

    def sample_of(self, distance: float) -> int:
        """Which sample a lap distance falls on."""
        wrapped = distance % self.length
        return min(int(wrapped / self.step), len(self.centre) - 1)

    def place(self, distance: float, offset: float = 0.0) -> tuple[Vec2, float]:
        """Where a car at ``distance`` and ``offset`` is, and which way it faces.

        The two coordinates the race actually carries turned into a place on
        the plane.  This is the only door between the distance model and the
        world, and it goes one way.
        """
        wrapped = distance % self.length
        exact = wrapped / self.step
        index = int(exact)
        nudge = exact - index
        count = len(self.centre)
        here = self.centre[index % count]
        there = self.centre[(index + 1) % count]
        along = (there - here)
        point = here + along * nudge
        heading = self.headings[index % count]
        across = Vec2(math.cos(heading), math.sin(heading)).left
        return point + across * offset, heading

    def surface_at(self, point: Vec2) -> Surface:
        """What is under a point on the plane.

        Answered by how far the point is from the centreline, because that is
        what every band is defined in terms of.  Linear in the samples nearby
        rather than in all of them: a car is somewhere, and the world knows
        roughly where from the last time it asked.
        """
        index, across = self._nearest(point)
        half = self.half_width[index]
        distance = abs(across)
        if distance <= half:
            return Surface.TRACK
        edge = distance - half
        kerb = self.kerb_width[index]
        if edge <= kerb:
            return Surface.KERB
        depth = RUNOFF_CORNER_M if self.corners[index] else RUNOFF_STRAIGHT_M
        if edge <= kerb + depth:
            if not self.corners[index]:
                return Surface.GRASS
            return (
                Surface.GRAVEL
                if edge >= kerb + depth * GRAVEL_FROM
                else Surface.RUNOFF
            )
        return Surface.BARRIER

    def _nearest(self, point: Vec2) -> tuple[int, float]:
        """The sample nearest a point, and how far the point is across from it.

        Through the grid rather than over every sample: a lap is a thousand
        points and this is asked once per car per step, which over a race is
        the difference between a world that runs and one that does not.
        """
        best = -1
        best_distance = float("inf")
        for index in self.grid.near(point, rings=2):
            distance = (point - self.centre[index]).length_squared
            if distance < best_distance:
                best = index
                best_distance = distance
        if best < 0:  # nowhere near the circuit at all
            best = 0
            for index, centre in enumerate(self.centre):
                distance = (point - centre).length_squared
                if distance < best_distance:
                    best = index
                    best_distance = distance
        heading = self.headings[best]
        across = Vec2(math.cos(heading), math.sin(heading)).left
        return best, (point - self.centre[best]).dot(across)

    def to_dict(self) -> dict[str, Any]:
        """The world as something a renderer can draw without knowing any of it."""
        return {
            "name": self.name,
            "length": round(self.length, 2),
            "step": self.step,
            "centre": [[round(p.x, 2), round(p.y, 2)] for p in self.centre],
            "half_width": [round(w, 2) for w in self.half_width],
            "bands": [
                {
                    "surface": band.surface.value,
                    "polygon": [[round(p.x, 2), round(p.y, 2)] for p in ring],
                }
                for band in self.bands
                for ring in band.rings(self.centre)
            ],
            "barriers": [
                [[round(p.x, 2), round(p.y, 2)] for p in wall.points]
                for wall in self.barriers
            ],
            "pit_path": [[round(p.x, 2), round(p.y, 2)] for p in self.pit_path],
            "bounds": self._bounds(),
        }

    def _bounds(self) -> list[float]:
        xs = [p.x for p in self.centre]
        ys = [p.y for p in self.centre]
        reach = max(self.half_width) + KERB_M + RUNOFF_CORNER_M + 4.0
        return [
            round(min(xs) - reach, 2),
            round(min(ys) - reach, 2),
            round(max(xs) + reach, 2),
            round(max(ys) + reach, 2),
        ]


def build_world(track: Track, *, step: float = STEP_M) -> TrackWorld:
    """Lay a circuit out on the plane.

    Reads the engine's own track model and nothing else, so a world is a
    projection of the circuit that is being raced rather than a second circuit
    that has to be kept in step with it.
    """
    count = max(8, int(track.length / step))
    step = track.length / count

    # The engine projects a point per *segment*, and a segment is longer than a
    # world sample -- so reading x and y straight off gives runs of identical
    # points, and a polyline that stands still has no direction to be offset
    # along.  Walking between the segments' own points instead keeps the
    # centreline moving, which is what every edge and wall is generated from.
    anchors = [Vec2(seg.x, seg.y) for seg in track.segments]
    starts = [seg.distance for seg in track.segments]

    def centre_at(distance: float) -> Vec2:
        wrapped = distance % track.length
        index = bisect.bisect_right(starts, wrapped) - 1
        index = max(0, min(index, len(anchors) - 1))
        here = anchors[index]
        there = anchors[(index + 1) % len(anchors)]
        span = (
            starts[index + 1] - starts[index]
            if index + 1 < len(starts)
            else track.length - starts[index]
        )
        if span <= 0.0:
            return here
        along = (wrapped - starts[index]) / span
        return here + (there - here) * along

    centre: list[Vec2] = []
    headings: list[float] = []
    half: list[float] = []
    corner: list[bool] = []
    for index in range(count):
        at = index * step
        state = track.state_at(at)
        centre.append(centre_at(at))
        headings.append(state.heading)
        half.append(state.track_width * 0.5)
        corner.append(abs(state.radius) < CORNER_RADIUS_M)

    # A corner's run-off does not start at the apex and stop again four metres
    # later: it covers the braking zone before and the exit after.  Without
    # spreading it, the classification flips between neighbouring samples and
    # the wall lurches twelve metres sideways in the space of a car length.
    corner = _spread(corner, int(RUNOFF_REACH_M / step))

    # A kerb where a car might actually use one, which is a corner.
    kerbed = [KERB_M if corner[index] else 0.0 for index in range(count)]
    runoff = _smooth(
        [RUNOFF_CORNER_M if corner[index] else RUNOFF_STRAIGHT_M for index in range(count)],
        int(SMOOTH_M / step),
    )

    bands: list[SurfaceBand] = []
    # The road itself, so a renderer fills what it is given in the order it
    # arrives rather than working out where the asphalt is a second time.
    bands.append(
        SurfaceBand(
            Surface.TRACK,
            tuple(-w for w in half),
            tuple(half),
        )
    )
    for side in (1.0, -1.0):
        white = tuple(side * w for w in half)
        kerb_out = tuple(side * (half[i] + kerbed[i]) for i in range(count))
        gravel_in = tuple(
            side * (half[i] + kerbed[i] + runoff[i] * GRAVEL_FROM) for i in range(count)
        )
        wall = tuple(side * (half[i] + kerbed[i] + runoff[i]) for i in range(count))
        bands.append(SurfaceBand(Surface.KERB, white, kerb_out))
        # A corner throws a car onto tarmac first and gravel after it; a
        # straight has grass, because nobody runs wide on a straight on purpose.
        bands.append(
            SurfaceBand(
                Surface.RUNOFF,
                kerb_out,
                tuple(
                    gravel_in[i] if corner[i] else kerb_out[i] for i in range(count)
                ),
            )
        )
        bands.append(
            SurfaceBand(
                Surface.GRAVEL,
                tuple(gravel_in[i] if corner[i] else kerb_out[i] for i in range(count)),
                tuple(wall[i] if corner[i] else kerb_out[i] for i in range(count)),
            )
        )
        bands.append(
            SurfaceBand(
                Surface.GRASS,
                tuple(kerb_out[i] if corner[i] else kerb_out[i] for i in range(count)),
                tuple(kerb_out[i] if corner[i] else wall[i] for i in range(count)),
            )
        )

    frozen_centre = tuple(centre)
    barriers = tuple(
        Barrier.of(
            project_polyline(
                frozen_centre,
                tuple(
                    side * (half[i] + kerbed[i] + runoff[i] + 1.0)
                    for i in range(count)
                ),
            )
            + (
                project_polyline(
                    frozen_centre,
                    tuple(
                        side * (half[i] + kerbed[i] + runoff[i] + 1.0)
                        for i in range(count)
                    ),
                )[0],
            ),
            cell=max(step * 4.0, 16.0),
        )
        for side in (1.0, -1.0)
    )

    return TrackWorld(
        name=track.name,
        length=track.length,
        step=step,
        centre=frozen_centre,
        headings=tuple(headings),
        half_width=tuple(half),
        kerb_width=tuple(kerbed),
        bands=tuple(bands),
        barriers=barriers,
        pit_path=_pit_path(track, frozen_centre, headings, half, step, count),
        corners=tuple(corner),
        # Cells a few car lengths across: big enough that a lookup touches a
        # handful of samples, small enough that it is not most of the lap.
        grid=SampleGrid.of(frozen_centre, cell=max(step * 4.0, 16.0)),
    )


def _spread(flags: list[bool], reach: int) -> list[bool]:
    """True wherever anything within ``reach`` samples is true."""
    if reach <= 0:
        return flags
    count = len(flags)
    return [
        any(flags[(index + offset) % count] for offset in range(-reach, reach + 1))
        for index in range(count)
    ]


def _smooth(values: list[float], window: int) -> list[float]:
    """A moving average round the lap, so a step becomes a slope."""
    if window <= 0:
        return values
    count = len(values)
    span = window * 2 + 1
    return [
        sum(values[(index + offset) % count] for offset in range(-window, window + 1))
        / span
        for index in range(count)
    ]


def _pit_path(
    track: Track,
    centre: tuple[Vec2, ...],
    headings: list[float],
    half: list[float],
    step: float,
    count: int,
) -> tuple[Vec2, ...]:
    """The pit lane, as a road beside the road.

    The engine models a pit lane as a length and a speed limit between two
    distances -- which is what a time loss needs and says nothing about where
    it is.  Here it is drawn where one is: alongside the circuit between those
    two distances, easing out from the road and back into it.
    """
    from ..race.pitlane import PitLane

    lane = PitLane.for_track(track.length)
    entry = lane.entry_distance
    exit_ = lane.exit_distance
    span = exit_ - entry if exit_ > entry else track.length - entry + exit_
    steps = max(8, int(span / step))
    points: list[Vec2] = []
    for index in range(steps + 1):
        at = (entry + span * index / steps) % track.length
        sample = min(int(at / step), count - 1)
        ease = math.sin(math.pi * index / steps)
        across = Vec2(math.cos(headings[sample]), math.sin(headings[sample])).left
        points.append(
            centre[sample] - across * (half[sample] + 3.0 + 9.0 * ease)
        )
    return tuple(points)
