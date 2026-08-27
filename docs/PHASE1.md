# Phase 1 — Foundation

**Status: complete.** 283 tests pass, all three shipped circuits build and
validate with zero errors and zero warnings.

Phase 1 builds the base the rest of the engine stands on: core infrastructure
and the track model. There is deliberately no vehicle yet.

---

## Delivered

| Item | Where |
|---|---|
| Core state | `core/state.py` — clock, snapshot protocol, telemetry recorder |
| Units | `core/units.py` — SI internals, conversion layer at the boundary |
| Configuration | `core/config.py` — frozen, validated, JSON round-tripping |
| Deterministic RNG | `core/rng.py` — hierarchical named sub-streams |
| Track segment | `track/segment.py` — immutable, linear curvature |
| Track model | `track/model.py` — `distance → TrackState` |
| Track builder | `track/builder.py` — definitions → spans → segments |
| Track validation | `track/validation.py` — 16 registered checks |
| Synthetic circuit | `data/tracks/synthetic_proving_ground.json` (+ two more) |
| Debug visualisation | `visualization/` — SVG (no deps) and matplotlib plots |

Beyond the required list: an event bus (`core/events.py`) as the Phase 11 seam,
monotone-cubic profiles (`core/interpolation.py`) so gradient is continuous, a
benchmark report (`track/report.py`), and the circuit closure solver
(`track/layout_solver.py`).

---

## Running it

```bash
pip install -e '.[dev]'

pytest                                          # 283 tests
python examples/01_build_and_validate.py        # benchmark report for every circuit
python examples/02_track_state.py               # walk a lap, print the track state
python examples/03_visualise.py                 # SVG maps + matplotlib overviews
python examples/04_resolution_independence.py   # the property the design rests on
```

---

## The reference circuit

`Synthetic Proving Ground` — 4978 m, 7 corners — exists to exercise every part
of the model at once, as Phase 1 requires: a long straight, a second long
straight, and high-, medium- and low-speed corners.

```
  length                  4978.3 m      (4.978 km)
  corners                      7
  direction           anticlockwise
  segments                   475

  GEOMETRY
    total turning        360.000 deg   (+1.0000 full turns)
    closure error           0.01 m     (0.000% of lap)
    tightest radius         25.0 m

  COMPOSITION
    straights             3595.1 m  #################....... 72.2%
    corners               1383.3 m  #######................. 27.8%
    longest straight      1262.4 m

  CORNER MIX
    low_speed                  1
    medium_speed               2
    high_speed                 4
    left / right            6 / 1

  ELEVATION
    range                   36.0 m
    total climb             44.0 m
    gradient                -2.6% to +4.4%

  DRS
    zones                      2
    coverage               34.5% of the lap

  RESOLUTION
    segment length          1.06 m min, 10.48 m mean, 25.00 m max
```

Two more circuits ship so that later phases can show track character emerging
from geometry rather than from per-track corrections:

| Circuit | Length | Corners | Longest straight | Min radius | Corner mix (L/M/H) |
|---|---|---|---|---|---|
| Power | 7000 m | 7 | 1416 m | 60 m | 0 / 2 / 5 |
| Proving Ground | 4978 m | 7 | 1262 m | 25 m | 1 / 2 / 4 |
| Street | 3350 m | 16 | 501 m | 18 m | 8 / 8 / 0 |

All three are **synthetic and labelled as such** in their metadata. See
`docs/ARCHITECTURE.md` §10 for why real circuits are deferred.

---

## Physics sanity checks

Run as part of the suite, not as a one-off:

| Property | Result |
|---|---|
| Segments tile the lap exactly | gaps < 1e-9 m |
| Curvature continuous, including across start/finish | jumps < 1e-12 1/m |
| Total turning is a whole number of turns | 360.000000000° |
| Plan view closes | 0.01 m on 4978 m (2e-6 of lap) |
| Elevation returns to its starting height | < 1e-6 m |
| Total climb equals total descent | exact, as a closed loop requires |
| Quarter circle matches the analytic result | 1e-5 m over 157 m |
| Full circle closes | < 1e-6 m |
| Corner transitions preserve the turn angle | exact to 1e-9° |
| Gradient is C1 (no impulsive forces) | max derivative jump < 1e-3 |
| Monotone cubic never overshoots | verified over 3000 samples |
| Green track grip equals static grip | exactly 1.000 |

---

## Resolution independence

The property the whole architecture rests on. The same circuit built at four
sampling resolutions:

```
resolution        segments       lap [m]   turning [deg]   min R [m]   climb [m]  closure [m]
coarse (30 m)          222   4978.341365   360.000000000     25.0000     43.9985     0.006070
default                475   4978.341365   360.000000000     25.0000     43.9985     0.006068
fine (3 m)             982   4978.341365   360.000000000     25.0000     43.9985     0.006068
uniform 1 m           4965   4978.341365   360.000000000     25.0000     44.0000     0.006068
```

Segment count varies by 22×. Track state sampled at 500 distances differs by at
most 1.7e-13 in curvature and exactly zero in gradient, banking and width.

---

## Determinism (rule 40, Test A)

- Same seed + same input → identical output, for both the RNG and the builder.
- A new subsystem consuming 500 random draws leaves every existing stream's
  numbers **unchanged** — verified in `tests/test_rng.py`.
- Seeds derive from BLAKE2b, so they do not depend on PYTHONHASHSEED.

Tests B–E from rule 40 (faster car → faster lap, more grip → more cornering,
more power → more acceleration) require a vehicle and are Phase 2/3 entry
criteria.

---

## Bugs found and fixed during the phase

Recorded because each one is a trap the next phase could fall into again.

1. **Seam slope discontinuity.** The periodic profile's wrap-padding points
   were given one-sided end slopes instead of their true interior slopes, so
   the gradient jumped across the start/finish line. Gradient enters the
   longitudinal force balance directly, so this would have been an impulsive
   force once per lap.
2. **Resolution-dependent track state.** DRS zone, sector, surface and kerb
   were read off the segment, which samples them at its midpoint. A query near
   a boundary answered differently at different resolutions. `state_at` now
   resolves them from their own maps at the exact distance.
3. **Segment length floor violated.** Rounding the segment count up pushed
   actual lengths below the configured minimum. The count is now capped so the
   floor holds.
4. **Corner radius check masked by its own warning.** Reporting once per corner
   keyed on the first segment seen meant a transition segment's mild warning
   suppressed an impossible radius at the apex. The check now judges each
   corner on its tightest point.
5. **Overlay range check ran too late.** An out-of-range control point surfaced
   as a confusing profile error instead of naming the offending overlay.

---

## Not in this phase

No vehicle, no driver, no tyres, no speed profile, no lap time. Those are
Phases 2–4. Nothing in Phase 1 pre-empts them; the seams are documented in
`docs/ARCHITECTURE.md` §8.

The web layer (FastAPI + React) and the season-management game sit on top of
the engine and are not part of the simulation core. The engine is already
UI-free and JSON-serialisable, so that layer attaches without changes here.

---

## Entry criteria for Phase 2

Met:

- [x] Code runs
- [x] Tests pass (283)
- [x] Physics sanity checks pass
- [x] Benchmark runs and its output is recorded
- [x] Results reviewed
- [x] Problems found were fixed, not deferred
