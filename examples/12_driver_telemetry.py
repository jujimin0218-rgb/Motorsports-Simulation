"""Export a lap's telemetry, in the channels a real trace has.

    python examples/12_driver_telemetry.py [--out build/] [--driver 01_benchmark]

Project rule 43: the output is meant to line up with real Formula 1 telemetry
channel for channel, so that calibration against recorded data is possible
later.  Gear and ERS deployment are present as channels and empty for now --
the gearbox is Phase 12 and the energy system Phase 5.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from f1_race_engine.core.rng import RngHub
from f1_race_engine.driver.io import load_builtin_driver
from f1_race_engine.simulation import LapSimulator
from f1_race_engine.track.io import load_track
from f1_race_engine.vehicle import Vehicle, VehicleSetup
from f1_race_engine.vehicle.io import load_builtin_vehicle


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("build/telemetry"))
    parser.add_argument("--track", default="synthetic_proving_ground")
    parser.add_argument("--car", default="reference_2024")
    parser.add_argument("--driver", default="01_benchmark")
    parser.add_argument("--wing", type=float, default=0.5)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    track = load_track(args.track)
    vehicle = Vehicle(load_builtin_vehicle(args.car), VehicleSetup(wing_level=args.wing))
    driver = load_builtin_driver(args.driver)

    simulator = LapSimulator(track, vehicle, driver, rng=RngHub(20260812))
    result = simulator.simulate(qualifying=True)
    telemetry = result.telemetry
    assert telemetry is not None

    path = args.out / f"{args.track}__{driver.abbreviation}.csv"
    path.write_text(telemetry.to_csv(), encoding="utf-8")

    print(f"{driver.name} at {track.name}: {result.formatted}")
    print(f"  sectors        {'  '.join(f'{s:.3f}' for s in result.sector_times)}")
    print(f"  full throttle  {telemetry.full_throttle_fraction:.1%} of lap time")
    print(f"  braking        {telemetry.braking_fraction:.1%}")
    print(f"  cornering      {telemetry.cornering_fraction:.1%}")
    print(f"  samples        {len(telemetry)}")
    print(f"  wrote          {path}")

    try:
        from f1_race_engine.visualization.lap_plots import save_telemetry_comparison
    except ImportError:
        pass
    else:
        from f1_race_engine.driver.io import load_driver_lineup

        overlay = [
            LapSimulator(track, vehicle, other, rng=RngHub(20260812)).simulate(
                qualifying=True
            )
            for other in load_driver_lineup()[:3]
        ]
        image = save_telemetry_comparison(
            overlay, str(args.out / f"{args.track}__comparison.png")
        )
        print(f"  wrote          {image}")

    print("\n  first samples:")
    print(
        f"    {'dist':>7}{'time':>8}{'kph':>8}{'thr':>7}{'brk':>7}"
        f"{'lat g':>8}{'long g':>8}"
    )
    for sample in telemetry.samples[:8]:
        print(
            f"    {sample.distance:>7.0f}{sample.time:>8.3f}{sample.speed_kph:>8.1f}"
            f"{sample.throttle:>7.2f}{sample.brake:>7.2f}"
            f"{sample.lateral_g:>8.2f}{sample.longitudinal_g:>8.2f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
