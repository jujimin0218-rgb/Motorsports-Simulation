# Real circuits

The engine's track files used to be invented.  They are now **measured**: a
surveyed centreline goes in, and corner radii, turn angles and straight lengths
come out, checked against what the circuit publishes.  Twenty-five circuits are
recovered this way; eleven of the season's twenty-two races run on them.

The point of recovering geometry rather than transcribing a track map is that
the reading is falsifiable.  A lap that closes and lands on the published
length is a lap somebody measured.  A lap that does not is a drawing.

## Where the data comes from

`data/tracks/survey/` holds twenty-five centrelines in the TUM format
(`x_m, y_m, w_tr_right_m, w_tr_left_m`), from the Technical University of
Munich's racetrack database — the same surveys their trajectory-optimisation
work uses.  `data/tracks/racelines/` holds eight of their optimised racelines,
which are not used to build anything; they are kept as an independent reference
to check the racing-line model against.

This was not the first source tried.  FastF1's telemetry, the Ergast and
Jolpica APIs and Overpass (OpenStreetMap) are all unreachable from here — the
network policy allows `raw.githubusercontent.com` and little else — so the
survey files, which live in a GitHub repository, are what there is.  That
constraint turned out not to matter much: a survey is a better input than
telemetry for this, because telemetry is one car's line on one lap and a survey
is the road.

## How a survey becomes a track file

`tools/extract_circuits.py`, in five steps.

1. **Resample by arc length** at 3 m.  Survey points are spaced however the
   surveyor walked, and curvature computed on uneven spacing mostly measures
   the spacing.

2. **Curvature, smoothed** over 45 m.  `κ = (x'y'' − y'x'')/(x'² + y'²)^1.5`,
   then a circular moving average.  This window is the one real parameter and
   it is set by measurement, not taste: swept from 21 m to 110 m across five
   circuits with known pole times, lap time moves more than fifteen seconds and
   passes through the right answer at about forty-five.  It is also not really
   a filter setting — smoothing curvature over the distance a car takes to
   cross the width of a circuit is, physically, an approximation to *what a
   racing line is*.

3. **Segment** into corners (above 1/400 m) and straights, absorbing runs
   shorter than a car length.

4. **Fit** each corner: radius is arc length over total turn, angle is the
   integral of curvature, direction is the sign.

5. **Close it** with the engine's own solvers — `solve_corner_angles` so the
   heading closes on a whole number of turns, then `solve_straight_lengths`
   against the published lap length, so the clothoid transitions the engine
   adds do not lengthen the lap past what the circuit measures.

Nothing here is per-circuit.  DRS zones go on the longest straights of the
built lap, sectors at its thirds — rules anybody can check rather than a table
only I can vouch for.

### Four things that had to be got right

**Small kinks must not be thrown away.**  A run turning less than six degrees
stays a straight, but its turning is *folded into the next real corner*.
Discarding it instead left the definition twenty degrees short of its own
trace, the closure solver put those degrees back by moving the corners that
*were* measured, and Montreal came out at fifteen kilometres.  Keeping every
kink as a corner fixes the turning and breaks the other end — there are no
straights left for the length solver.  Folding does both.

**The transitions are already in the survey.**  A real corner entry is in the
measured curvature, so the engine adding its own full clothoid on top
double-counts it.  These definitions carry `transition_factor=0.04`.

**A 5.8 km-radius "corner" is a straight.**  Monza's main straight has a
gentle drift that the segmenter classified as a corner, which cost the circuit
its defining feature.  A final pass reclassifies anything above the corner
threshold as straight and redistributes its turning across the real corners in
proportion to their size.  Monza's longest straight went from nothing to
1206 m, which is the number.

**A figure of eight turns nowhere.**  Suzuka crosses over itself, so it turns
as far one way as the other and closes at *zero* net turns.  Two things
rejected that.  The angle solver scales every corner by one factor and no
factor but zero takes a non-zero sum to zero, so the half-degree of leftover is
taken off the corners directly instead, each giving up a share proportional to
its size.  And the engine's own validator treated zero turning as "never closes
into a lap" — which was a bug the real data found.  What proves a lap closes is
where it ends up, and `check_position_closure` already measured exactly that.

## Results

Every one of the twenty-five lands on its published length exactly, and every
lap closes.  Against real pole laps, for the fifteen where a pole time exists
for that layout:

| circuit | vs pole | | circuit | vs pole |
|---|---|---|---|---|
| Interlagos | +0.63 s | | Mexico City | +2.21 s |
| Suzuka | +0.63 s | | Zandvoort | +2.63 s |
| Hungaroring | +0.88 s | | Red Bull Ring | +3.20 s |
| Bahrain | +1.75 s | | Shanghai | +3.29 s |
| Monza | +3.41 s | | Austin | +4.04 s |
| Montreal | +4.85 s | | Silverstone | +4.97 s |
| Spa | −5.41 s | | Catalunya | +8.66 s |
| Albert Park | +14.59 s | | Yas Marina | +22.54 s |

Twelve of fifteen inside five seconds — under 5.5% — and three inside a second,
from geometry alone with no per-circuit tuning.

A circuit is wired into the game calendar when it measures within five seconds.
Eleven of the twenty-two races are; the rest keep their synthetic tracks.

## What is still wrong, and why

**Three circuits are the right circuit in the wrong year.**  Albert Park,
Catalunya and Yas Marina miss by 8–23 s, and they are the three that were
rebuilt after the survey set was collected: Yas Marina in 2021, Albert Park in
2022, Catalunya in 2023.  Those files are honest recordings of the previous
layout.  They are held out of the calendar rather than corrected, because
correcting them would mean inventing the change.

**Spa runs 5.4 s fast because it is flat here.**  Raidillon climbs forty
metres and the survey has no elevation.  This is a missing input, not a
modelling error, and no smoothing setting fixes it — a flat Spa gets *faster*
with any widening.

**Seven circuits have no survey at all**: Jeddah, Miami, Imola, Monaco, Baku,
Singapore and Las Vegas — street circuits, mostly recent.  They keep their
synthetic tracks.

**The racing line is approximated, not solved.**  The 45 m smoothing window
stands in for a line model.  `f1_race_engine/track/racing_line.py` solves the
real problem — minimise ∫(κ + n″)² subject to |n| ≤ h, which reduces to a
biharmonic `n'''' = −κ''` solved by projected Gauss-Seidel on a coarse-to-fine
cascade — and it is correct for what it minimises, but ∫κ² is not max|κ|, and
lap time is set by the peaks.  On a 9.4 m-wide Monza it returns a line 13%
*tighter* at the worst corner than the smoothing does.  It is behind
`TrackDefaults.geometry = "centreline"` and off by default, with its own tests
for the shape of its answer.  Making it minimise the right functional is the
next piece of work.
