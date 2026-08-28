# Phase 10 — Weather and Environment

**Status: complete.** Weather is a process rather than a setting, the track
surface evolves from what happens on it, and running in the wet is two separate
physical problems that the engine keeps separate.

---

## Delivered

| Item | Where |
|---|---|
| Weather process | `environment/weather.py` — temperature, wind and showers that move |
| Track evolution | `environment/evolution.py` — rubber, marbles, water, the drying line |
| Wet grip | `tyres/wet.py` — water clearance and aquaplaning (rule 30) |
| Wet asphalt | `track/surface.py` — the surface penalty, separated from the tyre's |
| Wind | `environment/conditions.py` — headwind resolved against the track heading |
| Wet-weather ability | `driver/pace.py` — wet skill blended in as the track gets wetter |

---

## Running it

```bash
python examples/16_wet_weather.py --minutes 90 --seed 3    # a shower, and the drying line
python examples/17_race_weekend.py --rain 0.5              # a weekend it might rain on
```

---

## Two different things happen when it rains

Conflating them is how wet weather ends up as a lap-time multiplier, so the
engine keeps them apart.

**The asphalt gets slippery.** Wet asphalt has a lower friction coefficient
than dry asphalt with no standing water on it at all. That applies to every
tyre equally, saturates almost immediately — a damp track already has most of
the penalty — and lives in `TrackConditions`.

**The tyre has to get the water out of the way.** Standing water must be
evacuated through the tread in the time the contact patch is over it, and that
time shrinks as the car goes faster. Whatever is not evacuated lifts the tyre
off the road. That is what tread pattern is *for*, and it lives in `tyres/wet.py`:

```
clearance(v) = peak_water_depth × (v_ref / v)      for v > v_ref
grip         = 1 / (1 + unevacuated / aquaplaning_depth)
```

One model, and all of this follows from it:

| | rated depth | 2 mm at 200 km/h | aquaplanes in 4 mm above |
|---|---|---|---|
| Medium slick | 0 mm | 0.20 | any speed at all |
| Intermediate | 3 mm | 1.00 | 108 km/h |
| Full wet | 10 mm | 1.00 | 288 km/h |

Aquaplaning is a **speed limit**, not a coin flip: for any depth there is a
speed above which the tread cannot keep up, and it is solved from the clearance
model rather than tabulated.

### Which tyre is right, without anybody saying so

`compound_for_conditions` scores each compound by `peak_friction × wet_grip_factor`
— the grip it would actually deliver — and takes the best. Nothing is matched
by name:

| water | choice |
|---|---|
| 0.0 mm | Soft |
| 0.1 mm | Soft |
| 0.4 mm | Intermediate |
| 1.0 mm | Intermediate |
| 3.0 mm | Full wet |

Run the same three compounds over a lap and the ordering comes out the same
way, from lap times rather than from a score: on a dry track the medium is
1:07.0 and the full wet 1:15.8; at 0.3 mm the intermediate leads; at 1.5 mm the
slick is undrivable at 2:34 while the intermediate is unaffected; at 4 mm only
the full wet is still racing.

---

## Weather that moves

A wet race is a wet race because nobody knows whether it is going to rain, so
the weather is a process driven by the seeded RNG:

* **air temperature** is an Ornstein–Uhlenbeck walk around the forecast, with
  rain pulling the mean it walks around downwards — so a long shower cools the
  session by a bounded amount and it comes back;
* **track temperature** chases a target (air, plus sun, minus rain) through a
  first-order lag, because asphalt has thermal mass: a cloud cools the track
  long after it has gone;
* **showers** are two Poisson processes, one starting and one ending, so they
  have no fixed length — some pass in three minutes and some settle in;
* **intensity** relaxes towards its target, so rain arrives and clears over a
  couple of minutes rather than switching.

Three seeds, same 50% forecast, 90 minutes:

```
seed 11   dry until 80 min, then a downpour  (air 19.3-23.7, track 25.0-31.6)
seed 12   a passing shower at 60 min          (air 21.1-24.0, track 29.4-32.9)
seed 13   dry all afternoon                   (air 18.0-24.3, track 29.0-31.8)
```

Nothing schedules a shower for a dramatic moment. It either rains or it does
not.

---

## The track underneath

Every process is a rate applied to what actually happened — car-laps run,
seconds of rain fallen — and every one is integrated **in closed form**, so an
hour applied in one call and an hour applied in a hundred give the same track.
That is project rule 12 (resolution independence) applied to time instead of
distance, and there is a test for it.

```
 min   rain     water    wet  rubber   grip
   0   0.00    0.00mm     0%    0.00  1.000     20 cars running
  10   0.00    0.02mm   100%    0.55  1.006
  30   0.00    0.00mm     0%    0.91  1.055     rubbered in, +5.5% grip
  50   0.06    0.14mm   100%    0.90  0.903     shower
  60   0.13    0.37mm   100%    0.77  0.858     rubber washing away
  70   0.00    0.05mm   100%    0.89  0.967     it stops
  75   0.00    0.02mm    76%    0.93  1.019     the drying line appears
  80   0.53    1.14mm   100%    0.58  0.848     and then it really rains
```

The **drying line** is not drawn anywhere: cars throw water off the road where
they run, so the wet fraction falls even while the mean depth is still high, and
it falls *first where the road slopes*, because drainage is proportional to
gradient. The wet patch on a circuit is always in the same place and nobody
marked it as one.

**Marbles** collect *beside* the racing line, so they cost nothing to a car on
it — which is exactly why leaving the line is expensive, and why a car on it
gains grip through a session rather than losing it. Off-line grip is asked for
explicitly (`grip_multiplier(index, off_line=True)`) and Phase 9 will be its
first customer.

---

## Wind

The headwind is resolved against each segment's own heading, and only the
aerodynamic forces see it — wind changes the air the car is driving through,
not how fast the road is going past. Because drag grows with the square of
airspeed, a lap into a headwind down one straight and out of it down the next is
*slower* than the same lap in still air. The two do not cancel, which is why
wind direction shows up in real session data.

---

## What a wet-weather driver is worth

`wet_skill` blends into the driver's commitment as the track gets wetter. It is
not a bonus: on a wet track the question stops being "how much of the car's grip
can you use" and becomes "can you find where the grip is". A driver whose wet
skill matches their dry ability is unaffected either way, and the order changes:

```
driver             wet skill       dry       wet   order
Alex Rensen             0.95    66.800    82.972    1 -> 1
Hana Sugiyama           0.93    66.998    83.154    2 -> 2
Nico Bertone            0.88    67.026    83.962    3 -> 4
Iris Vandal             0.90    67.037    83.410    4 -> 3
```

---

## Calibration notes

Two numbers were re-derived during this phase and both were wrong in
instructive ways.

**The tread swung 75 °C within a lap** at the first calibration, because the
tread was given a 9 kJ/K heat capacity. Peaks reached 155 °C, the tyre took
permanent damage every lap, and the superlinear wear term fired at every apex —
which made a *better braker slower*, because braking harder cooked the tyres.
A tread capacity of 30 kJ/K, about four tyres' worth of rubber, brings the swing
to ±18 K, which is what a real one does.

**The surface water term grew without bound.** It has been re-cast as the wet
asphalt penalty, which saturates: a damp track has most of it, and deeper water
is dangerous because of aquaplaning, not because the road gets progressively
greasier.

**Standing water cools tyres hard.** Water carries heat away an order of
magnitude better than air, which is why a wet compound has a low working window
and why it destroys itself once the line dries. That is one extra conduction
term, and both behaviours come out of it.

---

## Not in this phase

* **Spray.** A car in another car's spray sees less grip and less air. Both need
  cars to know about each other, which is Phase 9.
* **Crosswind.** The along-track component is resolved; the lateral one, which
  loads the car sideways, waits for the suspension model in Phase 12.
* **Track-specific weather.** One sky over the whole circuit. Real rain arrives
  at one corner first.
* **Standing water off-line.** Water depth is per segment, not per line.
