# Motorsports-Simulation

A physics-based F1 race simulation engine designed for realistic lap times,
vehicle dynamics, tyre behaviour, strategy, and multi-car racing.

Lap times are the **result** of simulating a car covering a real distance-based
track model — never a random draw, and never a per-track correction.

**Status: the race engine is complete (Phases 1–12).** Core infrastructure, the track model, a car
whose behaviour comes out of a real force balance, a lap time that is the
integral of a speed profile, a driver who steps that car around the circuit,
consumables that change underneath all of it, a whole race weekend — weather
that moves on its own, a track surface that rubbers in and floods and dries a
racing line, knockout qualifying, a standing start over real distances, a
strategist that prices its own pit stops — and a field that can finally see each
other: dirty air, the tow, DRS, being held up, and getting past.

## Quick start

```bash
pip install -e '.[dev]'
pytest

python examples/01_build_and_validate.py        # circuit report for every track
python examples/02_track_state.py               # walk a lap, print the track state
python examples/03_visualise.py                 # SVG maps + circuit diagnostics
python examples/04_resolution_independence.py   # the property the design rests on
python examples/05_vehicle_benchmark.py         # car benchmark vs real F1 figures
python examples/06_setup_trade_off.py           # why circuits want different cars
python examples/07_visualise_vehicle.py         # force balance, g-g, cornering
python examples/08_lap_time.py --validate      # lap time + automatic checks
python examples/09_setup_per_circuit.py        # the circuit chooses the setup
python examples/10_visualise_lap.py            # speed profile, zones, g trace
python examples/11_driver_stint.py            # a stint, driver by driver
python examples/12_driver_telemetry.py        # telemetry CSV + overlay plot
python examples/13_stint_consumables.py      # tyres, fuel and energy over a stint
python examples/14_compound_choice.py        # where a softer tyre stops paying
python examples/15_race.py                   # a race, mid-race screens to flag
python examples/16_wet_weather.py            # a shower, and the drying line
python examples/17_race_weekend.py           # practice, qualifying, race
python examples/18_racing.py                 # two cars fighting, and its cost
```

```python
from f1_race_engine import (
    Forecast, RaceEntry, RaceStrategy, Vehicle, Weekend, benchmark_vehicle,
    compute_lap_time, load_builtin_compounds, load_builtin_driver,
    load_builtin_vehicle, load_driver_lineup, load_track, simulate_lap,
    validate_vehicle, wing_level_sweep,
)

track = load_track("synthetic_proving_ground")   # built and validated
state = track.state_at(2450.0)                   # the core query of the engine
print(state.radius, state.gradient, state.grip, state.sector)

car = Vehicle(load_builtin_vehicle("reference_2024"))
print(validate_vehicle(car).format())            # 14 automatic physics checks
print(benchmark_vehicle(car).peak_lateral_g)     # 5.40 -- integrated, not set

lap = compute_lap_time(track, car)
print(lap.formatted, lap.sector_times)           # 1:08.632 -- nobody chose this
print(wing_level_sweep(track, car).best)         # the circuit picks its setup

driver = load_builtin_driver("02_qualifier")
run = simulate_lap(track, car, driver, qualifying=True)
print(run.formatted, run.telemetry.full_throttle_fraction)

entries = [RaceEntry(car_number=i + 1, driver=d, vehicle=Vehicle(load_builtin_vehicle("reference_2024")),
                     compounds=tuple(load_builtin_compounds().compounds), strategy=RaceStrategy())
           for i, d in enumerate(load_driver_lineup())]
weekend = Weekend(track, entries, laps=10, forecast=Forecast(rain_probability=0.4),
                  practice_laps=2)
print(weekend.run().format())        # practice, qualifying, a race, one sky over all of it
```

A weekend is thousands of simulated laps, so it takes minutes rather than
seconds. `examples/17_race_weekend.py` takes `--laps` and `--practice` if you
want to trade fidelity for time.

## What is here

| Layer | Contents |
|---|---|
| `f1_race_engine/core/` | SI units, configuration, deterministic RNG, state, events, validation |
| `f1_race_engine/track/` | Definitions → builder → segments → `distance → TrackState` |
| `f1_race_engine/vehicle/` | Mass, aero, power unit, brakes, setup, fuel, ERS — separable systems |
| `f1_race_engine/tyres/` | Compounds, load sensitivity, friction ellipse, temperature, wear |
| `f1_race_engine/physics/` | Force balance, cornering, speed profile, lap time, validation |
| `f1_race_engine/driver/` | Ten separate abilities, each connected to the car |
| `f1_race_engine/simulation/` | The lap stepping loop and telemetry |
| `f1_race_engine/race/` | Entries, timing, qualifying, the grid, pit stops, strategy, racing |
| `f1_race_engine/environment/` | Air density, weather as a process, track evolution |
| `f1_race_engine/visualization/` | SVG circuit maps (no dependencies), matplotlib diagnostics |
| `f1_race_engine/data/` | Three circuits, three cars, five compounds, six drivers |

The engine core has **no third-party dependencies**. matplotlib is an optional
extra used only for debug plots.

## The season management game

On top of the engine there is a Formula 1 season management game: you run a
team for a season, sign the drivers, spend the research, set the strategy, and
the races are simulated by the engine below rather than by dice.

The one rule that shapes everything about it: **the game does not simulate
races.** It builds the inputs, hands them to the race engine, and reads the
result back. There is no second, simpler race model anywhere in it.

```
React + TypeScript
      |
   FastAPI
      |
 Game services  (season, money, research, contracts)
      |
  Race adapter
      |
  f1_race_engine     <- the physics, untouched
```

| | |
|---|---|
| `backend/app/game/` | the game itself — state, rules, calendar, teams, drivers |
| `backend/app/services/` | save/load and the operations a round goes through |
| `backend/app/adapters/` | the seam where a team's car becomes a `VehicleSpec` |
| `data/` | teams, drivers, engines, circuits, calendar, rules — all of it JSON |
| `frontend/` | the React client |

Nothing about the sport is written into the code. What a win is worth, how long
a season is, which circuits are on it and what each one asks of a car are all in
`data/`, and swapping that directory swaps the game.

```bash
python backend/scripts/phase1_demo.py   # new game -> calendar -> season -> save -> load
pytest backend/tests                    # the game's own suite
```

The teams, drivers and engine suppliers that ship with it are fictional.
Inventing performance figures and then attaching a real person's name to them
would be presenting made-up data as fact, so the shipped set is invented on
purpose and every file is plain JSON for anyone who wants to replace it. The
circuits are real, and their lengths, corner counts and race distances are the
published ones.


## Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — how it fits together and why
- [`docs/PHASE1.md`](docs/PHASE1.md) — the track model, with benchmark output
- [`docs/PHASE2.md`](docs/PHASE2.md) — the car, benchmarked against real F1 figures
- [`docs/PHASE3.md`](docs/PHASE3.md) — the lap, and why circuits want different cars
- [`docs/PHASE4.md`](docs/PHASE4.md) — the driver, and what each ability is worth
- [`docs/PHASE5.md`](docs/PHASE5.md) — tyres, fuel and energy, and where a compound crosses over
- [`docs/PHASE6.md`](docs/PHASE6.md) — a field of cars, and what a gap actually is
- [`docs/PHASE7.md`](docs/PHASE7.md) — qualifying, the grid, and getting off it
- [`docs/PHASE8.md`](docs/PHASE8.md) — what a stop costs, and how a plan is computed
- [`docs/PHASE9.md`](docs/PHASE9.md) — dirty air, the tow, and what a fight costs
- [`docs/PHASE10.md`](docs/PHASE10.md) — weather that moves, and two kinds of wet

## Roadmap

Phases 1-10 done. Next: 11 race events (safety cars, retirements, penalties) ·
12 advanced physics (suspension, slip angle, weight transfer).

A web layer (FastAPI + React) and a season-management game sit **on top** of the
engine; the engine itself stays UI-free and JSON-serialisable.

## Licence

MIT — see [LICENSE](LICENSE).
