# Phase 12 — Advanced Physics

**Status: the two that changed answers are done.** The gearbox replaces Phase
2's stand-in, and load now transfers across the car as well as along it. What
remains is listed honestly at the end rather than half-built.

---

## Delivered

| Item | Where |
|---|---|
| The gearbox | `vehicle/gearbox.py` — ratios, the engine curve, shift losses |
| The power unit through it | `vehicle/power_unit.py` — no more torque cap |
| Lateral load transfer | `vehicle/mass.py`, `physics/grip.py`, `physics/lateral.py` |
| Calibration | `core/config.py` — `suspension`, `powertrain.drivetrain_efficiency` |

---

## The gearbox, which Phase 2 promised

Phase 2 stood in for the whole powertrain with a peak wheel torque and a flat
cap, and said in its own docstring that Phase 12 would replace it. Replacing it
means three things a single number cannot give.

**Force is not flat within a gear.** A power unit makes its power over a narrow
band of crank speed; the gear set is how a car that has to go from 60 km/h to
350 km/h keeps it there. Between shifts the engine climbs its curve, so tractive
force rises and falls.

**Top speed is a gear, not a balance of forces.** Past the ratio's limit there
is no drive whatever the drag says. That is why a Formula 1 car at Monza sits on
the limiter rather than creeping towards a terminal velocity — and it produced a
behaviour nobody wrote down: at minimum wing the car is *already* on the
limiter, so DRS there adds no top speed at all and only gets the car there
sooner. Which is exactly what happens at Monza.

**Shifting costs time**, and it costs a short gear a real share of itself. A
fixed forty milliseconds is 4.3% of a second gear that is over in under a second
and nothing at all to a top gear held down a straight, so it is charged where it
is paid rather than averaged into an efficiency.

The rising side of the power curve turned out to matter far more than it looks.
Force at a road speed is `P / v` whatever the ratio, so the gear that wins is
simply the one putting the engine nearest its power peak. With a curve that was
too flat low down, the model cruised around in eighth at 120 km/h. Given a real
one it picks third, which is what telemetry shows:

| | engine | real power unit |
|---|---|---|
| power at 6 000 rpm | 41% | ~45% |
| power at 8 000 rpm | 65% | ~65% |
| power at 10 500 rpm | 100% | 100% |
| power at 15 000 rpm | 93% | ~93% |
| gear at 120 km/h | 3rd | 3rd |
| gear at 200 km/h | 6th | 6th |
| gear at 300 km/h | 8th | 8th |

And the car it produces still lands where a real one does: 0-100 km/h in 2.65 s,
0-200 in 4.90, 0-300 in 8.90, gear-limited at 350 km/h.

Two stand-ins went with it. `peak_wheel_torque` was never what stopped the car
off the line — the rear tyres are, and that limit already existed. And
`drivetrain_efficiency` now means the mechanical loss alone, because the other
half of what it used to lump together is the shift loss, which is modelled.

---

## Load transfers across the car, not just along it

Traction has been an axle question since Phase 2 and braking since the first
realism pass. Cornering was not, and that left the model overstating cornering
grip and `track_width` and `cg_height` doing nothing at all in a corner.

Friction coefficient falls with load, so a given total load buys less grip
**split** unevenly across four tyres than shared evenly. Cornering does exactly
that split:

```
transfer = m * a_y * h_cg / track
```

and what the tyres have left is the sum of `N^(1-k)` over the four of them
rather than four times the even share. So cornering costs grip simply by
cornering, and the cost grows with lateral acceleration until the inside wheels
lift and stop contributing at all — which the model reaches by itself.

| | cost |
|---|---|
| at 2 g | 0.7% of cornering grip |
| at 4.6 g | 1.3% |
| a narrow car (1.45 m track) | a further 0.3% |
| a high centre of gravity (0.40 m) | a further 1.1% |

Modest, and real, and it is what makes a wide car with a low centre of gravity
corner better than a narrow tall one carrying the same downforce.

---

## Paying for it

Both additions sit in the hottest paths in the engine -- the corner solver runs
for every segment of every lap, and the drive force is asked for tens of
thousands of times a lap -- so both had to be made cheap as well as right.

The gearbox replaced one division with a search over eight ratios, which cost
9.2 microseconds a call.  The ratios do not change, so the limit speeds and
shift losses are worked out once; the gears the engine can still turn are the
tail of a sorted list, so the lowest available one is a bisection away; and
force falls off either side of the power peak, so walking up from there and
stopping when it stops improving finds the best gear without trying the rest.
2.1 microseconds, same answer.

The load transfer was worse, and for a subtler reason: charging it inside the
loop that settles the cornering acceleration made that loop converge more
slowly, so a one percent correction cost fifty percent more work.  It is now
charged once, on the settled answer.  Re-settling around it would move the
result by a hundredth of a percent.

---

## Not done, and why

`suspension.roll_stiffness_front` is carried but not yet used: it is what an
anti-roll bar change actually alters, and using it means a **balance** model —
understeer and oversteer as a front-versus-rear grip split — which needs the
tyre model to distinguish the two axles' slip. That is the same piece of work as
slip angle and yaw, and half of it would be worse than none.

Also deferred, for the same reason: ride height and its effect on the floor,
the differential, and a transient tyre model. Each of them wants a car that
knows its attitude, and this one still treats a corner as a quasi-steady
balance of forces. That is a defensible model — it is what a lap-time
simulation is — and the honest thing is to say where it ends.

The other open item is not physics at all: the six real benchmark circuits of
project rule 10 still need real geometry. `tools/author_circuits.py` holds the
pipeline and the acceptance checks; what it is missing is survey data.
