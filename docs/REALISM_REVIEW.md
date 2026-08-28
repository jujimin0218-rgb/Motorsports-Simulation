# Realism Review — measuring the engine against the real thing

**Status: three defects fixed, one capability added, one gap left open and
named.** A pass over the Phase 1–9 engine looking for places where the model
disagrees with a real Formula 1 car, done by measuring the engine and putting
the numbers next to published ones rather than by reading the code and forming
opinions.

The method matters. Every finding below started as a measurement, and two
things I was initially confident were wrong turned out to be right when
measured properly — which is the reason for measuring.

---

## What was wrong

### 1. Braking was charged against the car, not against an axle

`physics/longitudinal.py` capped braking at the friction available on the
car's **total** load:

```python
grip = grip_limit(compound, loads.total)
brake_force = min(brakes.brake_force(brake), available_longitudinal(grip, lateral))
```

Traction had been done properly — the driven axle, its own load, load transfer,
solved implicitly — but braking had not. That quietly assumes a brake bias that
follows the load transfer around, which no car has: the bias is **fixed** while
the car is stopping, so the first axle to reach its friction limit ends the
braking for both of them.

```
F_total = min( F_front_limit / bias ,  F_rear_limit / (1 - bias) )
```

The strongest evidence it was wrong was not a number, it was a dead field:
`brake_bias_front = 0.57` sat in every car specification and in
`BrakeProperties`, and **nothing read it**. A car's brake bias could be set to
anything at all and the lap time would not move.

Now it is solved the same implicit way traction is, in the opposite direction —
braking harder loads the front and unloads the rear — and the bias is a real
setup parameter. Asked where the optimum is, the engine now answers:

| brake bias (front) | deceleration at 280 km/h |
|---|---|
| 0.40 | 3.88 g |
| 0.50 | 4.43 g |
| **0.57** | **4.85 g** |
| 0.68 | 4.00 g |
| 0.78 | 3.47 g |

The optimum falls at 0.57 — which is the bias the car specifications were
already carrying, and the bias a real Formula 1 car runs. That number was put
in the data as a real-world figure long before anything could read it; the
model now derives it independently.

### 2. Two axles had more grip between them than the whole car

Fixing braking exposed an older inconsistency. Friction coefficient falls with
load, so asking about half a car's load returns a **higher** coefficient than
asking about all of it. The traction solver asked per axle, the lateral model
asked per car, and the two never had to agree — so the axles offered 5.7% more
grip between them than the car did:

```
whole car at 30 kN : 45 343 N
two axles at 15 kN : 47 928 N   (+5.7%, out of nowhere)
```

`traction_limited_force` knew about this — its docstring works around it by
charging cornering against the whole-car circle — but the artefact itself was
still there, inflating every traction and braking answer.

Load sensitivity is a property of one contact patch, so a query now says how
many patches the load is spread over. An axle carrying `N` is, per patch, a car
carrying `2N`:

```python
grip_limit(compound, loads.rear, tyres=2)
```

Whole-car answers are bit-identical to before; the axle answers are now
consistent with them, and `check_axle_grip_is_consistent` keeps them that way.

### 3. A DRS zone could not cross the start/finish line

`DrsZone.__post_init__` rejected `activation_end <= activation_start`. Real
zones cross the line routinely — at Monza the flap opens on the exit of the
Parabolica and closes on the approach to the Rettifilo, with the timing line in
between. The line is a timing device, not a feature of the road, and nothing
about a zone should change when it moves. A zone whose end is behind its start
is now read as wrapping, and `DrsMap.overlaps` compares zones as arcs of the
lap rather than as intervals on a line.

---

## What was measured and found right

Both of these looked wrong at first and were not. They are recorded because
"we checked" is worth as much as "we fixed".

**Peak braking.** The engine reaches 7.2 g of deceleration, which no Formula 1
car does. But that was measured at wing level 0.5 and 340 km/h — a Monaco
package at Monza speed, a combination that cannot occur, because that car's top
speed is 322 km/h. Run at a wing level a car would actually use at that speed
and put next to Brembo's published telemetry for Monza's first chicane:

| | distance | time | peak |
|---|---|---|---|
| Brembo, 351 → 86 km/h | 137 m | 2.64 s | 5.9 g |
| engine, minimum wing | 125 m | 2.33 s | 6.0 g |

The peak lands almost exactly. The engine stops 9% shorter because it brakes at
the friction limit for the whole event, where a real driver builds the pressure
up and bleeds it off again — a driver-model difference, not a physics one, and
one worth coming back to when the driver's braking input becomes a real
`driver/inputs.py` trace rather than "as hard as the tyres allow".

**Aerodynamic efficiency.** `AeroProperties.efficiency` documented itself as
falling with wing level, and it rises: 3.79 at minimum wing to 4.28 at maximum.
That reads like a bug, and it is not. A large part of an F1 car's drag comes
from the wheels and bodywork rather than the wings, so `L/D` stays roughly flat
across the usable range — the marginal cost of the last unit of downforce is
what grows, and `dCdA/dClA = 2k·ClA` does grow. The docstring was wrong, not
the model. It has been corrected and `marginal_drag` added to state the real
trade-off.

---

## Where the engine sits against a real car

Reference car, measured by `physics/validation.py`:

| quantity | engine | real |
|---|---|---|
| peak lateral | 5.2 g | 5–6 g |
| peak braking | 5.8 g | 5–6 g (Brembo: 5.9 g at Monza) |
| standing start | 1.03 g | ~1.09 g implied by 0–100 km/h in 2.6 s |
| brake bias optimum | 0.57 front | 0.57 front |
| braking, 351 → 86 km/h | 125 m | 137 m (Brembo, Monza) |
| compound spread S→H | 0.60 s | 1.0–1.4 s |

The compound spread is the loosest of these and is the obvious next
calibration target.

---

## The gap that is still open: real circuits

Project rule 10 asks for Monza, Monaco, Silverstone, Spa, Suzuka and Bahrain as
benchmark circuits. The engine ships three synthetic ones, honestly labelled as
such, and **none of the six real circuits**. That is the largest distance
between the specification and the code.

What was added is the pipeline and, more importantly, the acceptance criteria —
`tools/author_circuits.py`, plus two engine capabilities real layouts need that
synthetic ones do not:

* **corners that change radius** (`CornerDefinition.radius_end`) — the
  Parabolica opens out, Bahrain's Turn 1 tightens. Modelled as two separate
  corners the car would be allowed to accelerate through the join;
* **`solve_corner_angles`** — a closed lap turns through exactly 360 degrees,
  and straights cannot help with that because a straight turns the car through
  nothing. Angles read off a track map have to be reconciled with that
  constraint before the straights can be solved.

That last one is also the honesty check, and it is why no real circuit ships.
How far the angles have to move to close a lap is a measure of how good the
reading was, and asked about three drafts written from memory of the track maps
it answers:

```
Monza         angles moved 10.0%  ->  closes, but the lap comes out +7.6% and
                                      the setup search wants maximum wing
Silverstone   angles moved 44.0%  ->  rejected
Spa           angles moved 80.0%  ->  rejected
```

Monza passing the geometric check and then failing on character is the useful
result: the corner-to-straight balance is wrong, so the circuit does not reward
the low-drag car it should, and shipping it would put an invented layout into
the engine's calibration set under a real circuit's name. The tool refuses to
write any of them.

Corner radii close to published figures are not enough. What these drafts need
is real geometry — a survey trace, or radii and straight lengths recovered from
telemetry (project rule 43) — and with it they become data files rather than
guesses. The checks that will say when the data is good enough are in place and
run on every invocation.

---

## Running it

```bash
pytest

python tools/author_circuits.py            # the three drafts and their verdicts
python examples/08_lap_time.py --validate  # the physics checks, per car
```
