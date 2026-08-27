"""Compute a lap for every car on every circuit, and validate it.

    python examples/08_lap_time.py [--car NAME] [--track NAME] [--json out/]

This is the Phase 3 benchmark run (project rule 41).  The lap time is not set
anywhere: it is the integral of a speed profile that is itself the minimum of
what the tyres allow through each corner, what braking allows on the way in,
and what the engine allows on the way out.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from f1_race_engine.core.units import ms_to_kph
from f1_race_engine.environment import AmbientConditions
from f1_race_engine.physics import compute_lap_time, format_lap_result
from f1_race_engine.physics.lap_validation import validate_lap
from f1_race_engine.track.io import builtin_track_names, load_track
from f1_race_engine.vehicle import Vehicle, VehicleSetup
from f1_race_engine.vehicle.io import builtin_vehicle_names, load_builtin_vehicle


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--car", help="only this car")
    parser.add_argument("--track", help="only this circuit")
    parser.add_argument("--wing", type=float, default=0.5)
    parser.add_argument("--air-temperature", type=float, default=25.0)
    parser.add_argument("--json", type=Path)
    parser.add_argument("--validate", action="store_true", help="run the lap checks")
    args = parser.parse_args()

    ambient = AmbientConditions(air_temperature=args.air_temperature)
    cars = [args.car] if args.car else builtin_vehicle_names()
    tracks = [args.track] if args.track else builtin_track_names()
    failed = False
    grid: dict[str, dict[str, float]] = {}

    for track_name in tracks:
        track = load_track(track_name)
        grid[track_name] = {}
        for car_name in cars:
            vehicle = Vehicle(
                load_builtin_vehicle(car_name), VehicleSetup(wing_level=args.wing)
            )
            result = compute_lap_time(track, vehicle, ambient)
            grid[track_name][car_name] = result.lap_time
            print(format_lap_result(result))
            print()

            if args.validate:
                report = validate_lap(track, vehicle, ambient, baseline=result)
                print(report.format())
                print()
                if not report.ok:
                    failed = True
                    print(f"!! {car_name} at {track_name} FAILED", file=sys.stderr)

            if args.json:
                args.json.mkdir(parents=True, exist_ok=True)
                path = args.json / f"{track_name}__{car_name}.json"
                path.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")

    if len(cars) > 1 and len(tracks) > 1:
        print("=" * 74)
        print("LAP TIMES")
        print("=" * 74)
        print(f"  {'':<20}" + "".join(f"{c:>20}" for c in cars))
        for track_name, row in grid.items():
            best = min(row.values())
            cells = "".join(
                f"{row[c]:>17.3f}" + ("  *" if row[c] == best else "   ") for c in cars
            )
            print(f"  {track_name.replace('synthetic_', ''):<20}{cells}")
        print("\n  * fastest on that circuit -- decided by geometry and physics,")
        print("    with nothing in the engine branching on a circuit's name.")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
