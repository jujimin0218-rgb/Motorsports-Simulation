# Realism Review — measuring the engine against the real thing

**Status: two passes done. Six defects fixed, two capabilities added, two gaps
left open and named.** A pass over the Phase 1–9 engine looking for places where the model
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

## Second pass: the reference circuits were not representative

The first pass stopped at the physics.  Measuring the *outputs* -- fuel effect,
compound choice, the setup the circuit wants -- found three more things, and the
first of them explained most of the other two.

### 4. The synthetic circuits were nothing like real ones

Every calibration the engine does is measured on three shipped circuits, and
against the range the calendar occupies they were a long way outside it:

```
                          corners/km   average speed
  power circuit                 1.0        302 km/h
  proving ground                1.4        266 km/h
  street circuit                4.8        145 km/h

  Monza                         1.9        264 km/h
  Silverstone                   3.1        245 km/h
  Monaco                        5.7        171 km/h
```

The power circuit averaged 302 km/h, faster than anything in Formula 1, with a
corner every kilometre.  A lap that is nine tenths straight line barely uses
the tyres, and that quietly distorted everything measured on it: fuel looked
cheap at 0.010 s/kg against the 0.024-0.041 teams use, and the same tyre step
was worth 0.31 s on one circuit and 1.90 s on another -- a six-fold spread
where the real one is about two-fold.

None of that was a physics bug.  It is what the physics correctly says about
laps no real circuit resembles.  `tools/design_circuits.py` regenerates all
three inside the range real circuits occupy, and gates them on it.  The gate is
geometry only -- corner density, average speed, minimum speed -- because the
obvious fourth measure, share of the lap at full throttle, turns out to be a
property of the *driver model* rather than of the road: the Phase 4 controller
follows the speed profile exactly, so where the profile is flat it holds a
maintenance throttle while a real driver squirts and lifts.  Same lap time,
different pedal trace.  Gating a circuit on it would be tuning the road to
suit the driver.

One convention had to be pinned down on the way.  A radius in this data is the
radius the *car* drives, not the road's centreline: the engine has no
racing-line model, so its cornering speeds are calibrated against the line
rather than the road.  The check is that they come out right -- Suzuka's 130R
is a 130 m corner taken at 290 km/h, and asked about a 130 m radius the engine
answers 292.

### 5. Every circuit wanted maximum wing

With realistic corner content the setup search collapsed: all three circuits
wanted the biggest wing available, including the one built to reward low drag.
The cause was the aero calibration.  Drag was anchored at the low-downforce end
and left to follow at the high end, which put a Monaco package at ``CdA 1.45``
where published figures say 1.6-1.8.  Downforce was nearly free, so more of it
always won.

Re-anchored at both ends -- ``ClA 3.6 -> CdA 0.92`` and ``ClA 6.2 -> CdA 1.75``
-- and the trade comes back:

```
  before   L/D 3.79 -> 4.28 (rising)     every circuit wants maximum wing
  after    L/D 3.91 -> 3.54 (falling)    power circuit minimum, street maximum,
                                         reference circuit an interior optimum
```

### 6. The engine never ran out of gears

Terminal velocity came out at 371 km/h, which nothing on the grid reaches, and
0-300 km/h took 7.9 s against a real 8.4-10.6.  Top gear is a fixed ratio, so
past a certain road speed the crank is on the limiter and there is no more
drive whatever the drag says -- and that limit was missing.

With it (`PowerUnitProperties.rev_limit_speed`, 353 km/h):

| | before | after | real |
|---|---|---|---|
| terminal velocity, low wing | 371 km/h | 353 km/h | ~350 (gear limited) |
| 0-100 km/h | 2.23 s | 2.65 s | ~2.6 s |
| 0-200 km/h | 4.17 s | 4.90 s | ~4.6-4.8 s |
| 0-300 km/h | 7.87 s | 8.94 s | ~8.4-10.6 s |

It also produced a behaviour nobody wrote down: at minimum wing the car is
already on the limiter, so **DRS stops adding top speed** and only gets the car
there sooner.  That is exactly what happens at Monza.

### What the circuits fixed, measured

| | before | after | real |
|---|---|---|---|
| fuel effect | 0.010-0.020 s/kg | 0.022-0.030 s/kg | 0.024-0.041 |
| compound step S->M | 0.31-1.90 s | 0.60-0.81 s | 0.5-0.7 |
| compound step S->H | 0.66-4.05 s | 1.23-1.66 s | 1.0-1.4 |
| degradation, medium | -- | 0.13 s/lap | 0.08-0.12 |
| degradation, hard | -- | 0.08 s/lap | 0.05-0.08 |

The tyre numbers moved twice.  Narrowing the compound grip steps to match the
published lap-time offsets went too far at first, because a softer tyre gives
some of its raw grip back by running hotter -- so the *raw* step has to be set
against the *on-track* step, which is a clean 20:1 relationship in this model
and is how it is now calibrated.

Still off: a soft degrades at 0.30 s/lap where a real one does 0.12-0.20, so it
stops being the quicker tyre after about three laps rather than eight to
fifteen.  The ratio between compounds is right and the medium and hard land in
range; it is the soft's thermal penalty that is too steep, and it belongs with
the tyre thermal model rather than with the wear curve.

### What was measured and found to be a limit rather than a bug

**A marginal pass is knife-edge, and that is not a defect.**  Running the same
two-car race at five track resolutions, the winner changed:

```
  pace 0.86 vs 0.97   158 segs: no pass   223: pass   312: no pass   439: pass
  pace 0.80 vs 1.00   passes at four resolutions out of five
  pace 0.74 vs 1.00   passes at every resolution
```

The physics underneath is resolution-independent -- lap times converge to a
hundredth of a second -- and a decisive pace advantage always gets through.
What flips is a *marginal* pass, where a hundredth of a second at a detection
point decides whether DRS is available on the following lap.  Real races are
chaotic in exactly that way, so the finding is not that the model is wrong but
that a test built on a marginal pass measures the knife edge rather than the
overtaking model.  The overtaking tests now use a decisive gap and say so.

**Track width is dead data.**  `track_width` is carried through the definition,
the builder, the segments and the report, and nothing in `physics/` reads it --
the same shape of defect as the brake bias, still open.  It cannot simply be
wired in: a racing line flattens a 90-degree corner on a 9 m road to nearly
twice its centreline radius, and the engine's cornering speeds are calibrated
against the radius the car takes rather than the road's centreline.  Adding a
racing-line model means moving the grip calibration with it, which is Phase 12
work.  Until then the circuits state racing-line radii, and
`tools/design_circuits.py` says so at the top.

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

python tools/design_circuits.py            # the synthetic circuits and their character
python tools/author_circuits.py            # the real-circuit drafts and their verdicts
python examples/08_lap_time.py --validate  # the physics checks, per car
```
