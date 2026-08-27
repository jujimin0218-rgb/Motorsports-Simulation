"""Render lap diagnostics: speed profile, braking and acceleration zones.

    python examples/10_visualise_lap.py [--out build/] [--wing 0.5]

Project rule 42 asks for exactly these plots.  Where the speed line touches the
cornering limit is an apex; where they part, braking or power is the constraint
instead.

Needs matplotlib:  pip install 'f1-race-engine[viz]'
"""

from __future__ import annotations

import argparse
from pathlib import Path

from f1_race_engine.environment import AmbientConditions
from f1_race_engine.physics import compute_lap_time
from f1_race_engine.track.io import builtin_track_names, load_track
from f1_race_engine.vehicle import Vehicle, VehicleSetup
from f1_race_engine.vehicle.io import load_builtin_vehicle


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("build/lap_plots"))
    parser.add_argument("--car", default="reference_2024")
    parser.add_argument("--wing", type=float, default=0.5)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    try:
        from f1_race_engine.visualization.lap_plots import save_lap_overview
    except ImportError as exc:
        print(f"cannot plot: {exc}")
        return 1

    ambient = AmbientConditions()
    spec = load_builtin_vehicle(args.car)
    for name in builtin_track_names():
        track = load_track(name)
        vehicle = Vehicle(spec, VehicleSetup(wing_level=args.wing))
        result = compute_lap_time(track, vehicle, ambient)
        path = save_lap_overview(result, track, str(args.out / f"{name}.png"))
        print(f"{path}   {result.formatted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
