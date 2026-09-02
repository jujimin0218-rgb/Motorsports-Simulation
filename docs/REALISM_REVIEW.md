# Realism Review — measuring the engine against the real thing

**Status: three passes done, then Phases 11 and 12. Nine defects fixed, two
capabilities added, two gaps left open and named -- one of which Phase 12 has
since closed.** A pass over the Phase 1–9 engine looking for places where the model
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
the same shape of defect as the brake bias.  Still open for the *circuit's*
width; the *car's* track width became live in Phase 12, where lateral load
transfer made it decide how much grip cornering costs.  It cannot simply be
wired in: a racing line flattens a 90-degree corner on a 9 m road to nearly
twice its centreline radius, and the engine's cornering speeds are calibrated
against the radius the car takes rather than the road's centreline.  Adding a
racing-line model means moving the grip calibration with it, which is Phase 12
work.  Until then the circuits state racing-line radii, and
`tools/design_circuits.py` says so at the top.

## Third pass: the consumables

With the circuits representative, the systems that act over a stint could be
measured against published figures for the first time.

### 7. A stint oscillated instead of settling

On the street circuit a set of softs produced lap times of 76, 92, 76, 76, 92,
77, 90 seconds -- alternating by sixteen seconds a lap, with the tread
temperature swinging between 133 C and 105 C to match.  That is not a tyre
going off, it is a limit cycle.

A lap is planned before it is driven, so it has to be planned from some tyre
temperature, and it was planned from the single reading taken at the timing
line.  That closes a feedback loop with a one-lap delay: a hot reading makes
the whole next lap slow, the slow lap cools the tyre, and the lap after that is
fast again.  Measured, the loop gain was almost exactly **-1.0** -- a period-two
cycle sitting on the stability boundary.

The tread temperature moves tens of degrees between a corner and the end of the
next straight, so one sample of it was never the right thing to plan a whole
lap on.  `TyreState` now carries a distance-weighted running mean and the plan
uses that; execution still uses what the tyre is actually doing.  The same
stint now settles and degrades at 0.16 s a lap.

### 8. A tyre was billed for working in its own window

`thermal_wear_factor` measured the temperature excess from the compound's
*optimum* and raised the whole thing to the overheating exponent.  Every
compound on every circuit was inside its working window -- 13 to 35 K below the
top of it -- and still being charged:

```
  soft    114.5 C, window top 127 C   ->  2.37x wear
  medium  104.6 C, window top 125 C   ->  1.50x
  hard     92.9 C, window top 125 C   ->  1.00x
```

The window is the range a compound is *built* to work across.  Charging it as
though it were overheating fell hardest on the softer compounds, which
naturally run nearest their own hot edge, and by a different amount at every
circuit -- so the durability ratio between compounds stopped being a property
of the compounds at all, swinging from 2.8 to 4.9 where the wear rates say
1.88.  Wear now rises gently inside the window and steeply above it, and the
ratio is back to 1.9-2.5 across circuits.

### 9. Wet tyres were perfect and then suddenly useless

`wet_grip_factor` returned exactly 1.0 for any depth the tread could evacuate
and then fell off a cliff.  An intermediate in 0.2 mm of water and one in 2 mm
lapped identically, and the tyre went from fine to undriveable between one
shower and the next.  Evacuation is a rate, not a switch: the closer the water
gets to what the grooves can move, the more of it stays under the contact
patch.  The loss now arrives gradually as the tread runs out of room and only
then turns into flotation, so the intermediate-to-wet crossover is a trade
rather than a cliff.

### What the third pass measured and found right

| | engine | real |
|---|---|---|
| ERS deployed per lap | 2.9-3.7 MJ | up to 4.0 MJ, and a car uses nearly all of it |
| fuel burn | 0.32-0.37 kg/km | 0.30-0.35 |
| pit stop loss | 19.4-20.8 s | 20-24 |
| stops over 305 km | 1-2 | 1-3 |
| green to rubbered track | -1.94 s | 1-2.5 s |
| grid spread, equal cars | 0-1.3% (rookie 3.8%) | ~1-1.5% |
| lap-to-lap variation, good driver | 0.08 s | 0.1-0.3 s |
| qualifying vs race-start trim | -3.0 s | 3-5 s |
| wind, averaged over direction | +0.04 to +0.77 s | a loss, growing with wind |
| stint length, medium | 129-197 km | 125-175 |
| stint length, hard | 194-284 km | 175-225 |

Wind is worth singling out.  Individual directions range from -0.30 s to
+1.58 s at the same wind speed, which looks alarming until it is averaged: over
the four cardinal directions the answer is always a loss and it grows with wind
speed, which is what a convex drag law on a closed lap has to give.  The spread
between directions is real -- it is why teams care which way the wind is
blowing.

Still off: a soft degrades at 0.26-0.30 s a lap on the two faster circuits
against a real 0.12-0.20, so it stops being the quicker tyre earlier than it
should.  The medium and hard land in range and the compound ratios are right,
which points at the soft's thermal behaviour rather than at the wear curve.

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

## Fourth pass: are the phases actually wired to each other?

The first three passes asked whether each mechanism was right on its own. This
one asks a different question: when an input changes, does the consequence
travel all the way through the phases that are supposed to carry it, and does
it arrive the right *size*?

The method is the same as before. Change one input, measure the lap or the
race at the other end, and compare against a published figure. A chain that is
merely connected is not enough — a chain can be live and still be wrong by a
factor of ten, and three of them were.

### The chains that were already right

Measured on `synthetic_proving_ground` unless stated, one input at a time:

| chain | change | result |
|---|---|---|
| aero → lap | wing 0.3 / 1.0 | +0.55 s / −0.05 s |
| power unit → lap | +10% power | −1.34 s |
| gearbox → lap | 8% longer gears | +0.01 s here, +0.56 s where the car reaches the limiter |
| chassis → lap | track 1.6→1.8 m / cg 0.30→0.42 m | −0.06 s / +0.38 s |
| fuel → lap | +50 kg | +1.19 s (2.4 kg per tenth) |
| compound → lap | S / H against M | −0.94 s / +0.18 s |
| wear → lap | 80% worn | +3.26 s |
| weather → lap | 5 °C / 40 °C / 8 m/s wind | −0.25 s / +0.19 s / −0.16 s |
| evolution → lap | green to fully rubbered | −1.95 s |
| rain → compound → lap | 0.6 mm → I, 2.0 mm → W | +25 s, +35 s |
| driver → tyre | tyre management 0.94 vs 0.75 | 3.76 vs 4.15 %/lap wear |
| ERS → budget | over a stint | 3.60 MJ deployed, 3.60 MJ recovered, store steady |
| reliability → race | normal stress | 1.3 mechanical retirements per 20 cars |
| neutralisation → strategy | green / VSC / safety car stop | 20.9 s / 12.5 s / 9.4 s |

The last two are worth singling out because they are the ones with a number
anyone can check. Formula 1 runs about one or one and a half mechanical
retirements a race, and a stop worth twenty seconds under green is worth about
twelve under a virtual safety car and about eight behind a real one. Neither
figure is written down anywhere in the engine: the first falls out of six
per-distance hazard rates, the second out of integrating the pit lane against
a field that is lapping more slowly.

The near-zero gearbox sensitivity was checked rather than assumed. On a circuit
where the car reaches the rev limiter, 8% shorter gears cost 0.56 s and cap the
top speed at exactly the gear ceiling; on the proving ground the car tops out
at 300 km/h against a 350 km/h ceiling, so the gearing has nothing to do.

### Three chains that were live but wrong by a lot

**Tyre temperature was far too punishing away from the window.** Being 40 K
cold cost 26.6 s a lap. A real out-lap on cold tyres costs 5–15 s. The falloff
term was carrying the whole of it, so it was set from what being out of the
window costs on the road rather than from a curve shape: `grip_falloff` 0.16 →
0.10, which gives +1.2 s at 15 K cold, +2.3 s at 20 K and +12.4 s at 40 K.

**Dirty air was worse than any real car's.** A car 0.8 s behind was losing
1.92 s a lap. That cannot be true: cars run in DRS trains, half a dozen of them
nose to tail for a whole stint, and at 1.92 s a lap the train would break up on
its own within two laps. The downforce loss was a pre-2022 number. Recalibrated
from the lap-time cost instead — losing one per cent of downforce is worth
0.09–0.13 s a lap here, measured — `peak_downforce_loss` 0.50 → 0.13 and
`downforce_scale` 0.90 → 0.70. That puts a following car between the two
figures the FIA published for the ground-effect regulations (18% of downforce
gone at ten metres, 4% at twenty) and leaves following worth a few tenths,
which is what makes a train possible. The tow was already right: a car sitting
right behind another gains 10–15 km/h, and a qualifying tow at a power circuit
is worth three or four tenths.

**Damage made a car faster.** Damage was modelled as a smaller wing. But
`CdA = CdA₀ + k·ClA²`, so taking downforce area away takes induced drag away
with it — and on a power circuit a trimmed-out wing is exactly what the car
wants. A fully damaged car was 1.06 s *quicker* with 27 km/h more top speed. A
broken wing is not a trimmed wing: it is a bluff body with the flow separated
behind it, so the downforce is gone and the drag is not. The drag is now pinned
to what the intact car had plus a penalty, with the zero-lift term absorbing
whatever the smaller wing no longer induces. Damage now costs 1.0–4.7 s
depending on level and circuit, and always costs top speed.

### The chain that is genuinely missing, and why it was not faked

Following costs lap time now, correctly. It does not cost the tyres, and in a
real race it costs the tyres more than it costs the lap. Measured over eight
laps on mediums:

| | lap 1 → lap 8 | tread | wear |
|---|---|---|---|
| clean air | 1:29.30 → 1:30.25 | 105.1 °C | 3.64 %/lap |
| 1.0 s behind | 1:29.46 → 1:30.38 | 104.8 °C | 3.60 %/lap |
| 0.5 s behind | 1:29.60 → 1:30.50 | 104.6 °C | 3.56 %/lap |

The lap-time column is right. The temperature column points the wrong way: a
car in dirty air comes in *cooler*.

The reason is structural rather than a wrong constant. Tread heat is modelled
as `friction force × speed`, and in dirty air the car corners more slowly with
less grip, so both terms fall. What actually overheats a tyre is the third term
neither of them stands in for: **slip velocity**. A driver chasing somebody
does not accept the slower corner — they arrive on the braking point they
learned in clean air, the tyre goes past its limit, and the difference comes
out as sliding and therefore as heat.

That needs a slip model, which is the same thing the deferred slip-angle and
yaw work needs, and it is why nothing was done about it here. The alternative
was a tuned multiplier on tyre heat keyed to the wake, which would reproduce
the table and break project rule 6 — a lap-time correction wearing a physics
costume, and one that would then have to be re-tuned against every circuit.
The honest state is a chain that carries the aerodynamics correctly and does
not yet carry the thermal consequence, which is written down here rather than
papered over.

### One knob that was connected to nothing

`suspension.roll_stiffness_front` was carried in the config and read by no
code. A calibration parameter that changes nothing is a broken connection like
any other, so it is now wired to the thing an anti-roll bar actually does: it
splits the lateral load transfer between the axles, and each axle is charged
for its own share.

The result is the one a setup engineer would expect, and it was not put there
by hand. The grip penalty is concave in how far the load has moved, so an axle
taking more than its share loses more than the other end gains back — total
grip therefore peaks exactly where the distribution matches the load split and
falls away on both sides of it:

| roll stiffness front | lap |
|---|---|
| 0.45 (matches the load split) | 1:29.915 |
| 0.55 (the default, mild understeer) | +0.016 s |
| 0.70 (stiff front) | +0.161 s |

A bar is not free lap time, in other words, and the reason a team moves it
anyway is the balance it buys — which is the part that needs the slip-angle
model Phase 12 still does not have.

### One contract that was wrong rather than one number

`compute_lap_time` documented itself as "the lap the car is capable of", and a
driven qualifying lap beat it by 1.5–1.8 s. Nothing was exceeding the tyres:
the limit lap was computed with ERS shut, and there was no way to ask for it
otherwise. Both halves are now fixed — the function takes `ers_power` and
`drs_zones`, and the docstring says the default is the *chassis* limit and why
(deployment is a decision, not a property, and the store holds one lap's worth
of it). With ERS deployed the ordering is the one it should always have been:

```
chassis limit    1:29.40
driven lap       1:26.84
deployed limit   1:26.77
```

A test now pins that ordering. If the driven lap ever fell outside it, the
driver would be either leaving ERS on the table or exceeding the grip the tyres
have, and both are bugs rather than driving.

---

## Making it twice as fast without changing a single answer

Optimisation on a simulator is only worth anything if the simulator still says
the same thing afterwards, so the rule here was strict: **every answer bit for
bit identical**. Ninety of them — the limit lap for three cars at two wing
levels on three circuits on three compounds, plus four laps of a driven stint
and the tyre state it ends on — were recorded to full precision first and
re-checked after every change. All ninety matched at every step.

That rules out the usual tricks. `cos(atan(g))` is `1/sqrt(1+g²)` in
mathematics and not in floating point; `m·a·h/L` and `a·(m·h/L)` differ in the
last bit, and a solver that runs to a tolerance is exactly where the last bit
shows. Both were tried and both were reverted. What was left is the honest
kind of speed: doing the same arithmetic fewer times.

| | before | after | |
|---|---|---|---|
| speed profile | 758 ms | 361 ms | **2.10×** |
| driven lap | 841 ms | 424 ms | **1.98×** |

Where it came from, largest first:

**Work thrown away.** The speed profile calls the longitudinal balance 43,000
times a lap and reads one number off the result — but the result was a frozen
dataclass wrapping another frozen dataclass. The same was true of cornering:
the corner-speed bisection asked ten times a corner for a `LateralCapability`
and took the acceleration, having paid for a friction-coefficient lookup it
never read. Both are now a core returning plain floats with the dataclass built
only for callers who want it, which is the same split `normal_loads` got.

**The same question asked three times.** `longitudinal_forces` computed the
downforce, then the traction solver recomputed it from the same speed and wing,
then the braking solver recomputed it again. Likewise the road's trigonometry:
every solver settles a loop against a *fixed* piece of road, so `cos(pitch)`,
`cos(bank)` and `sin(bank)` are worth one evaluation per query rather than one
per pass. Both are computed once and handed down.

**Constants recomputed in loops.** Gravity, the aero balance, the mass
properties, the tyre model, the combined-grip exponent and the cornering
reserve were all being looked up inside solver iterations that could not change
them.

**A wing that does not move.** `ClA` and `CdA` depend on the wing level and
whether DRS is open, and on nothing else, so the whole engine only ever needs
two pairs of numbers per car — and was recomputing them 165,000 times a lap
through a `lerp` and a `clamp`. They are now cached on the aero model, and the
force balance takes both from one dynamic pressure instead of two.

**Three properties made into attributes.** `Vehicle.config`, `.mass` and
`.wing_level` are fixed for the life of a vehicle — `with_setup` builds a new
one — and were reached through a property several hundred thousand times a lap.
They are now bound in the constructor, like the four models beside them already
were.

Nothing here is a physics change and nothing here is an approximation. The
tests that pin the numbers are the same tests, and they pass on the same
numbers.

---

## Running it

```bash
pytest

python tools/design_circuits.py            # the synthetic circuits and their character
python tools/author_circuits.py            # the real-circuit drafts and their verdicts
python examples/08_lap_time.py --validate  # the physics checks, per car
```
