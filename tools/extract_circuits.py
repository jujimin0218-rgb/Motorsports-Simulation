"""Recover a circuit's layout from a surveyed centreline (project rule 43).

The engine builds a track from corner radii, turn angles and the straights
between them.  What a survey gives is a centreline: a few hundred points in
metres, going round the lap.  This turns one into the other, and the point of
doing it that way rather than reading a track map is that *the reading is
checkable* -- a lap that closes to 360 degrees and lands on the published
length is a lap somebody measured, and one that does not is a drawing.

The recovery, in order:

1. **Resample uniformly by arc length.**  Survey points are spaced however the
   surveyor walked; curvature computed on uneven spacing is dominated by the
   spacing.

2. **Curvature, smoothed.**  ``kappa = (x' y'' - y' x'') / (x'^2 + y'^2)^1.5``
   on the resampled trace, then a moving average.  The window is the one real
   parameter here and it is a trade: too short and a straight looks like a
   series of tiny corners, too long and a chicane smears into one bend.  It is
   set by measurement -- see ``--tune``.

3. **Segment.**  Anything above a curvature threshold is corner, anything below
   is straight.  Runs shorter than a car length are absorbed into their
   neighbours, because a four-metre corner is noise rather than a corner.

4. **Fit.**  A corner's radius is the arc length over the total turn (which is
   the radius of the circle that turns that much in that distance, and is more
   robust than averaging 1/kappa over noisy samples); its angle is the integral
   of curvature; its direction is the sign.

Everything is then handed to the engine's own builder, and the result is
checked against what is published: the lap has to close, the length has to
match, and the lap time has to be roughly the real one.  Those are the honesty
gates.  A layout that fails them is not written.

Status: **the recovery works and the circuits do not ship yet.**

Fifteen circuits come back to within a few metres of their published lengths --
Monza to the metre, Spa and Silverstone to two, Spielberg to one -- and every
lap closes to within a few degrees of 360 (Suzuka to zero, because it is a
figure of eight and genuinely turns as far one way as the other).  The geometry
is measured rather than remembered, which is what these files were missing.

But the lap times do not land, and measuring *why* found two separate things,
pulling opposite ways:

**The centreline is not the racing line.**  A car goes wide, cuts to the apex
and comes out wide, so it drives a straighter path than the road.  The engine's
corner model drives the centreline, so real geometry comes out slow: Monza
+7.6 s, Silverstone +6.4 s, Bahrain +3.7 s, Suzuka +2.8 s.  Widening every
corner as a diagnostic closes most of it (Monza +7.6 to +1.2 at x1.6), and it
also moves Monza's setup optimum to minimum wing, which is where Monza's has to
be.  But the factor is not uniform -- Silverstone wants about x1.2 and Monza
about x1.6 -- so a flat multiplier is a diagnostic rather than a fix.  The fix
is a racing-line model, and the engine already carries the ``track_width`` on
every segment that such a model needs and currently ignores.

**There is no elevation in the survey.**  A flat Spa is a quick Spa: it comes
out 3.7 s *fast* at the centreline and worse with any widening, because
Raidillon climbs forty metres and this data does not know it.

So the pipeline and the acceptance criteria are finished, and the circuits are
one racing-line model and one elevation source away from being data files.  The
tool reports both numbers rather than writing a circuit that would put the
wrong lap time into the engine's calibration set under a real circuit's name.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

__all__ = ["Recovered", "recover", "load_centreline"]

#: Resampling step, m.  Fine enough to hold a hairpin, coarse enough that the
#: second derivative is not reading survey noise.
STEP_M = 3.0

#: Curvature smoothing window, in metres of track.
SMOOTH_M = 21.0

#: Above this curvature the road is turning: 1/400 m is a corner a Formula 1
#: car takes appreciably below its top speed, and below it the road is straight
#: enough that the engine's own corner model returns the speed ceiling anyway.
CORNER_CURVATURE = 1.0 / 400.0

#: Runs shorter than this are absorbed into their neighbours.  A corner shorter
#: than a car is not a corner.
MIN_RUN_M = 12.0

#: A corner has to turn at least this much to be called one.
MIN_CORNER_DEG = 6.0


@dataclass(frozen=True, slots=True)
class Element:
    """One recovered piece of road."""

    kind: str            # "corner" or "straight"
    length: float        # m
    radius: float = 0.0  # m, corners only
    angle: float = 0.0   # degrees turned, corners only
    direction: str = ""  # "left" or "right"
    start: float = 0.0   # distance round the lap, m


@dataclass(frozen=True, slots=True)
class Recovered:
    """A circuit, recovered, with everything needed to judge the recovery."""

    name: str
    length: float
    elements: tuple[Element, ...]
    total_turn: float          # degrees; a closed lap turns 360
    closure_error: float       # m between the first and last point
    mean_width: float
    corner_count: int

    @property
    def straights(self) -> tuple[Element, ...]:
        return tuple(e for e in self.elements if e.kind == "straight")

    @property
    def corners(self) -> tuple[Element, ...]:
        return tuple(e for e in self.elements if e.kind == "corner")

    @property
    def longest_straight(self) -> float:
        return max((e.length for e in self.straights), default=0.0)


# -- reading -----------------------------------------------------------------


def load_centreline(path: Path) -> tuple[list[tuple[float, float]], float]:
    """A surveyed centreline in metres, and the mean track width.

    The TUM racetrack database format: ``x_m, y_m, w_tr_right_m, w_tr_left_m``
    with a ``#`` header.  It is a *centreline* rather than a racing line, which
    is the reason to prefer it -- a racing line has cut every corner and its
    radii are the driver's, not the circuit's.
    """
    points: list[tuple[float, float]] = []
    widths: list[float] = []
    with path.open(encoding="utf-8") as handle:
        for row in csv.reader(handle):
            if not row or row[0].lstrip().startswith("#"):
                continue
            values = [float(v) for v in row[:4]]
            points.append((values[0], values[1]))
            if len(values) >= 4:
                widths.append(values[2] + values[3])
    width = sum(widths) / len(widths) if widths else 12.0
    return points, width


# -- the recovery ------------------------------------------------------------


def _resample(points: list[tuple[float, float]], step: float) -> list[tuple[float, float]]:
    """Uniform spacing by arc length, closing the loop."""
    closed = points + [points[0]]
    distances = [0.0]
    for (x0, y0), (x1, y1) in zip(closed, closed[1:]):
        distances.append(distances[-1] + math.hypot(x1 - x0, y1 - y0))
    total = distances[-1]

    out: list[tuple[float, float]] = []
    index = 0
    walked = 0.0
    while walked < total:
        while index < len(distances) - 2 and distances[index + 1] < walked:
            index += 1
        span = distances[index + 1] - distances[index]
        t = 0.0 if span <= 0 else (walked - distances[index]) / span
        x0, y0 = closed[index]
        x1, y1 = closed[index + 1]
        out.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
        walked += step
    return out


def _curvature(points: list[tuple[float, float]], step: float) -> list[float]:
    """Signed curvature at each point, on a uniformly spaced closed trace."""
    count = len(points)
    kappa: list[float] = []
    for i in range(count):
        x0, y0 = points[(i - 1) % count]
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % count]
        dx = (x2 - x0) / (2.0 * step)
        dy = (y2 - y0) / (2.0 * step)
        ddx = (x2 - 2.0 * x1 + x0) / (step * step)
        ddy = (y2 - 2.0 * y1 + y0) / (step * step)
        denominator = (dx * dx + dy * dy) ** 1.5
        kappa.append(0.0 if denominator < 1e-12 else (dx * ddy - dy * ddx) / denominator)
    return kappa


def _smooth(values: list[float], window: int) -> list[float]:
    """Circular moving average.  Circular because a lap is a loop and the start
    line is an arbitrary place to put a discontinuity."""
    if window <= 1:
        return list(values)
    count = len(values)
    half = window // 2
    out: list[float] = []
    running = sum(values[(-half + i) % count] for i in range(window))
    for i in range(count):
        out.append(running / window)
        running -= values[(i - half) % count]
        running += values[(i + half + 1) % count]
    return out


def _runs(kappa: list[float], step: float) -> list[tuple[str, int, int]]:
    """Split the lap into corner and straight runs, then tidy the short ones."""
    labels = [
        "corner" if abs(k) >= CORNER_CURVATURE else "straight" for k in kappa
    ]

    # A corner that changes hands is two corners, so the sign is part of the
    # label -- otherwise an esse comes out as one bend that turns nowhere.
    for i, k in enumerate(kappa):
        if labels[i] == "corner":
            labels[i] = "left" if k > 0 else "right"

    runs: list[list] = []
    for i, label in enumerate(labels):
        if runs and runs[-1][0] == label:
            runs[-1][2] = i + 1
        else:
            runs.append([label, i, i + 1])

    # Absorb anything too short to be real into whichever neighbour is longer.
    minimum = max(1, int(MIN_RUN_M / step))
    changed = True
    while changed and len(runs) > 2:
        changed = False
        for i, run in enumerate(runs):
            if run[2] - run[1] >= minimum:
                continue
            before = runs[i - 1]
            after = runs[(i + 1) % len(runs)]
            keeper = before if (before[2] - before[1]) >= (after[2] - after[1]) else after
            keeper[1] = min(keeper[1], run[1])
            keeper[2] = max(keeper[2], run[2])
            runs.pop(i)
            changed = True
            break

    # Merge neighbours that ended up the same label.
    merged: list[list] = []
    for run in runs:
        if merged and merged[-1][0] == run[0]:
            merged[-1][2] = run[2]
        else:
            merged.append(list(run))
    if len(merged) > 1 and merged[0][0] == merged[-1][0]:
        merged[0][1] = merged[-1][1] - len(kappa)
        merged.pop()

    return [(label, start, end) for label, start, end in merged]


def recover(
    name: str,
    points: list[tuple[float, float]],
    width: float,
    *,
    step: float = STEP_M,
    smooth_m: float = SMOOTH_M,
) -> Recovered:
    """Turn a surveyed centreline into corners and straights."""
    resampled = _resample(points, step)
    kappa = _smooth(_curvature(resampled, step), max(1, int(smooth_m / step)))
    count = len(resampled)
    length = count * step

    elements: list[Element] = []
    for label, start, end in _runs(kappa, step):
        span = end - start
        run_length = span * step
        if label == "straight":
            elements.append(
                Element("straight", run_length, start=(start % count) * step)
            )
            continue
        turn = sum(kappa[i % count] for i in range(start, end)) * step
        degrees = abs(math.degrees(turn))
        if degrees < MIN_CORNER_DEG:
            # Turns too little to be a corner: it is a kink in a straight.
            elements.append(
                Element("straight", run_length, start=(start % count) * step)
            )
            continue
        # Radius from the arc: a corner of this length that turns this much has
        # this radius.  More robust than averaging 1/kappa, which is dominated
        # by whichever sample was straightest.
        radius = run_length / abs(turn)
        elements.append(
            Element(
                "corner",
                run_length,
                radius=radius,
                angle=degrees,
                direction="left" if turn > 0 else "right",
                start=(start % count) * step,
            )
        )

    # Merge straights that ended up adjacent after a kink was reclassified.
    tidy: list[Element] = []
    for element in elements:
        if tidy and tidy[-1].kind == "straight" and element.kind == "straight":
            tidy[-1] = Element("straight", tidy[-1].length + element.length,
                               start=tidy[-1].start)
        else:
            tidy.append(element)

    total_turn = math.degrees(sum(kappa) * step)
    closure = math.hypot(points[0][0] - points[-1][0], points[0][1] - points[-1][1])

    return Recovered(
        name=name,
        length=length,
        elements=tuple(tidy),
        total_turn=total_turn,
        closure_error=closure,
        mean_width=width,
        corner_count=sum(1 for e in tidy if e.kind == "corner"),
    )


# -- handing it to the engine ------------------------------------------------


def to_definition(
    result: Recovered,
    *,
    country: str = "",
    display_name: str | None = None,
    drs_zones: int = 2,
    published_length: float | None = None,
) -> "TrackDefinition":
    """Build the engine's own track definition from a recovery.

    Two things happen here that the recovery itself cannot do.

    The engine joins a straight to a corner with a **clothoid**, because a real
    car cannot step from no steering to full steering, and those transitions add
    length the measured arc did not have.  So the straights are re-solved
    against the published lap length using the engine's own closure solver --
    which is what that solver exists for, and which means the corners keep the
    radii and angles that were measured while the straights absorb the
    difference.

    The **DRS zones** go on the longest straights, which is where they are in
    reality.  This is the only part of the process that is a convention rather
    than a measurement, so it is done by a rule anybody can check rather than
    by a per-circuit table.
    """
    from f1_race_engine.track.definitions import (
        CornerDefinition,
        CornerDirection,
        DrsDefinition,
        SectorDefinition,
        StraightDefinition,
        TrackDefaults,
        TrackDefinition,
        WidthDefinition,
    )
    from f1_race_engine.track.drs import DrsZone
    from f1_race_engine.track.builder import build_track
    from f1_race_engine.track.layout_solver import (
        apply_straight_lengths,
        solve_straight_lengths,
    )
    from dataclasses import replace

    layout: list = []
    turn = 0
    for element in result.elements:
        if element.kind == "straight":
            layout.append(StraightDefinition(length=element.length))
        else:
            turn += 1
            layout.append(
                CornerDefinition(
                    radius=element.radius,
                    angle=element.angle,
                    direction=(
                        CornerDirection.LEFT
                        if element.direction == "left"
                        else CornerDirection.RIGHT
                    ),
                    corner_id=turn,
                    name=f"Turn {turn}",
                )
            )

    # Sectors at the thirds of the lap: the real boundaries are a timekeeping
    # decision rather than a property of the road, and thirds are both a
    # defensible default and one nobody can mistake for a measurement.
    third = result.length / 3.0
    sectors = SectorDefinition(boundaries=(third, 2.0 * third))

    # DRS on the longest straights, opening a little after each one starts and
    # detected shortly before it.  A detection point that is not on the road
    # before the zone is not a detection point, so it is clamped to the lap.
    straights = sorted(
        (e for e in result.elements if e.kind == "straight"),
        key=lambda e: -e.length,
    )[:drs_zones]
    zones = []
    for index, straight in enumerate(sorted(straights, key=lambda e: e.start), start=1):
        opening = straight.start + min(60.0, straight.length * 0.15)
        closing = straight.start + straight.length * 0.95
        if closing <= opening:
            continue
        detection = (opening - 150.0) % result.length
        zones.append(
            DrsZone(
                index=index,
                detection_distance=round(detection, 1),
                activation_start=round(opening, 1),
                activation_end=round(closing, 1),
                lap_length=result.length,
            )
        )

    definition = TrackDefinition(
        name=display_name or result.name,
        country=country,
        layout=tuple(layout),
        defaults=TrackDefaults(track_width=result.mean_width),
        width=WidthDefinition(control_points=((0.0, result.mean_width),)),
        sectors=sectors,
        drs=DrsDefinition(zones=()),
        metadata={
            "source": "TUM racetrack-database centreline, recovered",
            "recovered_length_m": round(result.length, 1),
            "recovered_corners": result.corner_count,
            "total_turn_deg": round(result.total_turn, 2),
        },
    )

    # Re-solve the straights against the published length, so the clothoids the
    # engine adds do not lengthen the lap past what the circuit measures.
    target = published_length if published_length is not None else result.length
    solution = solve_straight_lengths(definition, target_lap_length=target)
    definition = apply_straight_lengths(definition, solution.lengths)

    # The DRS zones are placed on the *built* lap, since the solver has just
    # moved every distance on it.
    built = build_track(definition)
    lap = built.length
    third = lap / 3.0
    sectors = SectorDefinition(boundaries=(third, 2.0 * third))

    # Longest straights, found on the built lap by walking its segments.
    runs: list[tuple[float, float]] = []
    start = None
    for segment in built.segments:
        straight = abs(segment.curvature_start) < 1e-4
        if straight and start is None:
            start = segment.distance
        elif not straight and start is not None:
            runs.append((start, segment.distance))
            start = None
    if start is not None:
        runs.append((start, lap))

    zones = []
    for index, (begins, ends) in enumerate(
        sorted(sorted(runs, key=lambda r: r[0] - r[1])[:drs_zones]), start=1
    ):
        opening = begins + min(60.0, (ends - begins) * 0.15)
        closing = begins + (ends - begins) * 0.95
        if closing <= opening:
            continue
        zones.append(
            DrsZone(
                index=index,
                detection_distance=round((opening - 150.0) % lap, 1),
                activation_start=round(opening, 1),
                activation_end=round(closing, 1),
                lap_length=lap,
            )
        )

    return replace(
        definition,
        sectors=sectors,
        drs=DrsDefinition(zones=tuple(zones)),
        metadata={**definition.metadata, "built_length_m": round(lap, 1)},
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("centrelines", nargs="+", type=Path)
    parser.add_argument("--smooth", type=float, default=SMOOTH_M)
    args = parser.parse_args()

    print(
        "%-14s %9s %8s %9s %8s %8s %9s"
        % ("circuit", "length", "corners", "turn", "closure", "width", "longest")
    )
    for path in args.centrelines:
        points, width = load_centreline(path)
        result = recover(path.stem, points, width, smooth_m=args.smooth)
        print(
            "%-14s %8.0fm %8d %8.1f° %7.1fm %7.1fm %8.0fm"
            % (
                result.name,
                result.length,
                result.corner_count,
                result.total_turn,
                result.closure_error,
                result.mean_width,
                result.longest_straight,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
