# Motorsports-Simulation

A physics-based F1 race simulation engine designed for realistic lap times,
vehicle dynamics, tyre behaviour, strategy, and multi-car racing.

Lap times are the **result** of simulating a car covering a real distance-based
track model — never a random draw, and never a per-track correction.

**Status: Phase 1 (foundation) complete.** Core infrastructure and the track
model. No vehicle yet — that is Phase 2.

## Quick start

```bash
pip install -e '.[dev]'
pytest                                          # 283 tests

python examples/01_build_and_validate.py        # benchmark report for every circuit
python examples/02_track_state.py               # walk a lap, print the track state
python examples/03_visualise.py                 # SVG maps + matplotlib overviews
python examples/04_resolution_independence.py   # the property the design rests on
```

```python
from f1_race_engine import load_track

track = load_track("synthetic_proving_ground")   # built and validated
state = track.state_at(2450.0)                   # the core query of the engine

print(track)                                     # Track('Synthetic Proving Ground', ...)
print(state.radius, state.gradient, state.grip, state.sector)
```

## What is here

| Layer | Contents |
|---|---|
| `f1_race_engine/core/` | SI units, configuration, deterministic RNG, state, events |
| `f1_race_engine/track/` | Definitions → builder → segments → `distance → TrackState` |
| `f1_race_engine/visualization/` | SVG circuit maps (no dependencies), matplotlib diagnostics |
| `f1_race_engine/data/tracks/` | Three synthetic circuits spanning power / balanced / technical |

The engine core has **no third-party dependencies**. matplotlib is an optional
extra used only for debug plots.

## Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — how it fits together and why
- [`docs/PHASE1.md`](docs/PHASE1.md) — what Phase 1 delivers, with benchmark output

## Roadmap

Phase 2 vehicle physics · 3 speed profile · 4 lap simulation · 5 tyres/fuel/ERS
· 6 multi-car · 7 qualifying & race · 8 strategy & pit stops · 9 overtaking ·
10 weather · 11 race events · 12 advanced physics.

A web layer (FastAPI + React) and a season-management game sit **on top** of the
engine; the engine itself stays UI-free and JSON-serialisable.

## Licence

MIT — see [LICENSE](LICENSE).
