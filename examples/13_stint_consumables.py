"""Watch a set of tyres, a tank of fuel and a battery go through a stint.

    python examples/13_stint_consumables.py [--laps 25] [--compound M]

Every number in this table is a consequence, not an input.  There is no
per-lap degradation figure, no fuel-per-lap constant and no ERS lap-time
bonus anywhere in the engine (project rules 21-24).  What there is:

* tyres that heat from the friction work they do and wear from the same work,
  so they come in over the first lap or two and go off as the stint runs;
* fuel burned in proportion to the engine's work, so the car gets lighter and
  the laps get quicker -- which fights the tyres going off;
* an energy store that has to recover what it deploys, so the first lap out of
  the garage is the only one that gets to spend a full battery.

The lap time is the sum of all of it, and which effect wins changes as the
stint goes on.
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--laps", type=int, default=25)
    parser.add_argument("--track", default="synthetic_power_circuit")
    parser.add_argument("--car", default="reference_2024")
    parser.add_argument("--driver", default="01_benchmark")
    parser.add_argument("--compound", default="M")
    parser.add_argument("--fuel", type=float, default=100.0)
    parser.add_argument("--wing", type=float, default=0.5)
    parser.add_argument("--seed", type=int, default=20260812)
    args = parser.parse_args()

    track = load_track(args.track)
    spec = load_builtin_vehicle(args.car)
    vehicle = Vehicle(spec, VehicleSetup(wing_level=args.wing))
    driver = load_builtin_driver(args.driver)
    compound = load_builtin_compounds()[args.compound]

    simulator = LapSimulator(track, vehicle, driver, rng=RngHub(args.seed))
    tyres = TyreState()
    tyres.fit(compound)
    energy = ErsState(energy_remaining=spec.ers.capacity)
    fuel = args.fuel

    print(f"{track.name} -- {vehicle.name} -- {driver.name} -- {compound.name}\n")
    header = (
        f"{'lap':>4}{'time':>10}{'delta':>8}{'tread':>8}{'wear':>7}{'grip':>7}"
        f"{'fuel':>8}{'burn':>7}{'deploy':>8}{'recov':>7}{'charge':>8}"
    )
    print(header)
    print("-" * len(header))

    best = None
    for lap in range(1, args.laps + 1):
        result = simulator.simulate(
            lap=lap, fuel_mass=fuel, tyre_state=tyres, ers_state=energy,
            record_telemetry=False,
        )
        fuel -= result.fuel_used
        best = result.lap_time if best is None else min(best, result.lap_time)
        print(
            f"{lap:>4}{format_lap_time(result.lap_time):>10}"
            f"{result.lap_time - best:>+8.3f}"
            f"{result.tyre_temperature:>7.1f}C{result.tyre_wear:>7.1%}"
            f"{result.tyre_grip:>7.3f}{fuel:>7.1f}kg{result.fuel_used:>7.3f}"
            f"{result.energy_deployed / 1e6:>7.2f}M{result.energy_harvested / 1e6:>7.2f}"
            f"{energy.state_of_charge(spec.ers):>8.0%}"
        )

    print(
        f"\npeak tread temperature {tyres.peak_surface_temperature:.1f} C"
        f" | permanent damage {tyres.thermal_damage:.1%}"
        f" | fuel used {args.fuel - fuel:.1f} kg"
        f" | energy deployed {energy.deployed_total / 1e6:.1f} MJ"
    )
    if tyres.is_worn_out:
        print("the set is finished -- everything after this is on the canvas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
