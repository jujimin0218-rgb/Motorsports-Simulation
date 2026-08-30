# Real circuits

The twenty-two circuits on the calendar are real, and their lengths, corner
counts and race distances are the published ones. What has never been real is
the **shape** a lap is driven on: the engine ships three synthetic circuits, and
each round borrows whichever one is closest to its character.

This is the work to replace that, and where it has got to.

## Where the geometry came from

FastF1 was the obvious source and is not reachable: this environment's network
policy allows GitHub and the package indexes and denies
`livetiming.formula1.com`, so there is no telemetry to recover a line from.

What *is* reachable is the [TUM racetrack
database](https://github.com/TUMFTM/racetrack-database) — surveyed
**centrelines** in metres, with the track width either side. Fifteen of the
twenty-two circuits are in it, and a centreline is the better input anyway: a
racing line has already cut every corner, so its radii belong to the driver
rather than to the circuit.

The files are in `data/tracks/survey/`.

## How a centreline becomes a circuit

`tools/extract_circuits.py`. The engine builds a track from corner radii, turn
angles and the straights between them, so the survey has to be turned into
those — which is what project rule 43 means by recovering geometry from data
rather than reading it off a map.

1. Resample uniformly by arc length, because curvature computed on uneven
   spacing measures the spacing.
2. Curvature, smoothed. The window is the one real parameter: too short and a
   straight reads as a string of tiny corners, too long and a chicane smears
   into one bend.
3. Split into corner and straight runs; absorb anything shorter than a car.
4. A corner's radius is its arc length over its total turn, which is more
   robust than averaging `1/κ` over noisy samples.
5. Re-solve the straights against the published lap length, using the engine's
   own closure solver — the engine joins straights to corners with clothoids,
   and those add length the measured arc did not have.

## What it produces

Every one of the fifteen closes and lands on its published length:

| circuit | recovered | published | corners | turn |
|---|---|---|---|---|
| Monza | 5793 m | 5793 m | 14 | −361.0° |
| Spielberg | 4317 m | 4318 m | 14 | −365.1° |
| Spa | 7002 m | 7004 m | 22 | −363.2° |
| Silverstone | 5889 m | 5891 m | 18 | −359.2° |
| Suzuka | 5805 m | 5807 m | 23 | +0.5° |
| Montreal | 4359 m | 4361 m | 18 | −363.4° |
| … | | | | |

Suzuka's half-degree is not an error: it is a figure of eight and genuinely
turns as far one way as the other.

The corner counts run a few above the published ones because "turn 8" is a
naming convention and a curvature run is a measurement — a sequence a circuit
calls one corner often has two distinct radii in it.

## What still stands in the way

**The circuits do not ship yet.** They fail the gate that matters, which is
that geometry producing the wrong lap time is a drawing rather than a
measurement. Two separate things cause it, pulling opposite ways.

### The centreline is not the racing line

A car goes wide, cuts to the apex and comes out wide — a straighter path than
the road. The engine's corner model drives the centreline, so real geometry
comes out slow:

| circuit | engine | real pole | |
|---|---|---|---|
| Monza | 1:26.92 | 1:19.33 | +7.59 s |
| Silverstone | 1:32.21 | 1:25.82 | +6.39 s |
| Bahrain | 1:32.92 | 1:29.18 | +3.74 s |
| Suzuka | 1:30.98 | 1:28.20 | +2.78 s |

Widening every corner as a diagnostic closes most of it — Monza goes from
+7.59 s to +1.22 s at ×1.6 — and it also moves Monza's setup optimum to
minimum wing, which is where Monza's has to be and where it was not before.
But the factor is not uniform: Silverstone wants about ×1.2 and Monza about
×1.6, so a flat multiplier is a diagnostic and not a fix.

The fix is a racing-line model, and the engine already carries on every segment
the one thing such a model needs and currently ignores: `track_width`.

### There is no elevation in the survey

A flat Spa is a quick Spa. It comes out **3.65 s fast** at the centreline and
worse with any widening, because Raidillon climbs forty metres and this data
does not know it. The engine models gradient properly; it has not been told
about it.

## What would finish this

1. A racing-line model in the engine, using the track width it already carries.
2. An elevation source for the fifteen circuits.
3. A source for the seven the TUM database does not have — Jeddah, Miami,
   Imola, Monaco, Baku, Singapore, Las Vegas.

Until then the tool reports both numbers and writes nothing, which is the same
answer `tools/author_circuits.py` gives its own drafts. The difference is that
the geometry is now measured rather than remembered, and what is left is two
named pieces of physics rather than a guess.
