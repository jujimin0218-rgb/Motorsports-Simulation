"""Render vehicle diagnostic plots for the shipped cars (project rule 42).

    python examples/07_visualise_vehicle.py [--out build/] [--wing 0.5]

Four panels per car: the longitudinal force balance, the g-g envelope, the
performance envelope against speed, and the cornering limit against radius.
These are the first place to look when a lap time comes out wrong in Phase 4.

Needs matplotlib:  pip install 'f1-race-engine[viz]'
"""

from __future__ import annotations

import argparse
from pathlib import Path

from f1_race_engine.environment import AmbientConditions
from f1_race_engine.vehicle import Vehicle, VehicleSetup
from f1_race_engine.vehicle.io import builtin_vehicle_names, load_builtin_vehicle


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("build/vehicle_plots"))
    parser.add_argument("--wing", type=float, default=0.5)
    parser.add_argument("--air-temperature", type=float, default=25.0)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    try:
        from f1_race_engine.visualization.vehicle_plots import save_vehicle_overview
    except ImportError as exc:
        print(f"cannot plot: {exc}")
        return 1

    ambient = AmbientConditions(air_temperature=args.air_temperature)
    for name in builtin_vehicle_names():
        vehicle = Vehicle(load_builtin_vehicle(name), VehicleSetup(wing_level=args.wing))
        print(save_vehicle_overview(vehicle, str(args.out / f"{name}.png"), ambient))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
