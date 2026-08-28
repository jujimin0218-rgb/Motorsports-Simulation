# Phase 4 — Lap Simulation

**Status: complete.** 598 tests pass. A car with a driver in it now steps
around the circuit segment by segment, producing pedal inputs, telemetry, and a
lap time that responds to who is driving.

---

## Delivered

| Item | Where |
|---|---|
| Driver | `driver/model.py` — ten separate abilities (rule 18) |
| Ability → physics | `driver/pace.py` — abilities become grip commitment |
| Driver input | `driver/inputs.py` — throttle, brake, steering, gear, ERS (rule 19) |
| Consistency | `driver/consistency.py` — per-lap and per-corner variation |
| Mistakes | `driver/mistakes.py` — errors that cost time through the driving |
| Lap simulation | `simulation/lap.py` — the rule-26 stepping loop |
| Telemetry | `simulation/telemetry.py` — real-trace channels, CSV export |
| Driver lineup | `data/drivers/` — six fictional drivers with distinct shapes |
| Telemetry plots | `visualization/lap_plots.py` — speed/throttle/brake overlays |

---

## Running it

```bash
pytest

python examples/11_driver_stint.py --laps 20     # a stint, driver by driver
python examples/12_driver_telemetry.py           # telemetry CSV + comparison plot
```

---

## The stepping loop (rule 26)

```
Track Segment -> Vehicle State -> Driver Input -> Physics -> New Vehicle State
      ^                                                             |
      +-------------------------- next segment --------------------+
```

Time is integrated as `dt = ds / v` and the vehicle state carries forward.

**The test that says it is right:** a driver with no shortfall and no variation
reproduces the Phase 3 limit lap.

```
stepped lap : 68.6328 s
Phase 3 QSS : 68.6319 s
difference  : +0.0009 s  (+0.0013%)
top speed and minimum speed identical to 5 significant figures
```

---

## How a driver changes a lap

Never by adjusting a lap time. Each driving ability becomes the **fraction of
available grip the driver actually uses**:

```
utilisation = 1 - (1 - attribute) * max_commitment_deficit
```

and those go into `PerformanceLimits` — the seam wired through the speed profile
since Phase 3. The physics does not know a driver exists; it only knows how
much grip is being asked for. Everything else follows:

* a weaker braker brakes **earlier**, because the backward pass finds a lower
  deceleration;
* a weaker traction driver loses **specifically out of slow corners**, because
  that is where traction binds;
* a mistake lowers the **apex speed** at one corner, and the forward pass
  carries the loss down the following straight.

### Calibration

Measured, not chosen. On the reference circuit, using 94% of available grip
costs 0.86% of lap time and 99% costs 0.17%, so the entire Formula 1 field has
to live inside a very narrow band of commitment — which is itself the
interesting result.

| Config | Value | Calibrated against |
|---|---|---|
| `max_commitment_deficit` | 0.30 | best-to-worst spread ≈ 1% of lap time |
| `consistency_sigma` | 0.12 | lap-to-lap σ of 0.1–0.2 s mid-field |
| `mistake_rate` | 0.30 | rookie errs every few laps, benchmark ~1 in 100 |

---

## A stint, driver by driver

20 laps, reference car, same seed:

```
driver              best   median    worst      sd  mistakes    quali
REN  Alex Rensen  68.740   68.762   68.817   0.023         0   68.635
BER  Nico Bertone 68.968   69.082   69.770   0.195         3   68.702
VAN  Iris Vandal  69.001   69.013   69.022   0.007         0   69.001
REY  Tomas Reyes  69.049   69.123   69.331   0.077         0   68.927
SUG  Hana Sugiyama 68.951  68.983   69.067   0.032         1   68.908
ORL  Danil Orlov  69.550   69.749   70.164   0.170         3   69.645
```

Everything in that table is emergent:

* **Race and qualifying order differ.** Bertone is 4th on race median (+0.320 s)
  and 2nd in qualifying (+0.067 s). He is a one-lap specialist who finds
  commitment when it counts and gives it back over a stint. Nothing says so.
* **Vandal is the metronome** — σ of 0.007 s, best and median almost identical,
  because her consistency is 0.99.
* **Inconsistency costs average pace, not just scatter.** Commitment can fall
  short of the limit but never exceed it, so the variation is one-sided and an
  erratic driver's median lap is genuinely slower.
* **Mistakes land where the erratic drivers are** — three each for Bertone and
  the rookie, none for the benchmark or the metronome.

Spread best-to-worst: 0.99 s on a 68.6 s lap (1.4%), teammate gaps 0.06–0.19 s.
Both match Formula 1.

---

## What each ability is worth

Isolating one attribute at a time (+0.14 on that axis alone):

| Circuit | braking share of lap | braking ability worth | traction ability worth |
|---|---|---|---|
| Power | 4% | +0.040 s | +0.112 s |
| Proving ground | 9% | +0.080 s | +0.144 s |
| Street | 32% | +0.253 s | +0.496 s |

Two results fall out, neither of them written down anywhere:

1. **Braking ability pays in proportion to how much braking a circuit asks
   for** — 0.040 s where braking is 4% of the lap, 0.253 s where it is 32%.
2. **Traction is worth about twice braking, everywhere.** A lap spends far
   longer accelerating than braking, so you gain more on exit than on entry —
   which is what every racing driver will tell you.

---

## Telemetry (rule 43)

The channels a real trace has: distance, time, speed, throttle, brake,
steering, gear, lateral and longitudinal g, sector, DRS, tyre wear, fuel.
Exports to CSV so a simulated lap and a FastF1 lap can be laid side by side.

Time-weighted full-throttle fraction, as teams quote it:

| Circuit | full throttle | braking | cornering |
|---|---|---|---|
| Power | 92% | 3% | 30% |
| Proving ground | 84% | 8% | 29% |
| Street | 40% | 25% | 41% |

Real F1: Monza ~80%, Silverstone ~70%, Monaco ~55%.

**One channel needs a caveat.** `brake` is the fraction of the braking
*system's* capability being demanded, and an F1 car's brakes are stronger than
its tyres, so at the limit it saturates near 0.7 — the tyres lock first. Real
telemetry records pedal *pressure*, which does reach 100% and is not the same
quantity. Reconciling them needs a pedal-force map, which belongs with the
brake model in Phase 12.

---

## Bugs found and fixed during the phase

1. **The controller solved in the wrong space.** Throttle scales the *drive
   force*, but the first version mapped a required acceleration to throttle as
   a ratio of *net* accelerations — which silently ignores drag. A perfect
   driver came out **1.06 s a lap slower** than the car's own limit, with the
   error concentrated exactly where drag is largest. Now solved in force space:
   `delta_force = m·(a_required − a_coast)`, and the pedal is that divided by
   what the powertrain can add.
2. **The controller and the profile evaluated at different points.** The speed
   profile evaluates segment capability at the *midpoint* speed; the controller
   was evaluating at the segment *start*. Harmless for lap time (0.01%) but it
   reported a driver lifting to 94% throttle on a straight where they were in
   fact flat. Both now use the midpoint, and throttle reaches exactly 1.0.
3. **Pace saturated the strongest drivers.** An additive pace bonus pushed
   elite drivers to 100% commitment in race trim, so a qualifying mode had
   nothing left to give them — the benchmark driver gained 0.000 s from a
   flying lap. Pace is now *blended* into each specific ability rather than
   added on top, and qualifying gain now ranks correctly: +0.197 s for the
   specialist, +0.112 s for the benchmark, 0 for a baseline qualifier, and
   −0.206 s for a rookie who cannot find anything extra.
4. **Telemetry fractions were sample-weighted.** Samples are spaced by
   *distance* and the track is sampled far more finely in corners, so
   full-throttle was under-reported at 71%. Now time-weighted, which is how
   teams quote it, giving 84% on the Monza-like circuit.

---

## Not in this phase

* **Racecraft, overtaking, defending** — the attribute exists and is unused
  until Phase 9, when there is another car to race.
* **Tyre management** — the attribute exists and is unused until Phase 5 gives
  tyres something to manage.
* **Wet skill** — Phase 10.
* **Gear and ERS deployment** — present as input channels and left empty, as
  the gearbox is Phase 12 and the energy system Phase 5. They are not faked.
* **Multiple cars** — Phase 6. The simulator is per-car by construction, and
  its RNG streams are already keyed by driver and lap, so cars can be run in
  any order or in parallel and get identical results.

---

## Entry criteria for Phase 5

Met:

- [x] Code runs
- [x] Tests pass (598)
- [x] A perfect driver reproduces the Phase 3 limit lap to 0.0013%
- [x] Driver spread, teammate gaps and lap-to-lap scatter match real Formula 1
- [x] Telemetry is realistic and exports in real-trace channels
- [x] Results reviewed
- [x] All four bugs found were fixed, not deferred
