# Phase 3 — Speed Profile

**Status: complete.** 535 tests pass, every car/circuit combination validates
with zero errors and zero warnings, and lap time converges to within 0.02% as
track resolution changes by a factor of twenty.

Phase 1 built the circuit. Phase 2 built the car. Phase 3 puts the car on the
circuit and gets a lap time out of it — one that is the *integral of a speed
profile*, not a number anyone chose.

---

## Delivered

| Item | Where |
|---|---|
| Cornering limit | `physics/speed_profile.py` — from tyres, downforce, mass, banking |
| Braking limit | backward pass, respecting combined grip |
| Acceleration limit | forward pass, traction- and power-limited |
| Forward / backward passes | wrapping the lap until they converge |
| Speed profile | the pointwise minimum of all three |
| Braking zones | `physics/braking.py` — braking point, distance, entry/exit |
| Acceleration zones | `physics/acceleration.py` — with traction/power split |
| Lap time | `physics/lap_time.py` — exact integration, sectors, rule-41 metrics |
| Setup search | `physics/setup_search.py` — let the circuit choose the setup |
| Lap validation | `physics/lap_validation.py` — 11 checks, including rule 40's Test C |
| Debug plots | `visualization/lap_plots.py` — speed profile, zones, g trace, speed map |

---

## Running it

```bash
pytest

python examples/08_lap_time.py --validate    # lap + checks for every combination
python examples/09_setup_per_circuit.py      # the circuit chooses the setup
python examples/10_visualise_lap.py          # speed profile, zones, g trace
```

---

## How it works

```
Track -> curvature -> cornering limit
                          |
                +---------+---------+
                |                   |
          backward pass        forward pass
         (what braking          (what the engine
          allows into it)        allows out of it)
                |                   |
                +---------+---------+
                          |
                   final speed profile  =  the minimum of all three
```

No corner is given an average speed. Where the three curves intersect is the
apex, and nobody had to say so.

Three things make it correct rather than merely plausible:

**Both directions matter.** A slow corner limits how fast you may still be
*arriving* and how fast you can *have got* to the next one. One sweep can only
propagate one of those.

**The sweeps wrap.** A lap is a loop, so a braking zone can begin before the
start/finish line. The passes repeat around the lap until nothing changes,
which is what makes the answer independent of where the lap is cut.

**Combined grip is respected throughout.** A car turning at 80% of its lateral
limit has only the remainder of the friction circle left for braking or
traction, so the passes ask the tyre model what is actually available.

That last one is visible in the trail-braking trace into a slow corner —
deceleration *falls* from 4.71 g to 0.98 g as the friction budget shifts from
longitudinal to lateral:

```
   dist       R    limit    speed  a_long g  a_lat g
   2267straight    ------    306.7     -3.95     0.00   braking begins
   2290    2340    ------    267.5     -4.71     0.24
   2313     180    ------    219.0     -3.07     2.10   turning in
   2335      94     196.7    185.8     -0.98     2.90
   2339      90     183.2    183.2      0.00     2.93   ON THE LIMIT
```

---

## Benchmark — reference car, medium wing

```
LAP  --  Reference 2024  at  Synthetic Proving Ground
  lap time                  1:08.632
    sector 1  24.273 s     sector 2  23.305 s     sector 3  21.054 s

  top speed  324.3 km/h    minimum  77.6 km/h    average  261.1 km/h
  max lateral  4.18 g      max braking  5.05 g   max acceleration  1.25 g
  full throttle  91.9%     braking  8.1%
  mean power  448.9 kW     energy delivered  30.81 MJ

  BRAKING ZONES
       at m   len m     from       to   peak g  corner
       1163     121      324      103     5.05  Turn 1
       2267      87      307      182     4.71  Turn 4
       3993     113      324       78     4.74  Turn 6 (Hairpin)
```

**Is 1:08.6 for 4978 m realistic?** Monza covers 5793 m in about 81 s. Scaled
to this circuit's length that is 69.6 s, and this circuit has fewer slow
corners than Monza. So yes.

### The three circuits produce three different laps

| Circuit | Lap | Average | Full throttle | Braking | Zones |
|---|---|---|---|---|---|
| Power | 1:25.053 | 296.3 km/h | 96% | 4% | 2 |
| Proving ground | 1:08.632 | 261.1 km/h | 92% | 8% | 3 |
| Street | 1:23.812 | 143.9 km/h | 65% | 35% | 16 |

Real F1 reference: Monza ~80% full throttle, Silverstone ~70%, Monaco ~55%.

---

## Project rule 2.3, measured

The rule forbids per-track corrections. The positive test is whether circuits
disagree about what car and what setup they want — on their own.

**Which car wins flips between circuits** (medium wing, seconds):

| Circuit | aero-biased | power-biased | reference |
|---|---|---|---|
| Power | 88.608 | **81.841** | 85.053 |
| Proving ground | 70.675 | **66.795** | 68.632 |
| Street | **83.724** | 83.791 | 83.812 |

**And the optimal wing level spans the entire range:**

| Circuit | optimal wing | worst setting costs |
|---|---|---|
| Power | 0.0 | +7.137 s |
| Proving ground | **0.2 (interior optimum)** | +2.320 s |
| Street | 1.0 | +3.507 s |

The balanced circuit having a genuine *interior* optimum is the strongest
single piece of evidence that the trade-off is real: it wants some downforce,
but not all of it. Nothing in `f1_race_engine/` branches on a circuit's name.

The mechanism is induced drag, `CdA = CdA₀ + k·ClA²`, from Phase 2.

---

## Resolution independence

Phase 1 proved the *circuit* was resolution independent. Phase 3 has to prove
the *lap time* is, or every later result rests on an implementation detail.

```
resolution        nodes    lap time    seconds
coarse (30 m)       222    1:08.622    68.6223
default             475    1:08.632    68.6319
fine (3 m)          982    1:08.638    68.6381
uniform 1 m        4965    1:08.639    68.6388
```

Segment count varies by 22×; lap time by **0.0165 s (0.024%)**, converging
monotonically. Two things make that possible: the energy update
`v₁² = v₀² + 2·a·ds` is exact for constant acceleration, and a midpoint
corrector makes it second-order for the real, speed-dependent case.

---

## Sensitivities

Every one of these is measured, not set:

| Change | Cost/gain per lap (proving ground) |
|---|---|
| +10% engine power | −1.532 s |
| +5% tyre grip | −0.550 s |
| +50 kg | +0.633 s (0.127 s per 10 kg) |
| Wing level across its range | 2.320 s |

Mass sensitivity varies correctly with circuit character — 0.093 s/10 kg on the
power circuit, 0.199 s/10 kg on the street circuit. That is the right physics:
mass largely cancels out of low-speed cornering (`a_lat ≈ μ·g`) but not out of
acceleration. The commonly quoted F1 figure of ~0.3 s per 10 kg sits above even
the street-circuit number here; that gap is a **calibration** question and
needs telemetry (project rule 43), not a fudge factor.

---

## Automatic checks (rules 39, 40, 47)

Eleven lap checks, on top of Phase 2's fourteen vehicle checks:

| Check | Assertion |
|---|---|
| Cornering limit | the profile never exceeds what the tyres allow |
| Convergence | the sweeps settled |
| Periodicity | the profile joins up across the start/finish line |
| Sector times | sum to the lap time exactly |
| Plausibility | average speed, braking fraction in real ranges |
| Braking zones | each ends at a corner and actually slows the car |
| Corner exit | slow-corner exits are traction limited (rule 17) |
| **Test C** | more power → faster lap |
| **Test D** | more grip → faster lap |
| Mass | more mass → slower lap |
| Setup sensitivity | wing level is worth real lap time |

Rule 40's Test C first becomes testable here, because until Phase 3 there was
no lap.

---

## Bug found and fixed during the phase

**The lateral and longitudinal models were using different grip bases.**
`lateral_capability` computed the friction circle on the car's *total* load;
`traction_limited_force` computed it *per axle*. Because the friction
coefficient falls with load, two axles evaluated separately have more grip
between them than the same load evaluated as one lump — so a car sitting
exactly at its cornering limit still believed it had **+4.99 m/s²** of drive
available, and the speed profile accelerated through apexes.

Cornering is now charged as a *fraction of the whole car's friction circle*,
which is the same basis the lateral model uses. At the limit the reserve is
zero, so the car cannot overcome drag and settles just below the pure lateral
limit — which is exactly what a real car does in a long constant-radius corner:

```
   2339.2  v=183.192 km/h  limit=183.192  a_long=-1.6423 m/s2
   2354.4  v=182.139 km/h  limit=183.196  a_long=-0.4084 m/s2
   2377.2  v=181.766 km/h  limit=183.205  a_long=-0.0741 m/s2   <- equilibrium
```

Phase 2's numbers were unaffected (its benchmark is straight-line, where no
lateral grip is being spent) and all 464 Phase 2 tests passed unchanged.

---

## Not in this phase

No driver, no tyre degradation, no fuel burn, no multiple cars.

What Phase 3 produces is the **limit lap**: a perfect driver, exactly on the
tyre everywhere, fixed fuel, fresh tyres. That is the right Phase 3 answer — it
is the lap the car is capable of.

The driver attaches through `PerformanceLimits`, which is already wired
through the profile and defaults to 1.0 on all three axes. A driver who brakes
at 95% of the limit moves the braking points earlier on their own; there is
nothing to add to the profile code when Phase 4 supplies real values.

Rule 41's remaining benchmark fields — fuel used, energy used, tyre state — are
Phase 5. `energy_delivered` (30.81 MJ per lap) is already computed, and Phase 5
converts it into fuel consumed and energy harvested.

---

## Entry criteria for Phase 4

Met:

- [x] Code runs
- [x] Tests pass (535)
- [x] Physics sanity checks pass for every car on every circuit
- [x] Benchmark runs and lap times are realistic against real F1 pace
- [x] Lap time is resolution independent
- [x] Results reviewed
- [x] The bug found was fixed, not deferred
