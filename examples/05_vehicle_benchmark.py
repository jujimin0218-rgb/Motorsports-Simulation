"""Benchmark every shipped car and check it against real Formula 1 figures.

    python examples/05_vehicle_benchmark.py [--wing 0.5] [--json out/]

This is the Phase 2 benchmark run (project rule 41).  Nothing printed here is a
parameter: top speed is where net force reaches zero, 0-100 km/h comes from
integrating ``dt = dv / a(v)``, and braking distance from integrating the
deceleration the tyres actually allow.  Change the car and every figure moves
together.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from f1_race_engine.core.config import default_config
from f1_race_engine.environment import AmbientConditions
from f1_race_engine.physics.benchmark import benchmark_vehicle, format_benchmark
from f1_race_engine.physics.validation import validate_vehicle
from f1_race_engine.vehicle import Vehicle, VehicleSetup
from f1_race_engine.vehicle.io import builtin_vehicle_names, load_builtin_vehicle


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wing", type=float, default=0.5, help="wing level, 0 to 1")
    parser.add_argument("--car", help="benchmark only this car")
    parser.add_argument("--air-temperature", type=float, default=25.0)
    parser.add_argument("--json", type=Path, help="directory to write JSON reports into")
    args = parser.parse_args()

    config = default_config()
    ambient = AmbientConditions(air_temperature=args.air_temperature)
    names = [args.car] if args.car else builtin_vehicle_names()
    failed = False

    for name in names:
        vehicle = Vehicle(
            load_builtin_vehicle(name), VehicleSetup(wing_level=args.wing), config
        )
        benchmark = benchmark_vehicle(vehicle, ambient)
        report = validate_vehicle(vehicle, ambient, config)

        print(format_benchmark(benchmark))
        print()
        print(report.format())
        print()

        if not report.ok:
            failed = True
            print(f"!! {name} FAILED physics validation", file=sys.stderr)

        if args.json:
            args.json.mkdir(parents=True, exist_ok=True)
            path = args.json / f"{name}.json"
            path.write_text(
                json.dumps(
                    {
                        "vehicle": vehicle.to_dict(),
                        "benchmark": benchmark.to_dict(),
                        "validation": report.to_dict(),
                        "conditions": ambient.to_dict(),
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            print(f"wrote {path}\n")

    print("=" * 72)
    print("FAILED" if failed else f"OK -- {len(names)} car(s) benchmarked and validated")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
