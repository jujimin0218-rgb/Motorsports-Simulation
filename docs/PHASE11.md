# Phase 11 — Race Events

**Status: complete.** Cars break, hit each other and spin, and race control does
something about it. The race is no longer a procession in which everybody
reaches the flag.

---

## Delivered

| Item | Where |
|---|---|
| What went wrong | `events/incident.py` — one currency for failures, contact and spins |
| Reliability | `events/reliability.py` — a hazard per kilometre, per system |
| Contact | `events/collision.py` — a hazard per lap spent fighting |
| Race control | `events/race_control.py` — the flag state machine |
| The race reacting | `race/session.py` — retirements, neutralised laps, bunching |
| Calibration | `core/config.py` — `reliability`, `incidents`, `race_control` |

---

## Running it

```bash
pytest tests/test_race_events.py
python examples/19_race_events.py
```

---

## What happened, and what was done about it

The separation the whole phase rests on. **Incidents happen to cars. Flags are
a decision about the circuit.** The same failure produces a local yellow at one
point on the lap and a red flag at another, and none of that belongs in the
failure.

So `sample_failure` says a gearbox let go, and where the car stopped — and
stops. `RaceControl.assess` decides whether that needs recovering, and if so
whether the answer is a yellow, a virtual safety car, the real one, or stopping
the race. Neither knows the other's business.

---

## Failures are a hazard, not a coin flip

```
P(failure over a distance) = 1 - exp(-rate * distance * stress)
```

A rate **per kilometre**, not a probability per lap. That is not a detail. A
per-lap probability would make Monaco's 78 laps twice as hard on a car as
Spa's 44, when Spa is the longer race by distance and much the harder one on a
power unit. As a hazard the answer is the same however finely it is sampled,
and a long circuit is genuinely harder because the car covers more ground.

Each system carries its own rate and its own **stressor** — the thing that makes
that part work hard, taken from the lap the car actually drove:

| system | worked by |
|---|---|
| power unit | fuel burned per kilometre |
| gearbox | torque through it, so the same |
| brakes | energy recovered per kilometre, which happens under braking |
| cooling | the ambient air it has to reject heat into |
| hydraulics, suspension | how hard the driver was leaning on it |

So a hot race breaks more cars, a power circuit breaks more engines, a
heavy-braking circuit breaks more brakes, and a driver managing the car
genuinely sees the flag more often — none of it written down anywhere.

---

## Contact needs somebody to fight

Contact is a hazard **per lap spent within fighting distance**, not per lap. A
car in clean air does not hit anybody, so a race where nobody can pass produces
contact and a processional one does not.

Two things scale it and both are real. **The first lap**, because twenty cars
arriving at the first corner together is where a disproportionate share of a
season's contact happens and no per-lap average reproduces that. And **who is
fighting** — racecraft and risk management, from *both* cars, because contact
takes two.

What it costs is drawn separately from whether it happened, because they are
separate questions. Most contact is a broken front wing; some of it ends a
race; and some of it leaves something on the circuit that has to be picked up.
That last one is not the same as retiring: a front wing shed at speed brings out
a virtual safety car while its owner drives on to the pits, and conflating the
two loses the most common reason a modern race is neutralised.

---

## A safety car lap is a different activity

Not a slow racing lap. Modelling it by scaling one would get the consumables
wrong in both directions, so it is not modelled that way. What actually happens
is that the car does far less work: drag and tyre forces both fall with the
square of speed, so a lap run at `1/f` of racing pace does about `1/f²` of the
work. Everything else follows from that one line — the fuel saving, the tyres
cooling rather than merely wearing more slowly, and the battery filling up.

One thing had to be added deliberately. A driver behind the safety car weaves
and brakes precisely to keep temperature in the tyres, because a restart on cold
ones is where races are lost. Coasting the whole neutralisation instead left the
field so cold that the first green lap came out thirty seconds off the pace.
With the tyre work in, the same restart looks like this:

```
  laps 1-4   89.4 s     racing
  laps 5-9  138.5 s     behind the safety car, 1.55x
  lap  10    95.5 s     green, and six seconds off on cold tyres
  lap  11    91.7 s
  lap  12    89.8 s     back to pace
```

Nobody wrote that recovery. It is the tyre model coming back up to temperature.

---

## Where the numbers come from

Everything below is calibrated against the 2023 season and checked on every
test run:

| | engine | real |
|---|---|---|
| mechanical retirement, per car | 6.5% | 6.8% |
| contact retirement, per car | 5.8% | 6.1% |
| any retirement, per car | 11.9% | ~13% |
| races with a safety car | 43% | 42% |
| races with a virtual safety car | 51% | 50% |
| races with a red flag | 14% | 14% |

The flag shares are not free parameters either: with about one and a half cars a
race stopping somewhere they have to be recovered from, they are what makes the
three frequencies come out. What is left over is recovered under a local yellow,
which is the commonest answer of all.
