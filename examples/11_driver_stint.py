"""Run a stint and watch each driver's character show up in the lap times.

    python examples/11_driver_stint.py [--laps 20] [--track NAME]

Nothing here adds time to a result.  A driver's abilities become the fraction
of the car's grip they actually use, the speed profile responds, and the lap
time follows.  An inconsistent driver is slower *on average* as well as more
scattered, because commitment can fall short of the limit but never exceed it.
"""

from __future__ import annotations

import argparse
import statistics

from f1_race_engine.core.rng import RngHub
from f1_race_engine.driver.io import load_driver_lineup
from f1_race_engine.simulation import LapSimulator
from f1_race_engine.track.io import load_track
from f1_race_engine.vehicle import Vehicle, VehicleSetup
from f1_race_engine.vehicle.io import load_builtin_vehicle


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--laps", type=int, default=20)
    parser.add_argument("--track", default="synthetic_proving_ground")
    parser.add_argument("--car", default="reference_2024")
    parser.add_argument("--wing", type=float, default=0.5)
    parser.add_argument("--seed", type=int, default=20260812)
    args = parser.parse_args()

    track = load_track(args.track)
    vehicle = Vehicle(load_builtin_vehicle(args.car), VehicleSetup(wing_level=args.wing))
    drivers = load_driver_lineup()

    print(f"{track.name} -- {vehicle.name} -- {args.laps} laps, seed {args.seed}\n")
    header = (
        f"{'driver':<18}{'best':>9}{'median':>9}{'worst':>9}{'sd':>8}"
        f"{'mistakes':>10}{'quali':>9}"
    )
    print(header)
    print("-" * len(header))

    rows = []
    for driver in drivers:
        simulator = LapSimulator(track, vehicle, driver, rng=RngHub(args.seed))
        laps = [
            simulator.simulate(lap=lap, record_telemetry=False)
            for lap in range(1, args.laps + 1)
        ]
        times = [lap.lap_time for lap in laps]
        quali = min(
            simulator.simulate(
                lap=1000 + i, qualifying=True, record_telemetry=False
            ).lap_time
            for i in range(3)
        )
        mistakes = sum(len(lap.mistakes) for lap in laps)
        rows.append((driver, min(times), statistics.median(times), quali))
        print(
            f"{driver.abbreviation + '  ' + driver.name:<18}{min(times):>9.3f}"
            f"{statistics.median(times):>9.3f}{max(times):>9.3f}"
            f"{statistics.pstdev(times):>8.3f}{mistakes:>10}{quali:>9.3f}"
        )
    print("-" * len(header))

    best_race = min(row[2] for row in rows)
    best_quali = min(row[3] for row in rows)
    print("\nGaps to the fastest:")
    print(f"  {'driver':<18}{'race (median)':>15}{'qualifying':>14}")
    for driver, _, median, quali in sorted(rows, key=lambda r: r[2]):
        print(
            f"  {driver.abbreviation:<18}{median - best_race:>+14.3f}s"
            f"{quali - best_quali:>+13.3f}s"
        )

    print(
        "\nA driver's race and qualifying order need not match: a one-lap\n"
        "specialist finds commitment when it counts and gives it back over a\n"
        "stint, and none of that is written anywhere as a rule."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
