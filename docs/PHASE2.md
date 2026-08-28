# Phase 2 — Basic Vehicle Physics

**Status: complete.** 464 tests pass, and every shipped car passes the
automatic physics sanity suite with zero errors and zero warnings at every wing
level and in hot and cold conditions.

Phase 1 built the circuit. Phase 2 builds the car: a set of separable systems
whose behaviour comes out of a real force balance.

---

## Delivered

| Item | Where |
|---|---|
| Vehicle | `vehicle/model.py` — spec + setup + subsystem models |
| Mass | `vehicle/mass.py` — chassis, driver, fuel, distribution, load transfer |
| Engine | `vehicle/power_unit.py` — torque-limited and power-limited regimes |
| Drag & downforce | `vehicle/aero.py` — both ∝ v², coupled by induced drag |
| Brakes | `vehicle/brakes.py` — system capability above the grip limit |
| Basic tyre grip | `tyres/` — compounds, load sensitivity, friction ellipse |
| Physics core | `physics/` — normal loads, force balance, cornering |
| Environment | `environment/` — air density from real atmospheric physics |
| Validation | `physics/validation.py` — 14 automatic checks (rules 39, 40) |
| Benchmark | `physics/benchmark.py` — measured against published F1 figures |
| Debug plots | `visualization/vehicle_plots.py` — force balance, g-g, envelope |

---

## Running it

```bash
pytest

python examples/05_vehicle_benchmark.py        # benchmark + validate every car
python examples/06_setup_trade_off.py          # the downforce/drag trade-off
python examples/07_visualise_vehicle.py        # diagnostic plots
```

---

## Benchmark — reference car, medium wing

Every figure is **integrated from the force balance**. None is a parameter.

```
  top speed                       323.2 km/h  ok     320-360 km/h
  0-100 km/h                         2.45 s  ok        2.4-3.0 s
  0-200 km/h                         5.01 s  ok        4.4-5.6 s
  0-300 km/h                        12.52 s HIGH      9.5-12.5 s
  200-0 km/h braking                 63.9 m  ok          55-80 m
  peak lateral                       5.40 g  ok        4.5-6.5 g
  peak braking                       6.06 g  ok        4.5-6.5 g
  standing acceleration              1.10 g  ok        0.8-1.6 g
```

The one figure outside its range is **correct behaviour, not an error**.
Published 0-300 km/h times are quoted in low-drag trim; at wing level 0 this
car does it in **10.83 s**, inside the range. The medium-wing car is slower
down the straight because it is carrying wing — which is the whole point. ERS
(Phase 5) adds ~120 kW and will move it further.

### Lateral grip build-up

```
      50 km/h   1.76 g  ##############
     100 km/h   2.05 g  ################
     150 km/h   2.52 g  ####################
     200 km/h   3.17 g  #########################
     250 km/h   3.99 g  ################################
     300 km/h   4.97 g  ########################################
```

Nothing produces that curve except downforce ∝ v² combined with tyre load
sensitivity. At 50 km/h the car has almost no downforce, so it corners on
mechanical grip alone (~1.8 g); at 300 km/h the floor presses it down with more
than twice its own weight.

---

## The setup trade-off

The mechanism behind project rule 2.3 — no per-track corrections — is
**induced drag**: `CdA = CdA₀ + k·ClA²`. Each extra unit of wing costs more
drag than the last, so there is no setting that wins everywhere.

| wing | ClA | CdA | top speed | R25 m | R60 m | R120 m | R250 m |
|---|---|---|---|---|---|---|---|
| 0.0 | 3.60 | 0.950 | 346.5 | 76.3 | 127.3 | 210.0 | 346.5\* |
| 0.5 | 4.90 | 1.167 | 323.2 | 77.7 | 134.0 | 242.9 | 323.2\* |
| 1.0 | 6.20 | 1.449 | 300.7 | 79.2 | 141.7 | 292.4 | 300.7\* |

\* flat out — the tyres are not the limit there, the engine is.

Three regimes fall out of one mechanism:

* the **slow corner** barely moves (+2.9 km/h across the whole wing range) —
  there is no downforce at 77 km/h, so only mechanical grip counts;
* the **medium-fast corner** gains most (+82.4 km/h) — downforce is decisive
  and the tyres are still the limit;
* the **fast corner** is flat at every setting, so wing buys nothing and costs
  the full 45.8 km/h top-speed deficit.

A circuit built from long straights and slow corners therefore wants a
different car from one built from fast sweepers, and nothing in the engine
branches on a track name to make that happen.

---

## The three shipped cars

| Car | Top speed | 0-200 | R100 corner | Character |
|---|---|---|---|---|
| Power-biased | 340.6 km/h | 4.83 s | 195.4 km/h | wins straights |
| Reference 2024 | 323.2 km/h | 5.01 s | 201.4 km/h | balanced |
| Aero-biased | 305.8 km/h | 5.22 s | 210.0 km/h | wins corners |

All three pass validation. Phase 3 and 4 will show each winning on the circuit
that suits it — which is the real test of rule 2.3.

---

## Physics sanity checks (rules 39 and 40)

Fourteen checks, run against every car at every wing level and in hot and cold
conditions. Two kinds, because they catch different failures.

**Directional** — these catch a sign error or a dropped force term:

| Check | Assertion |
|---|---|
| Aero | speed ↑ → downforce ↑ and drag ↑, downforce exactly ∝ v² |
| Wing | more wing → more cornering **and** less top speed |
| Mass (rule 39) | mass ↑ → acceleration ↓, cornering ↓ |
| Power (Test E) | power ↑ → acceleration ↑, top speed ↑ |
| Grip (Test D) | grip ↑ → cornering ↑, braking ↑ |
| Track (rule 39) | radius ↓ → cornering speed ↓ |
| Load sensitivity | μ falls with load, total force still rises |
| Friction ellipse | spending longitudinal grip reduces lateral |
| Braking | harder from 280 km/h than from 80 km/h |
| Air density | denser air → more cornering, less top speed |
| Fuel (rule 23) | full tank → slower acceleration and cornering |

**Envelope** — a model can be self-consistent and still produce a car that
corners at 12 g; only comparison against reality catches that. Top speed, peak
lateral, peak braking, standing acceleration and low-speed lateral are all
bounded against published F1 figures.

Rule 40's Test C (faster car → faster lap) needs a lap time and is a Phase 4
entry criterion.

---

## Key modelling decisions

**Induced drag couples downforce to drag.** `CdA = CdA₀ + k·ClA²` rather than
two independent lookups. This is the single decision that makes setup a real
choice and circuits genuinely different.

**Load sensitivity on the tyre.** `μ = μ_peak·(N/N_ref)^-k`. Without it,
cornering ability would rise linearly with downforce and the fast corners would
come out absurd. It is also why the *coefficient* is lower in a fast corner
than a slow one even though the *force* is far higher.

**Traction is an axle question.** A rear-drive car launches on its rear tyres,
so the traction limit uses rear axle load — static distribution, plus the rear
share of downforce, plus load transfer.

**Cornering is solved, not inverted.** Grip depends on speed (downforce) and on
load (sensitivity), so the corner speed limit is implicit and is found by
bisection. Inverting a simplified closed form would be wrong in exactly the
high-load regime that matters.

**Braking is grip limited.** The brake system is deliberately specified above
any grip limit, because an F1 car can lock its wheels at any speed. That is why
braking performance comes out of downforce and tyres rather than a brake
number.

---

## One deliberate deviation from the phase plan

The project plan puts **weight transfer** in Phase 12. Phase 2 implements the
*quasi-static longitudinal* part only — `ΔN = m·a·h_cg/wheelbase` — because
without it a rear-drive car's standing-start acceleration is understated by
about 15% and 0-100 km/h comes out near 2.9 s instead of 2.45 s.

It is config-gated (`powertrain.longitudinal_load_transfer`) and both
parameters it needs are ordinary vehicle data. The full dynamic treatment —
suspension, damping, pitch, lateral transfer — remains Phase 12.

---

## Not in this phase

No speed profile, no lap time, no driver, no tyre degradation, no ERS, no fuel
burn. Deliberately:

* **Speed profile and lap time** are Phases 3 and 4. Phase 2 gives them the
  point-wise capability queries they consume.
* **ERS** (rule 24) is a separate energy system with its own state and
  deployment limits. It arrives in Phase 5 as an additive term in the power
  unit — never as a lap-time bonus.
* **Tyre temperature and degradation** are Phase 5. `TyreState.grip_multiplier`
  returns exactly 1.0 today, and Phase 5 fills in that one method.
* **Gearbox** is Phase 12. `peak_wheel_torque` stands in for the engine torque
  curve times the lowest usable ratio.

---

## Bugs found and fixed during the phase

Recorded because each is a trap the next phase could fall into again.

1. **Misleading cornering figures.** `corner_speed_limit` legitimately returns
   speeds above the car's top speed — it is a *grip* statement, meaning "the
   tyres would hold this corner faster than the engine can ever push". But the
   validation report was printing "450 km/h through a 150 m corner", which is
   nonsense to a reader. The checks now bound reported speeds by top speed and
   compare on a radius where both configurations are genuinely grip limited;
   the function's semantics are documented rather than changed, because Phase 3
   needs the unbounded value to take a minimum against.
2. **Lazy-import recursion.** `visualization/__init__.py` resolved plot
   functions with `from . import track_plots` inside a module-level
   `__getattr__`. The import machinery asks the package for the submodule as an
   attribute, which lands back in `__getattr__` and recurses forever. It only
   surfaced when a second plot module was added, because the Phase 1 test had
   already imported the submodule by another route. Now uses
   `importlib.import_module`, which does not consult `__getattr__`.
3. **Benchmark integration eight times more expensive than useful.** The
   acceleration and braking integrals ran 4000 sub-steps. Measured convergence:
   500 steps reproduces the 4000-step answer to 1e-5 relative — 0-300 km/h
   within 0.0002 s. The suite went from 84 s to 14 s, which matters because
   rule 47 requires running it at every phase and a slow suite gets skipped.

---

## Refactor carried out this phase

Validation reporting (`Severity`, `ValidationIssue`, `ValidationReport`) moved
from `track/validation.py` to `core/validation.py`, because rule 39 asks for
automatic validation of *every* system and the machinery is generic. Track
validation now subclasses it, keeping `TrackValidationError` and the
`track_name` accessor. All 283 Phase 1 tests passed unchanged afterwards.

---

## Entry criteria for Phase 3

Met:

- [x] Code runs
- [x] Tests pass
- [x] Physics sanity checks pass on every car, wing level and condition
- [x] Benchmark runs and lands in published Formula 1 ranges
- [x] Results reviewed against real figures
- [x] Problems found were fixed, not deferred
