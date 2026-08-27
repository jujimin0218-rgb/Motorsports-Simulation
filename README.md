# Motorsports-Simulation

A physics-based F1 race simulation engine designed for realistic lap times,
vehicle dynamics, tyre behaviour, strategy, and multi-car racing.

Lap times are the **result** of simulating a car covering a real distance-based
track model — never a random draw, and never a per-track correction.

**Status: Phase 2 (basic vehicle physics) complete.** Core infrastructure, the
track model, and a car whose behaviour comes out of a real force balance. No
lap time yet — that is Phases 3 and 4.

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
```

```python
from f1_race_engine import (
    Vehicle, benchmark_vehicle, load_builtin_vehicle, load_track, validate_vehicle,
)

track = load_track("synthetic_proving_ground")   # built and validated
state = track.state_at(2450.0)                   # the core query of the engine
print(state.radius, state.gradient, state.grip, state.sector)

car = Vehicle(load_builtin_vehicle("reference_2024"))
print(validate_vehicle(car).format())            # 14 automatic physics checks
print(benchmark_vehicle(car).peak_lateral_g)     # 5.40 -- integrated, not set
```

## What is here

| Layer | Contents |
|---|---|
| `f1_race_engine/core/` | SI units, configuration, deterministic RNG, state, events, validation |
| `f1_race_engine/track/` | Definitions → builder → segments → `distance → TrackState` |
| `f1_race_engine/vehicle/` | Mass, aero, power unit, brakes, setup — separable systems |
| `f1_race_engine/tyres/` | Compounds, load sensitivity, friction ellipse |
| `f1_race_engine/physics/` | Normal loads, force balance, cornering, benchmark, validation |
| `f1_race_engine/environment/` | Air density from real atmospheric physics |
| `f1_race_engine/visualization/` | SVG circuit maps (no dependencies), matplotlib diagnostics |
| `f1_race_engine/data/` | Three circuits, three cars, five tyre compounds |

The engine core has **no third-party dependencies**. matplotlib is an optional
extra used only for debug plots.

## Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — how it fits together and why
- [`docs/PHASE1.md`](docs/PHASE1.md) — the track model, with benchmark output
- [`docs/PHASE2.md`](docs/PHASE2.md) — the car, benchmarked against real F1 figures

## Roadmap

Phases 1-2 done. Next: 3 speed profile · 4 lap simulation · 5 tyres/fuel/ERS ·
6 multi-car · 7 qualifying & race · 8 strategy & pit stops · 9 overtaking ·
10 weather · 11 race events · 12 advanced physics.

A web layer (FastAPI + React) and a season-management game sit **on top** of the
engine; the engine itself stays UI-free and JSON-serialisable.

## Licence

MIT — see [LICENSE](LICENSE).
