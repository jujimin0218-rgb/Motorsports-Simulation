# Real circuits

The engine's track files used to be invented.  Twelve are now **measured**: a
surveyed centreline goes in, corner radii, turn angles and straight lengths
come out, and the result is checked against a real pole lap before it is
allowed to ship.  Eleven of the season's twenty-two races run on them.

Twenty-five circuits were recovered.  Thirteen of them are not here.  That is
the point of the process rather than a shortfall in it — see *The gate*.

## The gate

`f1_race_engine/data/circuit_reference.json` lists what each shipped circuit is
measured against, and `tests/test_circuit_accuracy.py` enforces it.

A circuit ships when its computed lap lands within **5 seconds** of a real pole
lap set on *that* layout by a car of the era this engine models — under a pole
lap's conditions, which are not the defaults: the wing is optimised for the
circuit, the tank has 20 kg in it, and the ERS is deployed.

This is a real check because the recovery never sees the number.  It solves the
straights against the published lap length and stops; the lap time is computed
afterwards by the physics from the shape of the road.  A layout can close,
measure exactly right, and still be the wrong shape — a plausible circuit
rather than this one — and the lap time is what notices.

Circuits with no comparable pole lap do not ship however clean their geometry.
**Unverified is not the same as correct.**

## What ships

| circuit | vs pole | | circuit | vs pole |
|---|---|---|---|---|
| Interlagos | +0.63 s | | Mexico City | +2.21 s |
| Suzuka | +0.63 s | | Zandvoort | +2.63 s |
| Hungaroring | +0.88 s | | Red Bull Ring | +3.20 s |
| Bahrain | +1.75 s | | Shanghai | +3.29 s |
| Monza | +3.41 s | | Austin | +4.04 s |
| Montreal | +4.85 s | | Silverstone | +4.97 s |

Three inside a second, from geometry alone with no per-circuit tuning.

## What does not, and why

**Three are the right circuit in the wrong year.**  Albert Park, Catalunya and
Yas Marina were rebuilt in 2022, 2023 and 2021, after the survey set was
collected.  Those files are honest recordings of the previous layout.
Correcting them would mean inventing the rebuild.

**Spa has no elevation.**  It runs 5.4 s fast because Raidillon climbs forty
metres and this data is flat.  A missing input, not a modelling error — no
smoothing setting fixes it, and a flat Spa gets *faster* with any widening.

**Nine have no comparable pole lap**: Brands Hatch, Hockenheim, Indianapolis,
Moscow Raceway, Norisring, Nürburgring, Oschersleben, Sepang, Sochi.  Their
geometry recovered cleanly.  Nothing independent agrees with it.

**Seven have no survey at all**: Jeddah, Miami, Imola, Monaco, Baku, Singapore
and Las Vegas.  They keep their synthetic tracks.

All twenty-five surveys stay in `data/tracks/survey/`, so any of these ships the
moment a reference or a better source turns up.

## How a survey becomes a track file

`tools/extract_circuits.py`, in five steps.

1. **Resample by arc length** at 3 m.  Survey points are spaced however the
   surveyor walked, and curvature computed on uneven spacing mostly measures
   the spacing.

2. **Curvature, smoothed.**  `κ = (x'y'' − y'x'')/(x'² + y'²)^1.5`, then a
   circular moving average.  The window is the one real parameter and it is set
   by measurement: swept from 21 m to 110 m across five circuits with known
   pole times, lap time moves more than fifteen seconds and passes through the
   right answer at about forty-five.  It is also not really a filter setting —
   smoothing curvature over the distance a car takes to cross the width of a
   circuit is, physically, an approximation to *what a racing line is*.

3. **Segment** into corners (above 1/400 m) and straights, absorbing runs
   shorter than a car length.

4. **Fit** each corner: radius is arc length over total turn, angle is the
   integral of curvature, direction is the sign.

5. **Close it** with the engine's own solvers — `solve_corner_angles` so the
   heading closes on a whole number of turns, then `solve_straight_lengths`
   against the published lap length, so the clothoid transitions the engine
   adds do not lengthen the lap past what the circuit measures.

Nothing is per-circuit.  DRS zones go on the longest straights of the built
lap, sectors at its thirds — rules anybody can check rather than a table only
the author can vouch for.

### Four things that had to be got right

Each was found by a circuit failing, not by inspection.

**Small kinks must not be thrown away.**  A run turning less than six degrees
stays a straight, but its turning is folded into the next real corner.
Discarding it left the definition twenty degrees short of its own trace, the
closure solver put those degrees back by moving the corners that *were*
measured, and Montreal came out at fifteen kilometres.  Keeping every kink as a
corner fixes the turning and breaks the other end — no straights are left for
the length solver.  Folding does both.

**The transitions are already in the survey.**  A real corner entry is in the
measured curvature, so the engine adding its own clothoid on top double-counts
it.  These definitions carry `transition_factor=0.04`.

**A 5.8 km-radius "corner" is a straight.**  Monza's main straight has a gentle
drift the segmenter classified as a bend, which cost the circuit its defining
feature.  A final pass reclassifies anything above the corner threshold and
redistributes its turning across the real corners in proportion to their size.
Monza's longest straight went from nothing to 1206 m.

**A figure of eight turns nowhere.**  Suzuka crosses over itself and closes at
zero net turns.  The angle solver scales every corner by one factor and no
factor but zero takes a non-zero sum to zero, so the half-degree of leftover
comes off the corners directly, each giving up a share proportional to its
size.  And the engine's own validator rejected zero turning as "never closes
into a lap" — a bug the real data found.  What proves a lap closes is where it
ends up, and `check_position_closure` already measured exactly that.

## Adding a circuit from FastF1

`tools/extract_circuits.py` also reads FastF1 position telemetry, which fills
both remaining gaps: it is current-season data, and it carries elevation.

Export a fast lap's position channels to CSV — `X`, `Y` and `Z` from
`lap.get_telemetry()` or `lap.get_pos_data()` — and hand it to `load_fastf1()`.
Extra columns are ignored, so a full telemetry export works as well as a
trimmed one.

Three things differ from a survey and the tool handles each:

- **It is a driven line, not the centreline.**  The driver has already cut every
  corner, so the radii are the line's rather than the circuit's.  Telemetry gets
  `SMOOTH_TELEMETRY_M` (15 m, enough to remove positional noise) instead of
  the 45 m window, which stands in for a racing line and would otherwise be
  applied twice.  Mark the result `TrackDefaults.geometry = "driven_line"`.
- **It carries elevation.**  `elevation_control_points()` thins `Z` to one point
  per hundred metres — fine enough for Eau Rouge, coarse enough not to turn GPS
  noise into a gradient — and levels any sensor drift linearly round the lap so
  the height closes exactly rather than stepping at the timing line.
- **It has no width.**  Nothing in telemetry says how wide the road is, so it
  has to be told.

A circuit added this way faces the same gate: put its pole time in
`circuit_reference.json` and the test decides whether it ships.

## What is still approximate

**The racing line.**  The 45 m smoothing window stands in for a line model.
`f1_race_engine/track/racing_line.py` solves the real problem — minimise
∫(κ + n″)² subject to |n| ≤ h, which reduces to a biharmonic `n'''' = −κ''`
solved by projected Gauss-Seidel on a coarse-to-fine cascade — and is correct
for what it minimises.  But ∫κ² is not max|κ|, and lap time is set by the peaks:
on a 9.4 m-wide Monza it returns a line 13% *tighter* at the worst corner than
the smoothing does.  It is behind `TrackDefaults.geometry = "centreline"` and
off by default, with tests for the shape of its answer.  Making it minimise the
right functional is the next piece of work.
