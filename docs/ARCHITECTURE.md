# Architecture

This document describes how the engine is put together and, more importantly,
*why* — the reasoning that later phases need in order to extend it without
tearing the foundation up.

---

## 1. The one rule everything else follows

**A lap time is a result, never an input.**

The engine simulates a car covering a real distance-based track model. Whatever
lap time falls out is the answer. Four things are therefore forbidden anywhere
in the codebase:

| Forbidden | Why |
|---|---|
| `random.shuffle(drivers)` to decide finishing order | Position must come from distance and time |
| `lap_time = random.uniform(80, 85)` | Lap time must come from driving the track |
| `if track == "Monza": lap_time -= 2.0` | Monza's character must emerge from its long straights and low downforce demand |
| `lap_time -= driver.skill * 0.1` as the whole driver model | Driver ability must act through braking, cornering, throttle and tyre use |

The third one is the sharpest test of the design. Three circuits ship with
Phase 1 and they behave differently already — different corner radii, different
straight lengths, different widths, different surface grip — with no per-track
constant anywhere in the code. Nothing in `f1_race_engine/` branches on a track
name, and nothing ever should.

---

## 2. Layering

Two cores, kept apart on purpose:

```
                    ┌──────────────────────────────────┐
                    │        Race Core                 │
                    │  lap · position · gap · pit      │
                    │  strategy · overtaking · rules   │
                    └───────────────┬──────────────────┘
                                    │  reads state, issues intent
                    ┌───────────────┴──────────────────┐
                    │        Physics Core              │
                    │  speed · acceleration · braking  │
                    │  cornering · grip · aero · power │
                    └───────────────┬──────────────────┘
                                    │  queries by distance
                    ┌───────────────┴──────────────────┐
                    │        Track Model               │
                    │        distance → state          │
                    └──────────────────────────────────┘
```

The Physics Core answers *how does this car move here*. The Race Core answers
*what is happening in this race*. Neither is allowed to become a single large
class containing the other, because every future system attaches to exactly one
of them.

Events are the third seam. Safety cars, red flags, failures and collisions
reach the race state through `core/events.py`, never by reaching into the
physics.

---

## 3. The track model is the foundation

```
Definitions → Builder → Track → Segments → TrackState
```

### distance → state

A track is not a list of corners. It is a function of arc length:

```python
state = track.state_at(2450.0)     # curvature, gradient, banking, grip, width, DRS, sector
```

Everything downstream is built on that single query. The speed profile walks
distance asking for curvature; the lap simulation integrates `dt = ds / v`
asking for gradient; overtaking asks for width and DRS.

### Curvature, not radius

Curvature `κ = 1/R` is finite everywhere, is zero on a straight instead of
infinite, and interpolates linearly through a transition. Radius is derived
from it for human-facing output, never the other way round.

Sign convention, used engine-wide: **positive is a left-hand corner**. Banking
follows the same sign, so banking helps exactly when `sign(banking) ==
sign(curvature)`.

### Corners are clothoids, not arcs

A `CornerDefinition` generates three spans: an entry transition where curvature
ramps from zero to `1/R`, a constant-radius arc, and an exit transition back to
zero. The transitions turn the car too, so the arc is shortened to keep the
total turn angle exactly as requested:

```
κ · (L_arc + (L_entry + L_exit) / 2) = angle
```

This is not decoration. A step change in curvature would mean infinite lateral
jerk at turn-in, and it is precisely what the curvature-continuity check
rejects.

### Static geometry vs. session condition

| Immutable, shared by all 20 cars | Mutable, one per session |
|---|---|
| curvature, elevation, banking | rubber laid down |
| width, surface type, base grip | marbles off-line |
| kerbs, DRS zones, sectors | standing water |
| `Track` / `TrackSegment` | `TrackConditions` |

Track evolution and weather (Phase 10) only ever mutate `TrackConditions`. The
geometry stays immutable and shareable, which is what makes a twenty-car
simulation affordable. In Phase 1 every condition sits at its neutral value, so
effective grip equals static grip exactly.

### Adaptive resolution

Segment length is chosen from three criteria, whichever is tightest: a target
length, a cap on heading change per segment, and a cap on curvature change per
segment. A straight lands at 25 m and a hairpin at ~1 m without anybody asking.

**Changing the resolution must not change the circuit.** That is enforced by a
strict separation:

- the **definition** owns geometry — radii, angles, transition lengths, width,
  grip;
- `TrackBuildConfig` owns **sampling only**.

`tests/test_resolution.py` builds the same circuit at four resolutions spanning
a 20× range in segment count and asserts that lap length, turning, corner
geometry, sector lengths and the track state at 997 distances all agree.
Measured difference: floating-point noise.

One consequence worth knowing: fields with a hard boundary — sector, DRS zone,
surface region, kerb — are *sampled at the midpoint* on `TrackSegment`, so a
segment straddling a boundary can only carry one of the two values. Physics
must therefore query `track.state_at()`, which resolves those from their own
maps at the exact distance.

---

## 3a. The vehicle stands on the same principle

A car is not one overall rating (project rule 11). It is a set of systems, and
its behaviour is whatever the force balance produces:

```
F_net = F_drive - F_drag - F_rolling - F_brake - m*g*sin(theta)
a     = F_net / m
```

Two couplings do most of the work, and both are deliberate.

### Induced drag makes wing a real choice

```
CdA = CdA_0 + k * ClA^2
```

Drag has a term proportional to the *square* of the downforce being generated,
so the tenth wing level costs far more than the first. There is no setting that
is best everywhere: a low wing is fast down a long straight and hopeless
through a medium-speed corner. **This is the mechanism that satisfies rule
2.3.** Monza and Monaco want different cars because their corner radii and
straight lengths differ, not because anything in the engine knows their names.

Measured across the reference car's wing range: +2.9 km/h through a 25 m
corner, +82.4 km/h through a 120 m corner, and -45.8 km/h of top speed.

Phase 3 turns that into the decisive test. Sweeping wing level on each shipped
circuit, the optimum lands **at 0.0 on the power circuit, at 1.0 on the street
circuit, and at 0.2 — a genuine interior optimum — on the balanced one**. And
which of the three shipped cars is fastest flips between circuits: the
power-biased car wins the power circuit by 6.8 s, the aero-biased car wins the
street circuit. Nothing in `f1_race_engine/` branches on a circuit's name.

### Load sensitivity makes downforce non-linear

```
mu = mu_peak * (N / N_ref)^-k
```

A tyre loses friction *coefficient* as it is pressed harder, though it still
gains force. Without this, cornering ability would rise linearly with downforce
and fast corners would come out absurd. It is also why an F1 car pulls 5 g in a
fast corner while its coefficient there is *lower* than in a slow one.

### Consequences that follow rather than being written down

* Traction is an axle question: a rear-drive car launches on its rear tyres, so
  the limit uses rear axle load including load transfer.
* Braking is grip limited, because the brake system is specified above any grip
  limit — an F1 car can lock its wheels at any speed.
* The corner speed limit is **implicit** (grip depends on speed depends on
  grip) and is solved by bisection, not by inverting a simplified formula that
  would be wrong exactly where it matters.
* A heavy fuel load costs 1.5% of corner speed in a hairpin and 7% in a fast
  corner — because at low speed mass largely cancels out of `a = mu*g`, and at
  high speed it does not.

---

## 3b. The lap is where the two meet

Project rule 15.  A lap time is never chosen; it is the integral of a speed
profile, and the profile is the pointwise minimum of three limits:

```
Track -> curvature -> cornering limit
                          |
                +---------+---------+
          backward pass        forward pass
         (what braking          (what the engine
          allows into it)        allows out of it)
                +---------+---------+
                          |
                   final speed profile
```

Where the three curves intersect is the apex. Nobody had to say where it is.

Three properties make this correct rather than merely plausible:

* **Both directions are needed.** A slow corner constrains how fast you may
  still be arriving *and* how fast you can have got to the next one; one sweep
  propagates only one of those.
* **The sweeps wrap.** A lap is a loop, so a braking zone can begin before the
  start/finish line. Repeating until nothing changes is what makes the answer
  independent of where the lap is cut.
* **Combined grip is respected.** A car using 80% of its lateral limit has only
  the remainder of the friction circle for braking or traction.

That last one has to be enforced on **one consistent basis**. Phase 3 found a
real bug here: the lateral model computed the friction circle on total load
while the traction model computed it per axle, and because μ falls with load,
two axles have more grip between them than one lump. A car at its cornering
limit therefore still believed it had drive available, and the profile
accelerated through apexes. Cornering is now charged as a fraction of the whole
car's circle — the same basis the lateral model uses.

**Resolution independence extends to the lap.** Segment count can vary by 22×
and the lap time moves by 0.024%, because the energy update
`v₁² = v₀² + 2·a·ds` is exact for constant acceleration and a midpoint
corrector makes it second-order for the speed-dependent case.

---

## 4. Determinism

`RngHub` is the single owner of randomness. It hands out **named, hierarchical
sub-streams**:

```python
hub.stream("tyre.degradation", car=14, lap=23).normal(0.0, 1.0)
```

Each stream's seed is derived by hashing `(master_seed, path)` with BLAKE2b.
That buys three properties a shared stream cannot:

1. **Adding a subsystem cannot disturb existing ones.** With one shared stream,
   a new driver-mistake check would shift every later draw and silently
   invalidate every result recorded before it. This project expects to keep
   adding systems for a long time, so that would be fatal.
2. **Per-car and per-lap independence**, so results are identical whether cars
   are simulated in sequence or in parallel.
3. **Replayability of one car's lap 23** without replaying everything before it.

Distributions are built on `random()` alone — CPython's Mersenne Twister output
for `random()` is stable across versions, whereas `gauss` and `shuffle` are not
contractually fixed. `normal()` consumes exactly two draws, always, so a
divergence between two runs can be bisected.

`hash()` is never used for seeding: it is salted per process by PYTHONHASHSEED
and would destroy reproducibility.

---

## 5. Configuration

Every tunable number lives in a frozen dataclass under `core/config.py`, so the
model can be re-calibrated against real telemetry by editing data, never code.
`ConfigNode` gives every section recursive `to_dict` / `from_dict` / `merged`
for free.

Unknown keys are **rejected**, not ignored. During calibration a silently
dropped typo (`aero_efficency`) looks exactly like a parameter that has no
effect, which is far more expensive to debug than an immediate error.

Adding a subsystem in a later phase = one new dataclass + one field on
`SimulationConfig` with a default. Existing config files keep loading.

---

## 5a. Validation is per-system, not per-phase

Rule 39 asks for automatic validation of every system. The reporting machinery
lives in `core/validation.py`; each system owns its own suite of checks:

* `track/validation.py` — 16 checks on circuit geometry
* `physics/validation.py` — 14 checks on vehicle behaviour
* `physics/lap_validation.py` — 11 checks on the profile and the lap

Both kinds matter. **Directional** checks (speed up, downforce up; mass up,
acceleration down) catch a sign error or a dropped force term. **Envelope**
checks catch a model that is perfectly self-consistent and still produces a car
cornering at 12 g — only comparison against reality finds that one.

Adding a check is appending a function to a list.

---

## 6. Units

Internal physics is **SI throughout**: metres, seconds, m/s, kg, newtons,
watts, joules, radians. Human-facing data (km/h, degrees, bar, horsepower) is
converted **once**, at the boundary, by `core/units.py`. Nothing inside the
physics core sees a non-SI number.

---

## 7. Module map

Shipped in Phase 1:

```
f1_race_engine/
    core/
        units.py            SI conventions + conversion layer
        config.py           frozen, validated, JSON-round-tripping config tree
        rng.py              hierarchical deterministic RNG
        interpolation.py    monotone-cubic profiles (C1, no overshoot)
        state.py            clock, snapshot protocol, telemetry recorder
        events.py           deterministic event bus
        errors.py           exception hierarchy
    track/
        definitions.py      StraightDefinition, CornerDefinition, overlays
        builder.py          definitions → spans → segments → Track
        segment.py          TrackSegment (immutable, linear curvature)
        model.py            Track, TrackState — the distance → state query
        curvature.py        curvature utilities, corner classification
        geometry.py         clothoid integration → plan-view centreline
        elevation.py        elevation and gradient profile
        banking.py          banking profile
        surface.py          SurfaceMap, KerbMap, TrackConditions
        drs.py              DRS zones (detection / activation)
        validation.py       16 registered checks
        layout_solver.py    design-time circuit closure solver
        io.py               JSON load/save
        report.py           benchmark report
    vehicle/
        model.py            VehicleSpec (what was built) + Vehicle (+ setup)
        mass.py             chassis, driver, fuel, distribution, load transfer
        aero.py             downforce and drag, coupled by induced drag
        power_unit.py       torque-limited and power-limited tractive force
        brakes.py           system capability (above the grip limit, by design)
        setup.py            wing level, brake bias, fuel load
        state.py            physics state: distance, speed, fuel, tyres
        io.py               JSON load/save
    tyres/
        compound.py         peak friction, load sensitivity, wear rate
        model.py            grip limits and the friction ellipse
        state.py            fitted set, age, wear (neutral until Phase 5)
        io.py               JSON load/save
    physics/
        grip.py             normal load: weight, downforce, banking, transfer
        longitudinal.py     the force balance, traction and braking limits
        lateral.py          cornering capability and the corner speed limit
        speed_profile.py    cornering limit + forward/backward passes
        braking.py          braking points and distances, read off the profile
        acceleration.py     corner exits, traction- vs power-limited
        lap_time.py         exact time integration, sectors, rule-41 metrics
        setup_search.py     let the circuit choose the setup
        benchmark.py        measured performance envelope
        validation.py       14 vehicle checks
        lap_validation.py   11 lap checks, including rule 40 Test C
    environment/
        conditions.py       air density from real atmospheric physics
    visualization/
        svg.py              standalone SVG maps, no dependencies
        track_plots.py      matplotlib circuit diagnostics (optional extra)
        vehicle_plots.py    force balance, g-g envelope, cornering limit
        lap_plots.py        speed profile, zones, g trace, speed map
    data/
        tracks/             three synthetic circuits
        vehicles/           three cars: reference, power-biased, aero-biased
        tyres/              five compounds
```

Arriving in later phases, attached at the seams above:

```
    vehicle/   ers, gearbox, differential, cooling, fuel burn
    tyres/     temperature, degradation, wear, pressure
    driver/    pace, inputs, braking, cornering, consistency, racecraft
    physics/   suspension, slip angle, yaw, weight transfer (dynamic)
    race/      session, qualifying, race, timing, pitstop, strategy, overtaking
    environment/ weather, wind, track_temperature, track_evolution
    events/    safety_car, vsc, red_flag, collision, mechanical_failure
```

---

## 8. Extension points

Adding a system should not require touching what already exists.

| To add | Do this |
|---|---|
| A track property (drainage, wind exposure) | Add a field to `TrackSegment` with a default + a definition class + one sampling call in the builder |
| A dynamic surface effect | Add a field to `SurfaceCondition` and a term in `TrackConditions.grip_multiplier` |
| A validation check | Write a function and append it to `TRACK_CHECKS` |
| A config section | Add a `ConfigNode` subclass + one field on `SimulationConfig` |
| A race event | Subclass `Event`, emit it on the bus |
| A source of randomness | Call `hub.stream("your.subsystem", ...)` — nothing else is affected |
| A circuit | Write the JSON definition; use `layout_solver` to close the geometry |

---

## 9. External clients

The engine is UI-free by construction (project rule 44). It produces simulation
data; something else visualises it.

- `Track.to_dict()`, `TrackState.to_dict()`, `track_report()` and
  `validate_track().to_dict()` are all plain JSON-compatible data.
- Every segment carries `x`, `y`, `heading`, so a client can draw the circuit
  without re-integrating curvature.
- `visualization/svg.py` already emits a browser-ready circuit map.

The planned web layer sits **on top**, importing the engine and never being
imported by it:

```
React (SVG track map, dashboards)
        │  HTTP / JSON
FastAPI (session state, save games)
        │  imports
f1_race_engine  ← this package
```

A Unity or other 3D client consumes the same data over the same boundary.

---

## 10. Phase roadmap

| Phase | Content | State |
|---|---|---|
| 1 | Core, units, config, RNG, track model, builder, validation, viz | **done** |
| 2 | Vehicle: mass, engine, drag, downforce, brakes, basic tyre grip | **done** |
| 3 | Speed profile: cornering / braking / acceleration limits, forward + backward pass | **done** |
| 4 | Lap simulation and the driver model | next |
| 5 | Tyres, fuel, ERS |
| 6 | Multi-car simulation |
| 7 | Qualifying and race |
| 8 | Strategy and pit stops |
| 9 | Overtaking and defence |
| 10 | Weather and environment |
| 11 | Race events: SC, VSC, red flag, collisions, failures |
| 12 | Advanced physics: suspension, weight transfer, slip angle, differential |

Each phase ends by running the code, running the tests, checking physics
sanity, running the benchmark, and fixing what is wrong — **before** the next
phase starts.

### Deferred deliberately

Real circuit data (Monza, Monaco, Silverstone, Spa, Suzuka, Bahrain) is **not**
in Phase 1. Hand-authoring a real circuit's plan view from memory produces
geometry that closes only by distorting the straights — a first attempt at
Monza required shrinking the Curva Grande → Roggia run from 550 m to 192 m,
which would give wrong top speeds and wrong lap times while looking entirely
plausible. Real circuits arrive alongside the telemetry calibration path
(project rule 43), when there is something to check them against.

What ships instead is three honestly-labelled synthetic circuits spanning the
character space, and `layout_solver.py`, the tool that makes authoring the real
ones tractable.
