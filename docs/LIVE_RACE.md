# The live race

The engine decides a race in the **distance domain**: a speed profile gives a
lap time, a driver model perturbs it, and `race/traffic.py` prices overtaking on
top of that.  It is fast, it is deterministic, and it is the right shape for
simulating a whole season.  What it is not is a race you can *watch*: the 2D
world beside it (`f1_race_engine/world/`) says so in its own docstring —
"nothing generated here feeds back into a lap time" — because cars are *placed*
where the distance model says they are.

This is the other thing.  A field of cars that are **driven**, in two
dimensions, at sixty frames a second, by a driver model whose entire interface
to the world is a steering angle, a throttle and a brake.  Lap times, positions,
overtakes, mistakes and the order at the flag are read off that loop.  There is
no drawer marked "result" for anything to reach into.

It lives in `frontend/src/race/` and runs in the browser, because sixty frames a
second of physics for twenty cars is not something that can come down a wire.
The circuit and the field still come from the game: the round's surveyed
geometry, the teams' cars and the drivers' ratings.  Everything after lights out
is the simulation.

## The pieces

| module | what it owns |
|---|---|
| `geometry.ts` | the circuit resampled for planning: headings, curvature, corners, and the projection between a place on the plane and a distance round the lap |
| `lines.ts` | the racing line, and the lines that come off it |
| `physics.ts` | one car, as a thing that obeys forces |
| `ai.ts` | one driver, who can only steer, brake and accelerate |
| `race.ts` | what is true of the circuit rather than of one car |
| `scenery.ts` | what is beside the road |
| `render.ts` | drawing it, and three cameras |

## The racing line

A car does not drive the middle of the road.  It goes to the outside before a
corner, cuts to the inside at the apex and lets the car run back out at the
exit, because that path has the biggest radius the road allows and speed goes as
the square root of radius.

Nothing here is told to do that.  The solver minimises

```
J = sum_i w_i (kappa_i + n''_i)^2      subject to  |n_i| <= limit_i
```

over the lateral offset `n` of every sample — the straightest path the road can
hold — and out-in-out is simply what the answer looks like.

Three things had to be right for that to be true, and each was wrong first:

* **Differentiating properly.** The obvious relaxation — move each point toward
  the midpoint of its neighbours — is the gradient of *length*, not curvature.
  On a closed loop that is curve-shortening flow, and the line collapses onto
  the inside edge of the road for the whole lap.  The real gradient touches
  three terms and gives a fourth-order (biharmonic) system, which has a periodic
  solution and whose answer is the shape a driver would recognise.
* **Coarse first.** A racing line is almost all long wavelength.  Relaxed on the
  fine grid alone the offsets barely leave zero.
* **Never tighter than the road.** The linearised objective thinks a constant
  offset is free, so on a long constant-radius corner the line parks against the
  inside kerb and comes out with a *smaller* radius than the centreline —
  slower than driving down the middle and at the absolute limit for two hundred
  metres.  Measured on a twenty-car race, that one corner produced half of every
  incident on the lap.  `guardWideCorners` states the invariant and enforces it.

The apex is then moved for the two things a driver is taught: **what follows**
(a corner onto a long straight is worth entering later, so the car can be
straight and on full throttle sooner) and **which way the radius is going** (a
corner that tightens is apexed late; one that opens out, early).

### The derived lines

Racing is not one line.  Each of these is a real path with its own curvature,
and because a driver builds its speed plan from whichever line it is actually
on, the *cost* of each is never written down anywhere — a tighter exit radius
simply is a lower exit speed.

* **defend** — the inside taken before the braking zone, early apex, tight exit.
* **dive** — braking as deep as the road allows, very late apex, running wide on
  the way out.  Fast in, compromised out.
* **switchback** — give up the entry, get the car turned early, be on the
  throttle first and cross back over at the exit.
* **outside** — round the outside.  It usually does not work.  Sometimes it does.

## The car

A single-track (bicycle) model with load transfer, aerodynamics, a friction
ellipse and a tyre that falls away past its peak.  Understeer, oversteer,
lock-ups, wheelspin and spins are not states the code switches into — they are
what the integrator does when it is asked for more than the tyres have.

The things that had to be fixed, because each of them produced a field that
destroyed itself:

* a tyre at its longitudinal limit was left with *exactly zero* lateral grip, so
  every car spun on the throttle;
* only the front axle could lock, so every hard stop spun the car;
* the driver's own estimate of its car ignored tyre load sensitivity, so it
  believed it could brake thirty per cent harder than it could;
* and the estimate assumed a straight braking zone, so into a corner that
  follows a bend it arrived a hundred km/h too fast with no grip left to do
  anything about it.

## The driver

Each driver scans the line it is on, computes from **its own car's** mass,
downforce and tyre state how fast each piece of road can be taken, and works
backwards to find where it has to brake.  Two cars brake in different places
because their numbers are different — which is the only reason anything here is
ever quicker than anything else.

* **Steering** is a three-term path follower: the curvature feed-forward a car
  of this wheelbase needs, plus heading error, plus cross-track error.
* **The friction circle** governs both pedals.  Trail braking is the brake
  coming off as the car turns in, because the tyre has one budget.
* **Overtaking is a choice of line** and then driving it.  Whether it comes off
  is settled by the physics: whether the car actually stops in time, whether it
  is alongside at the apex, whether it comes out with more speed.
* **Commitment** is one number.  At one, the driver brakes where the car can
  stop; above one, where they *wish* it could — and the understeer, the wide
  exit and the trip through the gravel are what happens next, not outcomes
  picked from a list.

## Watching it

Three cameras: the whole circuit, a chase camera, and onboard.  Clicking a car
or a row in the timing tower switches to it.

The picture is drawn from the *same* surface model the cars are driving on,
because a picture that disagrees with the physics is worse than no picture —
a car slides onto what looks like asphalt and behaves as though it were gravel,
and nobody watching can tell which half is wrong.

## Where it stands

Verified against the engine's own reference:

* a lap of Bahrain comes out at **1:30.2** against a real 2024 pole of 1:29.2;
* a solo car runs eight laps with **no** track-limits excursions;
* twenty cars with varied ratings run eight laps **without a single incident**
  when nobody stops;
* thirteen of the fourteen corners at Bahrain produce a genuine out-in-out line
  with a late apex, and none of them is tighter than the road.

**Known rough edge.** Attrition around the pit window is still higher than it
should be: a typical eight-lap race finishes ten to sixteen of twenty cars.
Every retirement is physical — a car that ran wide, reached a barrier and
stopped — and the trigger is traffic around cars rejoining at pit-lane speed.
Nothing is scripted; it is a calibration problem, not a modelling one, and the
tooling to chase it is in the commit history.
