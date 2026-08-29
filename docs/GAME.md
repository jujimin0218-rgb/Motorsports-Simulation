# The season management game

A Formula 1 season on top of the race engine: you run a team, sign the drivers,
spend the research, set the strategy, and the races are simulated rather than
rolled for.

## The one rule

**The game does not simulate races.** It assembles the inputs, hands them to
`f1_race_engine`, and reads the result back. There is no second, simpler race
model anywhere in it, and there is no place where a lap time is adjusted after
the engine has produced one.

```
React + TypeScript
      |
   FastAPI            backend/app/api/
      |
 Game services        backend/app/services/    season, money, research, jobs
      |
  Race adapter        backend/app/adapters/    a team's ratings -> a real car
      |
  f1_race_engine      the physics, untouched
```

Every arrow points down. The engine knows nothing about the game; the adapter
knows nothing about HTTP; the API decides nothing.

## Where the seam is

A team's car is six ratings between 0 and 1. The engine wants a `VehicleSpec`:
downforce areas in square metres, mass in kilograms, power in watts. The
adapter (`app/adapters/car_builder.py`) converts one into the other, and the
rule it follows is the engine's own — **a rating buys a physical property, and
the engine decides what that is worth.**

| rating | what it buys | why that |
|---|---|---|
| `aero` | downforce area up, induced drag down | a better wing is not a bigger wing; efficiency is what an aero department produces |
| `power_unit` | engine power and deployment, with the supplier's | a customer of a strong manufacturer can beat a works team of a weak one |
| `chassis` | mass | everybody chases the same minimum weight and the good teams get closer to it |
| `mechanical_grip` | centre-of-gravity height, track width | not an analogy: those two numbers are what set lateral load transfer in the engine's grip model |
| `tyre_management` | the tyre model's reference wear energy | the same work wears the tyre less |
| `reliability` | the per-distance failure rates | a hazard rate, not a chance of a DNF |

The spans are calibrated by measurement, not chosen.
`backend/scripts/calibrate_spread.py` runs the whole grid round three circuits:

```
Monza        2.24 s   2.14%   top two split 0.31 s
Silverstone  1.99 s   2.26%   top two split 0.22 s
Monaco       1.82 s   2.40%   top two split 0.08 s
```

Two to three per cent front to back with a couple of tenths at the top is where
a real Formula 1 field sits. And the *order* changes between the three, which
nobody arranged: it falls out of what each circuit asks of a car meeting what
each car is good at.

## The driver model is the engine's

The engine already has one, with ten attributes. A `DriverProfile` is the
career around it — an age, a contract, a reputation, a run of form — and
`to_engine_driver()` builds the engine's own object when a session needs one.

Six ratings carry the engine's names and are handed straight across. Five exist
only in the game, because the engine has nowhere to put them:

- `overtaking` and `defending`, because the engine settles a fight with one
  `racecraft` number and a manager game wants to tell an attacker from a
  defender. They are stored apart and folded back together according to which
  side of the fight the driver is on.
- `starts`, for the first hundred metres.
- `feedback`, which pays off in the factory rather than on Sunday.
- `mentality`, which decides what a bad weekend does to a driver's form.

The engine's other four attributes — braking, cornering, throttle control, risk
management — are derived from the ratings above rather than stored separately,
so each ability has one source of truth.

## Determinism

One seed, addressed by name:

```
GameSeed -> season/2026 -> round/7 -> qualifying   (handed to the engine)
                                   -> race         (handed to the engine)
                                   -> development  (the game's own draws)
```

Nothing depends on call order, so a save reloaded and re-run reaches the same
address and gets the same race. That is what makes "load it and try a different
strategy" a comparison rather than two different afternoons.

## What a round costs

The engine simulates every car on every lap. Measured, twenty cars:

| | |
|---|---|
| qualifying | 2.6 min |
| a 57-lap grand prix | 10.4 min |
| a 22-round season | about 4.8 hours |

Handled two ways, neither of which touches the physics. Long sessions run as
**background jobs** and the client polls; and a season can be run at a
**fraction of the race distance**, which is a shorter race rather than a
cheaper one — a 25% grand prix is fourteen laps genuinely simulated.

## The data

Nothing about the sport is in the code.

```
data/rules.json          points, season length, prize money, the cost cap
data/calendar.json       which circuits, in what order
data/tracks/tracks.json  the circuits, and what each asks of a car
data/teams/teams.json    the grid
data/drivers/drivers.json
data/engines/engines.json
```

The circuits are real and their lengths, corner counts and race distances are
the published ones. The teams, drivers and engine suppliers are fictional on
purpose: inventing performance figures and attaching a real person's name to
them would be presenting made-up data as fact. Every file is plain JSON, so a
licensed or community-made set drops in without a line of code changing.

The one thing still missing is real circuit *geometry*. The engine ships three
synthetic circuits and no surveyed data for these twenty-two, so each round
borrows the synthetic circuit closest to its character — named in
`physics_track`, and replaceable per circuit when survey data exists.

## Phases

| | | |
|---|---|---|
| 0 | Repository analysis | done |
| 1 | Game core: state, calendar, teams, drivers, standings, save/load | done |
| 2 | Race engine integration: qualifying, race, championship update | done |
| 3 | Management: R&D, upgrades, facilities, contracts, sponsors, AI teams | next |
| 4 | Frontend | |
| 5 | SVG race visualisation | |
| 6 | Advanced events | mostly already in the engine |
| 7 | Polish, replay, season history | |
