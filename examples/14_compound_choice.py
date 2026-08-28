"""Where a softer tyre stops being worth it.

    python examples/14_compound_choice.py [--laps 30]

Rule 20 asks for compounds that trade grip against life.  Nothing in the
engine states that trade: a soft compound has more peak friction, more
hysteresis (so it heats faster) and a higher wear rate, and everything else --
the early advantage, the crossover, the cliff -- comes out of driving on it.

The cumulative column is the one a strategist reads.  It is the total time to
complete N laps on a set, so the compound with the lowest number at each row
is the one to be on for a stint of that length.
"""

from __future__ import annotations

import argparse

from f1_race_engine.core.rng import RngHub
from f1_race_engine.core.units import format_lap_time
from f1_race_engine.driver.io import load_builtin_driver
from f1_race_engine.simulation import LapSimulator
from f1_race_engine.track.io import load_track
from f1_race_engine.tyres import TyreState
from f1_race_engine.tyres.io import load_builtin_compounds
from f1_race_engine.vehicle import Vehicle, VehicleSetup
from f1_race_engine.vehicle.ers import ErsState
from f1_race_engine.vehicle.io import load_builtin_vehicle


def stint(simulator, spec, compound, laps, fuel):
    tyres = TyreState()
    tyres.fit(compound)
    energy = ErsState(energy_remaining=spec.ers.capacity)
    load = fuel
    results = []
    for lap in range(1, laps + 1):
        result = simulator.simulate(
            lap=lap, fuel_mass=load, tyre_state=tyres, ers_state=energy,
            record_telemetry=False,
        )
        load -= result.fuel_used
        results.append(result)
    return results, tyres


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--laps", type=int, default=30)
    parser.add_argument("--track", default="synthetic_power_circuit")
    parser.add_argument("--car", default="reference_2024")
    parser.add_argument("--driver", default="01_benchmark")
    parser.add_argument("--fuel", type=float, default=100.0)
    parser.add_argument("--wing", type=float, default=0.5)
    parser.add_argument("--seed", type=int, default=20260812)
    args = parser.parse_args()

    track = load_track(args.track)
    spec = load_builtin_vehicle(args.car)
    vehicle = Vehicle(spec, VehicleSetup(wing_level=args.wing))
    driver = load_builtin_driver(args.driver)
    compounds = load_builtin_compounds()

    simulator = LapSimulator(track, vehicle, driver, rng=RngHub(args.seed))
    stints = {}
    for code in ("S", "M", "H"):
        compound = compounds[code]
        stints[code] = stint(simulator, spec, compound, args.laps, args.fuel)

    print(f"{track.name} -- {vehicle.name} -- {driver.name}\n")
    for code, (results, tyres) in stints.items():
        compound = compounds[code]
        print(
            f"{compound.name:<13} best {format_lap_time(min(r.lap_time for r in results))}"
            f"  wear after {args.laps} laps {tyres.wear:>6.1%}"
            f"  peak tread {tyres.peak_surface_temperature:5.1f} C"
        )

    codes = tuple(stints)
    header = f"{'lap':>4}" + "".join(f"{c:>12}" for c in codes) + f"{'  cumulative best':>20}"
    print("\n" + header)
    print("-" * len(header))
    totals = {code: 0.0 for code in codes}
    for index in range(args.laps):
        row = f"{index + 1:>4}"
        for code in codes:
            totals[code] += stints[code][0][index].lap_time
            row += f"{totals[code]:>12.2f}"
        leader = min(codes, key=lambda c: totals[c])
        row += f"{compounds[leader].name:>20}"
        print(row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
