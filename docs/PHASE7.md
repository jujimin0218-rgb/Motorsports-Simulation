# Phase 7 — Qualifying and the Race

**Status: complete.** A weekend now has a shape: practice, a knockout qualifying
session, and a race that starts from the grid qualifying produced — from a
standstill, over real distances.

---

## Delivered

| Item | Where |
|---|---|
| Qualifying | `race/qualifying.py` — knockout segments, runs, out-laps, elimination |
| The grid | `race/grid.py` — slots as distances, reactions, launches from rest |
| The weekend | `race/weekend.py` — one sky and one track surface across three sessions |
| Standing start | `race/session.py` — lap one begins at rest, behind the line |
| Effort | `driver/pace.py` — how hard a driver is pushing, and what backing off costs |

---

## Running it

```bash
python examples/17_race_weekend.py --laps 30 --rain 0.4
```

---

## Qualifying is run, not ranked

Every car goes out, warms a set of tyres on an out-lap, sets a flying lap that
counts, and comes back in. The slowest are eliminated and the rest go again.
Three things fall out of running it rather than sorting the field by pace:

**The track comes to them.** Rubber goes down as the session runs, so a lap in
Q3 is on a quicker circuit than a lap in Q1 — and every segment is quicker for
everybody, without anybody being given anything:

```
Q1: best 1:05.867 over 12 laps
Q2: best 1:05.713 over  8 laps
Q3: best 1:05.626 over  6 laps
```

**The out-lap matters.** A set of tyres comes out of the blankets below its
window and has one lap to get into it, and that lap is simulated. A compound
that warms up quickly is worth something here that it is not worth in a race.

**The weather does not wait.** The session asks which tyre suits the track it
has, so a shower during Q1 rearranges the grid.

The knockout grid is built from the back on each segment: whoever is still in
goes above whoever just went out, who in turn go above everyone eliminated
earlier. So the front of the grid is always the latest ordering and the back
never moves again — which is exactly how a real one is built.

---

## The grid is a set of distances

There is no grid penalty in seconds anywhere in this engine. A grid slot is a
place on the road behind the start line, two cars to a row with the second
column set back:

```
P1  8 m    P3 16 m    P5 24 m    P7 32 m
P2 12 m    P4 20 m    P6 28 m    P8 36 m
```

Getting off it is three real things:

1. **A reaction**, which is the one place in the engine where seconds are added
   to anything — because a reaction time *is* seconds before anything happens.
   Racecraft sets the mean, consistency sets the scatter.
2. **A launch**, which is the car's own force balance integrated from zero. A
   car with more traction gets away better; a heavy one gets away worse; a wet
   grid punishes everybody, through both the wet asphalt and the tread.
3. **The road to the line**, which the car in P20 has 72 more metres of than the
   car on pole.

```
driver             racecraft   react  P1 total  P20 total
Alex Rensen             0.96   0.196     1.411      3.958
Danil Orlov             0.74   0.268     1.483      4.030
```

Lap one then starts at whatever speed the car crossed the line at, so it is the
slowest lap of the race for everybody — which is what a real lap chart shows.

---

## Effort

Qualifying needed an out-lap, and an out-lap needed a way of saying "not
pushing". `effort` scales the grip a driver chooses to use, so backing off costs
lap time through the physics rather than by adding any:

```
effort 1.00: 1:06.788   wear 0.0308
effort 0.95: 1:07.540   wear 0.0296
effort 0.85: 1:09.802   wear 0.0256
effort 0.70: 1:14.658   wear 0.0199
```

That knob is also what Phase 8's tyre management is made of, and what
lift-and-coast will be made of later.

---

## The weekend, and why it is one object

Practice, qualifying and the race share **one weather model and one track
surface**. That is the whole of the wiring, and it is what makes the phases
inseparable:

* laps run in practice make qualifying quicker for everybody — measured, and
  tested: more practice produces a faster pole time;
* a Saturday shower is still draining when qualifying begins;
* qualifying sets the grid, and the grid is what the race launches from;
* the strategy for the race is decided from what the tyres did on *this* track
  in *this* condition.

Nothing in practice is timed. The point is that the laps happened.

---

## Not in this phase

* **Traffic.** Every car gets a clear lap in qualifying and clear air in the
  race. Tows, being held up, and the scramble at the end of Q1 all need cars to
  see each other — Phase 9.
* **The first corner.** The launch is real; what happens when twenty cars arrive
  at turn one together is not modelled.
* **Jump starts and penalties.** The reaction model has a floor below which a
  start would be a jump; nothing acts on it yet.
* **Ordering within a run.** Every car in a qualifying wave meets the same
  track, so the entry list cannot change anybody's lap. Who goes out when — and
  therefore who gets the best of the track — is Phase 9's, when cars share it.
