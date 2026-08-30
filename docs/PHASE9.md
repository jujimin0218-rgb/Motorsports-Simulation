# Phase 9 — Overtaking and Defence

**Status: complete.** The cars can finally see each other: dirty air, the tow,
DRS, being held up, and getting past.

---

## Delivered

| Item | Where |
|---|---|
| The wake | `race/wake.py` — dirty air and the tow, from one hole in the air |
| Racing | `race/traffic.py` — who is in front, how close, and whether it can be fixed |
| The interface | `simulation/traffic.py` — what the lap simulation asks, and nothing more |
| A lap in pieces | `simulation/lap.py` — `LapDrive`, so a field can be stepped together |
| Per-segment aero | `physics/speed_profile.py` — the plan is made in the air the car is in |
| A live trace | `race/timing.py` — where everybody is now, not just at the line |

---

## Running it

```bash
python examples/18_racing.py --track synthetic_power_circuit   # a tow does the work
python examples/18_racing.py --track synthetic_street_circuit  # nowhere to go
```

---

## One hole in the air

Two effects, opposite in sign, and both of them are the same thing:

**Dirty air.** A wing works by bending clean air. Behind another car the air is
already bent, so the wing makes less downforce — and downforce is what a
Formula 1 car corners on.

**The tow.** The same hole is a hole: less air to push out of the way, so less
drag. On a straight that is speed.

```
downforce_loss(gap) = 0.50 · exp(−gap / 0.90)      everywhere
drag_saving(gap)    = 0.14 · exp(−gap / 0.60)      on the straights only
```

Both decay with the **time** gap, because the wake is convected downstream with
the car: at 300 km/h a second is 83 metres and at 100 km/h it is 28, and the
aerodynamic effect is much the same. That is also how the sport talks about it.

The tow only counts where the cars are lined up. Two cars are nose to tail down
a straight and side by side through a corner, so the hole in the air is only
useful in one of those places. The turbulence is not so fussy — it fills the
corner too, which is exactly why following is hard and slipstreaming is not
enough to fix it.

Neither is a lap-time penalty. They are multipliers on two aerodynamic
coefficients and the rest of the engine works out what that costs — which comes
out different at every circuit, because drag scales with speed squared and
downforce matters more the faster the corner.

---

## The plan has to be made in the air the car is in

This was the hard part, and the same lesson as Phase 5's frozen grip in a new
disguise.

A car following another has less downforce, so it has to brake earlier. Capping
its speed at the apex instead does not work: by then it is too late to slow
down, and the car comes out of the corner **faster** for having had less grip.
Worse, the tow makes it quicker down the straight than its own plan expected, so
it arrives at the braking point too fast as well.

So the speed profile itself now takes per-segment `downforce_factors`,
`drag_factors` and `drs_zones`, and the lap is planned in the air the car will
actually meet — estimated by walking its own clean-air profile to see where it
will be and when.

And then the lap is *driven* in the air it was planned in. That second half is
as important as the first and is easy to miss: take the aerodynamics from a
live query at each segment instead, and a car that planned a clean-air lap and
met dirty air keeps the plan while banking the drag saving it never planned
for. Every car in the field comes out quicker for being raced, which is the one
thing the wake must never do. Plan and execution use the same numbers; what the
traffic model says while the lap is being driven decides only what the car is
*not allowed* to do — how fast the car in front will let it go, and whether it
is off the racing line.

---

## Stepping a field together

A lap at a time cannot represent a position change. A car that is overtaken a
third of the way round has already driven the rest of the lap, so it arrives at
the line still in front and the pass undoes itself next lap.

`LapDrive` fixes it: the driving loop became a generator that pauses forty times
a lap, and the session advances whoever is furthest behind on the clock. Nobody
is ever simulated past a moment the cars in front of them have not reached, so
"who is in front" is never a guess. The physics is the same physics — a stepped
lap and a whole one agree to the last bit, and there is a test that says so.

That also makes the causality work for lapped traffic: anybody physically in
front of a car started their lap before it did, including a car a lap up the
road, so their trace already exists to be raced against.

What they are raced against is the timing tower, which now takes each car's
progress as it is driven rather than only at the line — telling whether one car
is half a second behind another needs to know where both of them were, and that
changes every few metres. It is also where the honesty of a pass comes from: a
car in the middle of its stretch has run past everybody else's clock, and where
they are from there is a guess extended at the speed they were last doing. Good
enough for the air. Not good enough to decide a position on, so positions are
only decided where the record actually reaches.

---

## Getting past

There is no overtaking probability. There is a gap, and it shrinks when one car
is quicker than the other:

* **a car cannot be driven through.** Where a move is not on, the follower is
  held to the car in front's pace — and in its wake it has lost the downforce it
  would need to stay that close anyway, so it falls back on its own.
* **a move is on** where the road is wide and quick *and* the attacker has the
  speed advantage the defender's racecraft demands. Against a driver who leaves
  the door open that is nothing; against a better racer it is several metres a
  second, because a defender takes the line the attacker wants.
* **an overtake is not an event to be detected.** It is the moment a car that
  was in front stops being in front, so that is what is looked for, and every
  position change goes through it. Both halves have to happen — clearly behind,
  then clearly ahead, by more than a car's length — because two cars nose to
  tail trade the odd inch back and forth all lap without either of them having
  overtaken anything. And it is asked of every car's position rather than of
  whoever is under the nose right now, because the moment a move completes is
  exactly the moment the car being passed stops being the car in front.
* **committing to a move means leaving the racing line**, and Phase 10 put the
  marbles there. An attempt costs something, and nobody had to price it.

What a fight costs, measured over ten laps against exactly the same two cars in
exactly the same race with the racing switched off — same grid, same launch,
same tyres, and the only difference being whether they can see each other:

| | chaser barely quicker | chaser decisively quicker | passes |
|---|---|---|---|
| Power circuit | −2.48 s | −0.93 s | 2 |
| Proving ground | +0.75 s | +1.52 s | 1 |
| Street circuit | **+7.34 s** | **+29.49 s** | **0** |

Two things fall out of that table and neither was put there. **Being stuck costs
time, and it costs most where there is nowhere to pass.** At the street circuit
the decisively quicker car never gets by at all and finishes half a minute down
on the race it would have had alone — the more pace it has, the more of it it
wastes. At the power circuit the same fight *gains* time, because the car gets
past inside two laps and banks the tow that got it there on the way.

And **the two effects do not cancel at the same place.** The proving ground is
quick and open and still costs the chaser time, because its corners are fast
enough that the lost downforce bites harder than the straights pay back; the
power circuit's straights are long enough that they do. Nothing in the engine
knows which circuit is which. It knows that a tow needs a straight and that
dirty air does not, and the rest is the same force balance as always.

One earlier guarantee had to be narrowed to fit. Phase 6 asked that adding a car
to the field change nobody else's race, which is how it checks that randomness
does not leak between competitors. From here that only holds with the racing
switched off, because a bigger field really does put somebody in somebody's way.
So the question is asked where it can still be answered, and the opposite is
asserted where it cannot.

---

## DRS

The gap is measured at a **detection point**, 150 m before the zone — not at the
zone. Being within a second at one and not the other is a real thing that
happens, and it needs the two to be different places. Within a second, the flap
opens for the length of the zone, and the aero model already knew what an open
flap does.

The same rule at every circuit, and worth what the circuit's zones are worth:
two long ones at the power circuit, one short one at the street circuit.

---

## Not in this phase

* **Side by side.** The model has no such state: a car is in front or behind.
  A fight that in reality is resolved over several corners with the cars
  alongside is resolved here as a sequence of passes, which is why two evenly
  matched cars swap places every few laps rather than running door to door. A
  driver who has just been passed at least has to regroup for a lap before
  trying again, which is real and is what keeps it from oscillating.
* **Contact.** Nobody hits anybody. Collisions, and the penalties that would
  make a bad move cost something, are Phase 11.
* **Spray.** A car in another's spray sees less grip and less air; the wake
  model handles the air but not the water.
* **Blue flags.** A lapped car is raced like any other rather than being
  required to move over.
* **The first corner.** Twenty cars arriving at turn one together is a
  qualitatively different problem from two cars racing, and it is not modelled.
* **Team orders and racing a rival's strategy.** The strategist reads the track
  and its own car, not the timing screen.
