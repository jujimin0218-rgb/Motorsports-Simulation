# Phase 6 — Multi-Car Racing

**Status: complete.** 728 tests pass. A field of cars now shares one circuit,
one clock and one set of conditions, each carrying its own tyres, fuel and
energy, with positions and gaps computed from real distance and time.

---

## Delivered

| Item | Where |
|---|---|
| Entry | `race/entry.py` — a car, its driver, and what it is carrying |
| Timing | `race/timing.py` — positions and gaps from distance and time (rule 28) |
| Session | `race/session.py` — runs the field and classifies it |
| Lap events | `race/session.py` — `LapCompleted` on the bus, for Phase 11 |
| Race example | `examples/15_race.py` — mid-race screens and a result sheet |

---

## Running it

```bash
pytest

python examples/15_race.py --laps 24                        # a race, start to flag
python examples/15_race.py --track synthetic_street_circuit # a different winner
```

---

## What a gap actually is (rule 28)

> "포지션과 갭은 실제 거리와 시간에서 계산되어야 한다."

A gap is never an index into a sorted list and never a running total of lap
time differences. It is the answer to one question:

> *how long ago was the car ahead standing where this car is now?*

which needs two things — a distance for every car at a moment in time, and a
time for every car at a point on the road. `TimingTower` keeps exactly that:
one strictly increasing table of `(elapsed, distance)` per car, sampled at
every sector crossing, and both questions are the same table interpolated in
opposite directions.

That one definition gives all of this for free:

* **a lapped car is a lap down, not 89 seconds behind.** The same query notices
  that the car ahead is more than a lap up the road and says so.
* **the interval between two cars is not the difference of their lap times.**
  It is the difference between them passing the same point.
* **asking mid-lap works exactly as well as asking at the line.** Every timing
  screen in `examples/15_race.py` is asked for at a moment in time, not at a
  lap boundary.

There are two honest ways to measure, and the engine uses both where each
belongs:

| | measured | used for |
|---|---|---|
| `gap(car, ahead, time)` | same **time**, two places | the live timing screen |
| `gap_at(car, ahead, distance)` | same **place**, two times | the classification |

They give slightly different numbers, and that is correct rather than a bug:
one asks "how far back is that car right now", the other "how much later did it
cross this line". Gaps measured at one point telescope exactly — third-to-second
plus second-to-first is third-to-first — and there is a test that says so. Live
intervals telescope only approximately, because each is taken where its own car
happens to be.

---

## The chequered flag

The flag falls when the winner finishes, and every other car takes it the next
time it crosses the line. So each car's race is *its first lap completed at or
after that moment* — 24 laps for somebody two seconds behind, 23 for somebody a
lap down, which is exactly how a result sheet reads:

```
pos car driver               laps       time        gap  interval      best   tyre
  1   5 Hana Sugiyama          24  26:25.004                       1:04.839  M 75%
  2   2 Nico Bertone           24  26:38.645    +13.641   +13.641  1:04.998  M 86%
  3   1 Alex Rensen            24  26:45.695    +20.691    +7.050  1:06.237  M 63%
  4   4 Tomas Reyes            24  27:02.561    +37.557   +16.866  1:06.625  M 69%
  5   3 Iris Vandal            24  27:32.152    +67.147   +29.591  1:08.379  M 50%
  6   6 Danil Orlov            23  26:43.702     +1 lap    +1 lap  1:08.938  M 58%
```

Nothing here is a lap counter dressed up. Danil Orlov is a lap down because the
distance he had covered when the winner finished was a lap short of the
winner's, and his tyre wear is 58% because of the work his tyres did getting
there.

---

## Cars must not perturb each other (rule 36)

The single easiest way to make a race simulator irreproducible is to let
randomness leak between competitors: one car draws from a shared stream, and
adding a twentieth entry silently changes the other nineteen. So every entry
gets its **own hub**, spawned from the session seed by name:

```python
rng=self.rng.spawn(f"car.{entry.car_number}")
```

Three properties are tested and all three hold exactly, to the last bit:

* the same seed and the same field give the same race;
* a car's race time does not change when the field grows from two cars to five;
* the order of the entry list does not matter.

---

## The field is not all the same, and the circuit decides who wins

Same six drivers, same three cars, same tyres, same fuel, ten laps. The only
thing that changes is the circuit:

| | Proving Ground | Power Circuit | Street Circuit |
|---|---|---|---|
| 1st | SUG, Power-Biased | SUG, Power-Biased | **REN, Reference 2024** |
| 2nd | BER, Power-Biased (+2.5) | BER, Power-Biased (+1.4) | **VAN, Aero-Biased** (+8.8) |
| 3rd | REN, Reference (+10.9) | REN, Reference (+26.9) | SUG, Power-Biased (+18.7) |

The power-biased car wins two circuits by a distance and loses the third, with
the fastest driver in the field aboard it dropping to third — and the
aero-biased car, nowhere on the other two, takes second. No part of the engine
knows what kind of circuit it is on. This is rule 2.3 arriving at the level of a
race result rather than a lap time.

---

## Performance

The profile passes, not the stepping, are what a race costs: building a lap's
speed profile is ~89% of a lap's runtime. Two exact optimisations were made
this phase, neither of which changes a single result:

**Stop the traction solve when it has converged.** The fixed point converges
from below at a rate of about `mu·h_cg/wheelbase` ≈ 0.12, so it is finished
long before the eight-iteration cap — but the previous exit test only fired on
exact float equality and so never fired at all.

**Stop it as soon as it clears the engine.** The caller takes
`min(powertrain, traction)`, and the iteration only ever climbs, so the moment a
pass exceeds the engine's own output the answer is settled. On most of a lap the
engine and not the tyre is what limits the car, so the solve is skipped
entirely.

| | ms per lap |
|---|---|
| Phase 5 | 371 |
| convergence test fixed | 339 |
| engine ceiling as well | **225** |

A six-car, ten-lap race on the reference circuit takes 15 seconds; the street
circuit, which is sampled far more finely because its corners are tighter, takes
35. Lap times are unchanged to the last digit.

---

## Design decisions worth stating

**The cars do not interact.** No dirty air, no overtaking, no defending. That is
Phase 9, and a placeholder here would only have to be unpicked. Phase 6's job is
everything underneath racing: independent state, independent randomness, and
timing that is right.

**The field is stepped in lockstep by lap.** Cars are independent, so running
them lap by lap or car by car gives identical answers — but lockstep is the
structure Phase 9 needs, when who is where at a given moment starts to matter.
Its one cost today is that laps run past the flag by a lapped car are simulated
and then not classified.

**Race state lives on the entry, not the simulator.** The tyres, the fuel and
the energy store are what persist across laps, and the entry is the thing that
persists. The simulator holds nothing between laps, which is what makes a car
movable between sessions in Phase 7 and refuelable-and-refittable in Phase 8.

---

## Not in this phase

* **Starts and grids.** `RaceEntry.grid_position` is carried but nothing uses
  it: a standing start is a launch, a first corner and a lot of interaction.
  Phase 7 does qualifying and the race procedure.
* **Pit stops.** `RaceEntry.fit()` exists and works; deciding *when* to call it
  is Phase 8.
* **Retirements and safety cars.** Phase 11, on the event bus this phase has
  already started publishing to.
* **Traffic.** A car catching a slower one currently drives straight through it.

---

## Entry criteria for Phase 7

Met: a field can be run over a race distance with per-car state, per-car
randomness and correct timing, and the result is reproducible. Phase 7 adds the
session structure around it — practice, qualifying, and a race that starts from
a grid the qualifying produced.
