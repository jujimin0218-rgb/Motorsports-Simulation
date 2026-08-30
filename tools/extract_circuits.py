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
#:
#: This is the one real parameter in the recovery and it turned out to be the
#: dominant one, so it is set by measurement against real pole laps rather than
#: chosen.  Swept from 21 m to 110 m across five circuits whose pole times are
#: known, the lap time moves by more than fifteen seconds and passes through
#: the right answer at about forty-five:
#:
#: .. code-block:: text
#:
#:                21 m      45 m      75 m
#:     Bahrain    +3.74s    +0.65s    -4.51s
#:     Suzuka     +2.78s    -0.93s    -5.62s
#:     Monza      +7.59s    +3.06s    -4.68s
#:
#: And it is not really a filter setting.  Smoothing the road's curvature over
#: the length of a corner entry is, physically, *what a racing line is*: a car
#: does not follow the road's curvature point by point, it takes a path that
#: averages it out over the distance it can move sideways in.  Forty-five metres
#: is about how far a Formula 1 car travels while crossing the width of a
#: circuit, which is why this is the number and not some other one.
#:
#: The principled version is to solve for the line rather than approximate it
#: with a filter -- ``f1_race_engine.track.racing_line`` does that -- but it
#: does not yet beat this on tight narrow corners.  See ``docs/CIRCUITS.md``.
SMOOTH_M = 45.0

#: Above this curvature the road is turning: 1/400 m is a corner a Formula 1
#: car takes appreciably below its top speed, and below it the road is straight
#: enough that the engine's own corner model returns the speed ceiling anyway.
CORNER_CURVATURE = 1.0 / 400.0

#: Runs shorter than this are absorbed into their neighbours.  A corner shorter
#: than a car is not a corner.
MIN_RUN_M = 12.0

#: A corner has to turn at least this much to be called one.
#:
#: A run that turns less than this stays a straight -- but its turning does
#: *not* get thrown away, it is folded into the nearest real corner.  That
#: distinction is worth the trouble.  A lap is the sum of its turning, and
#: every degree discarded here has to be put back by the closure solver, which
#: does it by moving the corners that *were* measured: with the turning
#: discarded the definition came out twenty degrees short of its own trace, the
#: solver moved the real corners by a hundred degrees between them, and the lap
#: came out at fifteen kilometres.  Keeping every kink as a corner instead
#: fixes the turning and breaks something else -- there are no straights left
#: for the length solver to work with.  Folding is what does both.
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


#: Curvature smoothing for **telemetry**, in metres of track.
#:
#: Much shorter than :data:`SMOOTH_M`, and for a reason worth stating.  The 45 m
#: window on a survey is not really a filter -- it stands in for a racing line,
#: because a survey is the road and a car does not drive the road's curvature
#: point by point.  Telemetry is the opposite: it is one car's actual line, so
#: the averaging has already been done by the driver.  Smoothing it over 45 m
#: would apply the racing line twice.  Fifteen metres is enough to take out
#: positional noise and nothing else.
SMOOTH_TELEMETRY_M = 15.0

#: FastF1 reports car position in tenths of a metre.
FASTF1_POSITION_SCALE = 0.1


def load_fastf1(
    path: Path,
    *,
    scale: float = FASTF1_POSITION_SCALE,
    width: float = 12.0,
) -> tuple[list[tuple[float, float]], float, list[float]]:
    """A lap of FastF1 position telemetry: points in metres, width, elevation.

    Reads what ``lap.get_telemetry()`` or ``lap.get_pos_data()`` writes out as
    CSV -- ``X``, ``Y`` and, when the source has it, ``Z``.  Column names are
    matched case-insensitively and anything else in the file is ignored, so a
    full telemetry export works as well as a trimmed one.

    Three things differ from a survey, and all three matter.

    **It is a driven line, not the centreline.**  The driver has already cut
    every corner, so these radii are the line's and not the circuit's.  That is
    what :attr:`TrackDefaults.geometry` distinguishes, and it is why telemetry
    gets :data:`SMOOTH_TELEMETRY_M` rather than :data:`SMOOTH_M`.

    **It carries elevation.**  ``Z`` is the channel a survey does not have, and
    it is the missing input for Spa -- Raidillon climbs forty metres and a flat
    Spa is a fast Spa.  Returned as a third value, empty when absent.

    **It has no width.**  Nothing in the telemetry says how wide the road is,
    so ``width`` has to be told rather than measured.
    """
    columns: dict[str, int] = {}
    points: list[tuple[float, float]] = []
    elevation: list[float] = []
    with path.open(encoding="utf-8") as handle:
        for row in csv.reader(handle):
            if not row:
                continue
            if not columns:
                header = [cell.strip().lower() for cell in row]
                for wanted in ("x", "y", "z"):
                    if wanted in header:
                        columns[wanted] = header.index(wanted)
                if "x" not in columns or "y" not in columns:
                    raise ValueError(
                        f"{path.name}: expected X and Y columns, found {row}"
                    )
                continue
            try:
                x = float(row[columns["x"]]) * scale
                y = float(row[columns["y"]]) * scale
            except (ValueError, IndexError):
                continue  # a blank or partial row, of which exports have plenty
            points.append((x, y))
            if "z" in columns:
                try:
                    elevation.append(float(row[columns["z"]]) * scale)
                except (ValueError, IndexError):
                    elevation.append(elevation[-1] if elevation else 0.0)
    if len(points) < 100:
        raise ValueError(f"{path.name}: only {len(points)} usable points")
    return points, width, elevation


def elevation_control_points(
    elevation: list[float],
    lap_length: float,
    *,
    every: float = 100.0,
) -> tuple[tuple[float, float], ...]:
    """Thin a per-sample elevation trace down to control points for the engine.

    Sampled every hundred metres, which is fine enough for Eau Rouge and coarse
    enough not to turn GPS noise into a gradient.  The lap has to come back to
    its own height -- the engine checks that -- so any drift left by the sensor
    is taken out linearly round the lap rather than dumped at the join, which
    would put a step in the road where the timing line is.
    """
    if not elevation:
        return ()
    count = len(elevation)
    drift = elevation[-1] - elevation[0]
    levelled = [z - drift * i / (count - 1) for i, z in enumerate(elevation)]
    base = levelled[0]
    stride = max(1, int(round(count * every / lap_length)))
    points = [
        (round(i * lap_length / count, 1), round(levelled[i] - base, 2))
        for i in range(0, count, stride)
    ]
    # The last sample, always, and not only when the stride happens to miss the
    # end.  Levelling made it equal to the first, so ending on it closes the
    # lap's height exactly; stopping at whatever the stride reached instead
    # leaves the engine to interpolate the remainder, which puts a gradient in
    # the road that the circuit does not have.
    if points[-1][0] < lap_length - 1.0:
        points.append((round(lap_length - 0.1, 1), round(levelled[-1] - base, 2)))
    return tuple(points)


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
    stray = 0.0
    for label, start, end in _runs(kappa, step):
        span = end - start
        run_length = span * step
        turn = sum(kappa[i % count] for i in range(start, end)) * step
        degrees = abs(math.degrees(turn))

        if degrees < MIN_CORNER_DEG:
            # A straight, but not one that turns nowhere: the few degrees it
            # does swing are banked and given to the next real corner, so the
            # lap still turns as far as the survey says it does.
            stray += turn
            elements.append(
                Element("straight", run_length, start=(start % count) * step)
            )
            continue

        # Hand this corner whatever the kinks either side of it were carrying.
        turn += stray
        stray = 0.0
        degrees = abs(math.degrees(turn))
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

    # Enforce the threshold on the finished elements.  Absorbing short runs into
    # their neighbours can chain a straight onto a corner and leave a kilometre
    # of Monza's main straight labelled as a 5838-metre-radius bend -- which is
    # a straight, and which the lap-length solver then cannot shorten because it
    # is not allowed to touch corners.
    threshold_radius = 1.0 / CORNER_CURVATURE
    tidied: list[Element] = []
    for element in elements:
        if element.kind == "corner" and element.radius > threshold_radius:
            signed = math.radians(element.angle) * (
                1.0 if element.direction == "left" else -1.0
            )
            stray += signed
            tidied.append(Element("straight", element.length, start=element.start))
        else:
            tidied.append(element)
    elements = tidied

    # Give the banked turning back to the real corners, in proportion to how
    # much each already turns -- so a hairpin takes more of it than a kink, and
    # no single corner is bent out of shape by the correction.
    real = [e for e in elements if e.kind == "corner"]
    total_turn_of_real = sum(math.radians(e.angle) for e in real)
    if abs(stray) > 1e-9 and total_turn_of_real > 1e-9:
        for index, element in enumerate(elements):
            if element.kind != "corner":
                continue
            share = math.radians(element.angle) / total_turn_of_real
            signed = math.radians(element.angle) * (
                1.0 if element.direction == "left" else -1.0
            ) + stray * share
            if abs(signed) < 1e-9:
                continue
            elements[index] = Element(
                "corner",
                element.length,
                radius=element.length / abs(signed),
                angle=abs(math.degrees(signed)),
                direction="left" if signed > 0 else "right",
                start=element.start,
            )
        stray = 0.0

    if abs(stray) > 1e-9:
        for index in range(len(elements) - 1, -1, -1):
            element = elements[index]
            if element.kind != "corner":
                continue
            signed = math.radians(element.angle) * (
                1.0 if element.direction == "left" else -1.0
            )
            signed += stray
            elements[index] = Element(
                "corner",
                element.length,
                radius=element.length / max(abs(signed), 1e-9),
                angle=abs(math.degrees(signed)),
                direction="left" if signed > 0 else "right",
                start=element.start,
            )
            break

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
        apply_corner_angles,
        apply_straight_lengths,
        solve_corner_angles,
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
        defaults=TrackDefaults(
            track_width=result.mean_width,
            # The survey already contains the transitions.  A real corner eases
            # into its radius over a spiral and the curvature trace shows it
            # doing so, which is exactly what the recovery measured -- so the
            # builder must not add another one on top.  Left at the default,
            # it puts 0.55 x radius of clothoid either side of every corner,
            # which on a lap with a dozen large-radius sweepers is over a
            # kilometre of track that is not there: Monza came out at 7261 m
            # against its 5793.
            transition_factor=0.04,
            min_transition_length=2.0,
            max_transition_fraction=0.15,
        ),
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

    # Close the lap.  A closed lap turns through exactly a whole number of full
    # turns, and a curvature integral off a real survey lands a few degrees
    # away -- smoothing rounds the sharpest corners off, and what is rounded off
    # is turning.  How far the angles have to move to close is the honesty
    # number: a couple of degrees is a good reading and twenty is a drawing.
    # Signed, and zero is a real answer: Suzuka is a figure of eight and turns
    # as far one way as the other, so it closes at no net turns at all.  The
    # corners carry their own direction, so the sign here is the lap's.
    turns = round(result.total_turn / 360.0)
    moved = total_moved = 0.0
    if turns != 0:
        angles = solve_corner_angles(definition, turns=turns)
        definition = apply_corner_angles(definition, angles.angles)
        moved = max(
            (abs(a - b) for a, b in zip(angles.angles, angles.original_angles)),
            default=0.0,
        )
        total_moved = sum(
            abs(a - b) for a, b in zip(angles.angles, angles.original_angles)
        )
    else:
        # A figure of eight turns as far one way as the other and closes at no
        # net turns at all.  The angle solver cannot be asked for that: it
        # scales every corner by a single factor, and no factor except zero
        # takes a non-zero sum to zero.  So the leftover comes off the corners
        # directly, each giving up a share in proportion to its own size --
        # which at Suzuka is half a degree spread across twenty-one corners,
        # or about a hundredth of a degree each.
        corners = [e for e in definition.layout if isinstance(e, CornerDefinition)]
        signed = [
            e.angle * (1.0 if e.direction is CornerDirection.LEFT else -1.0)
            for e in corners
        ]
        residual = sum(signed)
        weight = sum(abs(a) for a in signed)
        if weight > 0.0 and residual != 0.0:
            corrected = [a - residual * abs(a) / weight for a in signed]
            # The correction is a fraction of a percent, so it cannot turn a
            # corner around; taking the magnitude back is safe because the
            # direction still lives on the element.
            angles_out = [abs(a) for a in corrected]
            deltas = [abs(a - e.angle) for a, e in zip(angles_out, corners)]
            moved = max(deltas, default=0.0)
            total_moved = sum(deltas)
            definition = apply_corner_angles(definition, angles_out)

    # Then the straights, against the published length, so the clothoids the
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
        metadata={
            **definition.metadata,
            "built_length_m": round(lap, 1),
            "closure_turns": turns,
            "angle_moved_deg": round(total_moved, 2),
            "worst_angle_moved_deg": round(moved, 2),
        },
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


def write_definition(definition, directory: Path, *, slug: str | None = None) -> Path:
    """Write a recovered circuit as an engine track file.

    Round-tripped before it is written: a file the engine cannot read back is
    not a track, and finding that out at load time rather than here would mean
    a broken circuit sitting in the data directory looking fine.
    """
    from f1_race_engine.track.io import definition_from_dict, definition_to_dict

    payload = definition_to_dict(definition)
    restored = definition_to_dict(definition_from_dict(payload))
    if restored != payload:
        raise ValueError(f"{definition.name}: does not survive a round trip")

    directory.mkdir(parents=True, exist_ok=True)
    name = slug or definition.name.lower().replace(" ", "_").replace("-", "_")
    path = directory / f"{name}.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path
