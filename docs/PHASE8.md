# Phase 8 — Strategy and Pit Stops

**Status: complete.** A stop is priced from the pit lane's own geometry, a plan
is computed from measured degradation, and a strategist abandons the plan when
the track stops matching it.

---

## Delivered

| Item | Where |
|---|---|
| Pit lane | `race/pitlane.py` — a stop priced as two journeys (rule 32) |
| Strategy | `race/strategy.py` — compound choice, plans, in-race decisions (rule 31) |
| Planning | `race/planning.py` — measure the tyres, measure the stop, then add up |
| Stops in a race | `race/session.py` — the strategist runs in the lap loop |

---

## Running it

```bash
python examples/17_race_weekend.py --laps 30      # stops happen inside a race
```

---

## What a stop costs (rule 32)

> "피트스탑 시간 손실은 상수로 두지 않는다."

There is no constant. A stop is the difference between two journeys between the
same two points on the circuit:

* **through the pit lane** — brake to the limit, run the lane, stop, get going
  again — integrated with the same force model as everything else;
* **on the racing line**, which the car's own speed profile answers exactly.

Rejoining is charged separately, because it happens after the pit exit on a
piece of road the car would have covered flat out.

Everything a strategist needs falls out of that subtraction:

| | pit loss |
|---|---|
| Power circuit (500 m lane) | 23.3 s |
| Proving ground (448 m lane) | 21.2 s |
| Street circuit (302 m lane) | 11.7 s |

| variable | effect |
|---|---|
| speed limit 60 → 100 km/h | 26.6 s → 17.9 s |
| lane 300 → 700 m | 15.5 s → 30.8 s |
| crew 1.9 → 3.5 s stationary | 20.7 s → 22.3 s |

The crew's number and the lane's geometry are separate inputs because they are
separate things, and there is a test that changing one does not move the other.
A car that accelerates better also loses less, because getting back up to speed
is part of the price.

---

## Planning a race (rule 31)

> "타이어 전략은 하드코딩된 규칙이 아니라 계산 결과여야 한다."

Nothing says a soft tyre is for a short stint. What the planner does instead is
measure two things and add them up:

1. **the degradation curve** — a set is bolted on and driven until it is
   finished, and the lap times that come back *are* the curve. Warm-up, the
   cliff and everything else nobody thought to model are already in there.
2. **the pit loss**, from above.

Then it searches every way of splitting the race distance and takes the
smallest total. The two-compound rule is a regulation, so it is a constraint on
the search rather than a term in the objective — turn it off and the same search
happily runs one compound all race, which is what happens in the wet.

Same car, same driver, same 40 laps, two circuits:

```
proving ground   S14 -> M26                stops on lap 14      pit loss 21.2 s
street circuit   S17 -> S17 -> M6          stops on laps 17, 34 pit loss 11.7 s
```

A cheap pit lane buys an extra stop. Nobody wrote that down; it comes out of
21.2 s being worth more laps of degradation than 11.7 s is.

---

## Which tyre, without anybody saying so

`compound_for_conditions` scores each compound by the grip it would actually
deliver — `peak_friction × wet_grip_factor(compound, depth, speed)` — and takes
the best. On a dry track that is the softest slick; as the water deepens the
slicks score zero long before the intermediate does, and the intermediate before
the full wet. See `docs/PHASE10.md` for the table.

Because clearance falls with speed, the *same* puddle can want a different tyre
at a circuit where it sits on a straight than at one where it sits in a hairpin.

---

## Abandoning the plan

A plan is a projection of a race that has not happened. What makes a strategist
is reacting when it stops describing reality, and `RaceStrategy` weighs three
reasons to stop in the order a pit wall would:

1. **the tyre is wrong for the track as it now is** — which is what a shower
   does, and it does not wait for the plan or for the minimum stint;
2. **the set is finished**, whatever the plan said — but not if the stop would
   cost more than the laps left are worth;
3. **the plan said so.**

Run a race into a shower and the whole field reacts without being told to:

```
car 1: lap 4 M->I (conditions, 23.4 s), lap 9 I->S (conditions, 21.9 s)
car 2: lap 4 M->I (conditions, 23.7 s), lap 9 I->S (conditions, 21.9 s)
car 3: lap 4 M->I (conditions, 23.5 s), lap 9 I->S (conditions, 21.9 s)
car 4: lap 4 M->I (conditions, 23.6 s), lap 9 I->S (conditions, 21.9 s)
```

The rain arrives, everybody boxes for intermediates; the cars dry their own
racing line; everybody boxes back for slicks. The only inputs were a water depth
and a tread pattern.

---

## Where the cost lands

The loss is charged to the lap the stop happens on, so the lap chart shows it
where it was incurred. That is a simplification: a real pit entry is before the
line and the exit after it, so the cost is split across two laps. Correcting it
needs the lap simulation to start and finish somewhere other than the line,
which is not worth the disruption until cars interact.

---

## Not in this phase

* **Undercuts and overcuts.** Both are about *other cars* — stopping early to
  use clear air, or staying out to inherit it. Phase 9.
* **Refuelling.** The hook is there; the regulations are not.
* **Pit lane traffic and unsafe releases.** Cars in the lane do not see each
  other, for the same reason cars on track do not.
* **Reacting to what rivals do.** A strategist reads the track and its own car,
  not the timing screen.
* **Penalties.** Speeding in the pit lane is not possible, because the limit is
  enforced by construction rather than policed.
* **Being made to stop.** The strategist honours the two-compound rule when it
  chooses a tyre, but it will not take a stop that costs more time than it is
  worth purely to comply — so a car whose tyres last the distance can finish
  having used one compound. Making that illegal needs a penalty to enforce it
  with, and penalties are Phase 11's.
