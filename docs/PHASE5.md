# Phase 5 — Tyres, Fuel and Energy

**Status: complete.** 681 tests pass. The car now carries consumables that
change underneath it: tyres that heat and wear from the work they do, fuel
burned from the engine's work, and an energy store that has to recover what it
deploys.

---

## Delivered

| Item | Where |
|---|---|
| Tyre temperature | `tyres/temperature.py` — two-mass heat balance (rule 21) |
| Tyre wear | `tyres/wear.py` — dissipated friction work (rule 22) |
| Degradation | `tyres/degradation.py` — grip lost to wear and to cooking |
| Tyre state | `tyres/state.py` — one object, one grip number, updated per step |
| Fuel | `vehicle/fuel.py` — burned from engine work (rule 23) |
| Energy recovery | `vehicle/ers.py` — a store with budgets and two recovery paths (rule 24) |
| Consumables in the lap | `simulation/lap.py` — the per-segment accounting |
| Calibration | `core/config.py` — `tyre_thermal`, `tyre_wear`, `fuel`, `ers` |

---

## Running it

```bash
pytest

python examples/13_stint_consumables.py --laps 25   # a set of tyres, a tank, a battery
python examples/14_compound_choice.py --laps 26     # where a softer tyre stops paying
```

---

## The one rule this phase had to obey

> "타이어 열화는 단순히 매 랩 일정한 시간을 더하는 방식으로 만들지 않는다."
> "ERS는 단순히 '랩타임 -0.5초' 방식으로 구현하지 않는다."

Nothing in this phase adds or subtracts time, and nothing counts laps. Three
quantities are accumulated per segment and everything else is a consequence:

| Quantity | Accumulated from |
|---|---|
| Tread temperature | friction power into the rubber, minus convection and conduction |
| Tread wear | friction force × distance — the work the tyre dissipates |
| Fuel | engine work ÷ (thermal efficiency × heating value) |
| Stored energy | deployed against drive force, recovered from braking and exhaust |

`TyreState.age_laps` exists and is *never read by the physics*. There is a test
that says so.

---

## Tyre temperature (rule 21)

Two masses, because one is not enough. The tread has a small heat capacity and
responds in seconds; the carcass has a large one and lags by laps. That is what
produces a tyre up to temperature on the outside after one lap and still cold
underneath.

```
heat in   = work_coefficient × hysteresis × |F_friction| × v
heat out  = (convection_base + convection_speed·v)·(T − T_air)
          + track_conduction·(T − T_track)
          + internal_conduction·(T_surface − T_carcass)
```

`hysteresis` comes from the compound's own wear rate — softer rubber loses more
energy internally, so it heats faster. Nothing else distinguishes the compounds
thermally, and it is enough to make softs come in quickly and run hot while
hards never quite do.

Grip is a quadratic well centred on the compound's optimum, floored so a
stone-cold tyre still drives. Measured on the power circuit, medium compound:

| | tread temperature | grip |
|---|---|---|
| coolest point (end of the straight) | 85 °C | 0.964 |
| lap mean | 102 °C | 0.997 |
| hottest point (corner exit) | 122 °C | 0.943 |

The calibration puts the lap mean just below the compound's optimum on purpose.
A compound is designed around the temperature it will see, and leaving a little
headroom is what lets pushing harder warm a tyre *into* its window rather than
straight out of it.

---

## Tyre wear (rule 22)

```
wear increment = (|F_friction| × ds / reference_wear_energy)
               × compound.wear_rate
               × (1 + max(T − T_optimal, 0)/window)^2.4
               × (1 − management_range · driver.tyre_management)
```

Four behaviours a strategist cares about, none of them written down:

* a circuit that asks more of the tyre wears it faster, because the tyre does
  more work per lap;
* pushing wears more than cruising, because commitment raises the friction force;
* overheating is far worse than merely using the tyre, because the thermal term
  is raised to a power above one;
* a driver good at tyre management genuinely makes a set last longer.

Grip loss is progressive — `1 − 0.22·wear^1.6` — so a set holds its performance
and then falls away rather than fading in a straight line.

**Thermal damage** is separate and permanent. Above the top of the working
window the tyre starts losing grip that does not come back when it cools, which
is why cooking a set early in a stint is expensive for the rest of it.

---

## A stint (power circuit, medium)

```
 lap      time   delta   tread   wear   grip    fuel   burn  deploy  recov  charge
   1  1:24.604  +0.000   94.0C   3.2%  0.990   97.8kg  2.164   3.83M   3.76     98%
   2  1:23.139  +0.000   99.1C   6.9%  0.997   95.7kg  2.164   3.84M   3.80     97%
   4  1:23.033  +0.000  101.8C  15.2%  0.988   91.3kg  2.163   3.84M   3.80     96%
   8  1:23.213  +0.180  102.1C  32.6%  0.962   82.7kg  2.164   3.84M   3.81     93%
  12  1:23.421  +0.388  101.5C  49.5%  0.928   74.0kg  2.164   3.84M   3.82     91%
  16  1:23.684  +0.651  100.9C  65.7%  0.887   65.4kg  2.160   3.82M   3.84     90%
```

Three things are happening at once and they do not all pull the same way. The
tyres come in over the first two laps (worth 1.57 s), then go off. The car burns
2.16 kg a lap and gets quicker for it. The fastest lap of the stint is lap 4 —
late enough that the tyres are working, early enough that they are still fresh —
which is where a real one is too, and nothing puts it there.

---

## Compound choice, and where it crosses over

Same car, same driver, same circuit; the only difference is which compound is
fitted. Cumulative stint time, so the lowest number at each row is the compound
to be on for a stint of that length:

| stint length | best compound |
|---|---|
| 1–6 laps | Soft |
| 7–21 laps | Medium |
| 22+ laps | Hard |

| | best lap | wear after 26 laps | peak tread |
|---|---|---|---|
| Soft | 1:22.758 | 100% (finished by lap 22) | 137.3 °C |
| Medium | 1:23.034 | 100% (finished by lap 25) | 122.0 °C |
| Hard | 1:23.359 | 56.9% | 107.6 °C |

The soft is 0.6 s a lap quicker while it lasts and cooks itself doing it. No
part of the engine knows that softs are for short stints.

---

## Fuel (rule 23)

Fuel is mass on board burned in proportion to the work the *internal combustion*
engine does — the electrical share burns nothing, which is the point of a
hybrid. The regulated flow limit caps the answer, so a car cannot burn its way
past the rules however hard it is being driven.

| circuit | lap | fuel | flow |
|---|---|---|---|
| Power circuit | 1:23.030 | 2.163 kg | 0.0261 kg/s |
| Proving ground | 1:06.744 | 1.604 kg | 0.0240 kg/s |
| Street circuit | 1:23.267 | 1.227 kg | 0.0147 kg/s |

Real Formula 1 is 1.5–2.5 kg a lap. Note the ordering: per *second* the power
circuit is thirstiest because it demands the most power, but per *kilometre* the
street circuit is, because it spends longer covering the same ground. Both are
true of the real thing, and neither is stated anywhere in the engine.

---

## Energy recovery (rule 24)

The store has a capacity, a per-lap deployment budget, and two recovery paths
that behave completely differently:

* **the brakes** — capped at 120 kW and 2 MJ per lap, and only available while
  the car is slowing down;
* **the exhaust** — capped at 45 kW, available while the car is on the throttle,
  and *not* budgeted per lap.

That asymmetry is the reason a car can deploy 4 MJ a lap when its brakes could
never recover that much, and it is why the deployment a circuit sustains depends
on its character rather than on its name:

| circuit | no ERS | full store | gain | deployed |
|---|---|---|---|---|
| Power circuit | 1:25.144 | 1:23.030 | −2.114 s | 3.85 MJ |
| Proving ground | 1:08.749 | 1:06.744 | −2.004 s | 3.75 MJ |
| Street circuit | 1:24.231 | 1:23.267 | −0.964 s | 3.02 MJ |

The street circuit gets less than half the benefit — partly because it cannot
find the accelerating time at speed to spend the whole budget, and partly
because a fixed power is worth less force the faster you are already going.

**The deployment policy** decides a budget for the lap — the regulated limit, or
what is in the store plus what the previous lap recovered, whichever is smaller
— and spends it evenly across the time the car spends accelerating. Over a stint
that settles by itself into the equilibrium every real hybrid runs at: *you can
deploy what you recover, and no more.* Phase 8 replaces the policy with a
strategic one; the accounting underneath does not change.

---

## Two design decisions worth stating

**Grip is held still for the length of a lap.** The lap is planned on the tyre
the driver went out on, so it is driven on that tyre too; the live state goes on
heating and wearing underneath and is what the *next* lap is planned on. Letting
the plan and the execution disagree is worse than a small lag — and not in the
obvious direction. A car whose real grip has dropped below its plan simply fails
to brake as hard as it intended, carries the extra speed into the corner, and
comes out with a **faster** lap for having less grip. That was measured at
+0.26 s of phantom pace before the fix. Degradation belongs between laps, which
is also where a strategist reads it.

**The grip multiplier is stored, not derived on demand.** The physics asks the
tyre for one number thousands of times a lap and the answer only changes when
the tyre does, so `TyreState.refresh()` computes it — it is the only place that
holds the calibration — and everything else reads `TyreState.grip`. Before this,
the grip model called `grip_multiplier()` with no configuration and would have
silently used defaults under a non-default calibration.

---

## Bugs found and fixed during the phase

**A tyre default that cost 10% of the grip.** `TyreState()` defaulted to 80 °C
while the medium compound's optimum is 100 °C, moving the reference lap from
1:08.632 to 1:10.106. A freshly constructed state now starts at its compound's
own optimum — the right idealisation for a limit lap — and `fit()` starts a set
below its window, which is what a car leaves the pit box on.

**A tread that swung 75 °C within a lap.** The first calibration gave the tread
a 9 kJ/K heat capacity, so a long fast corner put 70 K into it and peaks reached
155 °C. The tyre was taking permanent damage every lap and the superlinear wear
term was firing hard at every apex. A tread capacity of 30 kJ/K — about four
tyres' worth of rubber — brings the swing to ±18 K, which is what a real one
does.

**Wear that accelerated only past a cliff edge.** The thermal wear term measured
its excess from the top of the working window, so a tyre wore at exactly its
reference rate right up to the edge and then fell off. It now measures from the
optimum: rubber does not wear at one flat rate and then suddenly stop being
rubber.

**A better braker who was slower.** With grip evolving mid-lap but the plan
fixed, braking later heated the tyres more, and the resulting mismatch made the
stronger braker 0.078 s *slower* on the reference circuit. Fixed by the
grip-held-still decision above; the ordering is now traction +0.215 s > braking
+0.080 s > 0, as it was in Phase 4.

**An energy store that was empty after lap one.** With only brake recovery the
car recovered 0.31 MJ a lap against a 4 MJ budget, so every lap after the first
was effectively unpowered. The exhaust recovery path — which is real, and which
is precisely why the regulations budget the two paths differently — brings
recovery to 3.8 MJ and the store into equilibrium.

---

## What this phase did not do

* **Per-corner tyre state.** All four tyres are one set. Per-corner load and
  temperature need the suspension model in Phase 12.
* **Strategic deployment.** The ERS policy spreads its budget evenly. Deciding
  *where* the energy is worth most is Phase 8.
* **Lift-and-coast and fuel saving.** The coupling is there — pushing burns more
  — but nothing yet chooses to trade lap time for fuel.
* **Wet tyres in the wet.** The compounds exist; the water model does not.
* **Warm-up within a lap.** Grip changes between laps, not within one. See the
  design decision above.

---

## Entry criteria for Phase 6

Met: a car can be driven for many laps with state that carries forward, the
result is reproducible from the seed and the starting conditions, and every
consumable is accounted for at the segment level. Phase 6 puts more than one of
them on the circuit at the same time.
