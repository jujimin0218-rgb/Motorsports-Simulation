"""A whole race weekend: practice, qualifying and a race, under one sky.

    python examples/17_race_weekend.py [--laps 30] [--rain 0.4]

Three phases of this engine meet here, and the point is that none of them can
be understood alone:

* the **weather** runs continuously from the first practice lap to the flag, so
  a Saturday shower is still draining when qualifying starts (rule 30);
* the **track surface** carries over too, so every lap anybody runs makes the
  circuit quicker for everybody -- and rain washes it away again;
* **qualifying** is run rather than ranked, and the grid it produces is a set of
  distances behind the line that the race covers from a standstill (rule 27);
* **strategy** is computed from what the tyres actually did here, and abandoned
  the moment it starts raining (rules 31 and 32).

Run it twice with different seeds and you get different afternoons.  Nothing in
the engine knows what is supposed to happen.
"""

from __future__ import annotations

import argparse
import time

from f1_race_engine.core.rng import RngHub
from f1_race_engine.environment import Forecast
from f1_race_engine.race import (
    PitLane,
    QualifyingSegment,
    RaceEntry,
    RaceStrategy,
    Weekend,
)
from f1_race_engine.driver.io import load_driver_lineup
from f1_race_engine.track.io import load_track
from f1_race_engine.tyres.io import load_builtin_compounds
from f1_race_engine.vehicle import Vehicle, VehicleSetup
from f1_race_engine.vehicle.io import load_builtin_vehicle

CARS = ("reference_2024", "power_biased", "aero_biased")
TEAMS = ("Aurora", "Meridian", "Kestrel")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--laps", type=int, default=30)
    parser.add_argument("--track", default="synthetic_proving_ground")
    parser.add_argument("--rain", type=float, default=0.4)
    parser.add_argument("--practice", type=int, default=8)
    parser.add_argument("--fuel", type=float, default=90.0)
    parser.add_argument("--wing", type=float, default=0.5)
    parser.add_argument("--seed", type=int, default=20260812)
    args = parser.parse_args()

    track = load_track(args.track)
    compounds = load_builtin_compounds()
    drivers = load_driver_lineup()

    entries = []
    for index, driver in enumerate(drivers):
        spec = load_builtin_vehicle(CARS[index % len(CARS)])
        entries.append(
            RaceEntry(
                car_number=index + 1,
                driver=driver,
                vehicle=Vehicle(spec, VehicleSetup(wing_level=args.wing)),
                team=TEAMS[index % len(TEAMS)],
                fuel_mass=args.fuel,
                compounds=tuple(compounds.compounds),
                strategy=RaceStrategy(minimum_stint=6),
            )
        )

    names = {entry.car_number: entry.driver.name for entry in entries}
    lane = PitLane.for_track(track.length)
    weekend = Weekend(
        track,
        entries,
        laps=args.laps,
        rng=RngHub(args.seed),
        forecast=Forecast(
            air_temperature=23.0, cloud_cover=0.4, rain_probability=args.rain
        ),
        pit_lane=lane,
        segments=(
            QualifyingSegment("Q1", 1080.0, 2),
            QualifyingSegment("Q2", 900.0, 1),
            QualifyingSegment("Q3", 720.0, 0),
        ),
        practice_laps=args.practice,
    )

    print(f"{track.name} -- {args.laps} laps -- {len(entries)} cars")
    print(
        f"forecast {args.rain:.0%} rain | pit lane {lane.length:.0f} m at "
        f"{lane.speed_limit * 3.6:.0f} km/h | seed {args.seed}\n"
    )

    started = time.perf_counter()
    result = weekend.run()
    print(f"({time.perf_counter() - started:.0f} s of simulation)\n")
    print(result.format(names))

    print("\nweather through the weekend")
    header = f"{'':>6}{'min':>6}{'air':>7}{'track':>8}{'rain':>7}"
    print(header)
    print("-" * len(header))
    log = result.weather_log
    for label, state in zip(("start", "quali", "flag"), (log[0], log[-2], log[-1])):
        print(
            f"{label:>6}{state.elapsed / 60:6.0f}{state.air_temperature:7.1f}"
            f"{state.track_temperature:8.1f}{state.rain_intensity:7.2f}"
        )
    print(
        f"\ntrack at the flag: {weekend.conditions.mean_rubber:.0%} rubbered in, "
        f"{weekend.evolution.mean_water_depth * 1000:.2f} mm of water on "
        f"{weekend.evolution.wet_fraction:.0%} of it"
    )

    stops = [(entry, entry.pit_stops) for entry in entries if entry.pit_stops]
    if stops:
        print("\npit stops")
        for entry, made in stops:
            legs = ", ".join(
                f"L{stop.lap} {stop.from_compound}->{stop.to_compound}"
                f" ({stop.reason}, {stop.loss:.1f} s)"
                for stop in made
            )
            print(f"  {entry.label} {entry.driver.name:<18}{legs}")
    else:
        print("\nnobody stopped: the tyres lasted the distance")

    if result.qualifying is not None:
        converted = "converted pole" if result.pole_converted else "lost from pole"
        print(f"\ncar {result.pole} {converted}; car {result.winner} won.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
