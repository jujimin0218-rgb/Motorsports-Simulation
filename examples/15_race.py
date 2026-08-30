"""Put the whole field on the circuit and run a race.

    python examples/15_race.py [--laps 24] [--track NAME]

Six drivers, three different cars, one set of tyres each and no pit stops.
Nothing in here decides the result: every car is simulated lap by lap through
the same physics, carrying its own tyres, fuel and energy, and the timing
screen is assembled from distance and time (project rule 28) rather than from
anywhere the answer might have been written down.

Phase 6 runs the cars side by side without them interacting -- no dirty air, no
overtaking, no defending. That is Phase 9's job, and faking it here would only
have to be unpicked later. What is real already: who is quick, who looks after
a tyre, who gets lapped, and what each of those is worth in seconds.
"""

from __future__ import annotations

import argparse
import time

from f1_race_engine.core.rng import RngHub
from f1_race_engine.core.units import format_lap_time
from f1_race_engine.driver.io import load_driver_lineup
from f1_race_engine.race import RaceEntry, RaceSession
from f1_race_engine.track.io import load_track
from f1_race_engine.tyres.io import load_builtin_compounds
from f1_race_engine.vehicle import Vehicle, VehicleSetup
from f1_race_engine.vehicle.io import load_builtin_vehicle

CARS = ("reference_2024", "power_biased", "aero_biased")
TEAMS = ("Aurora", "Meridian", "Kestrel")
COMPOUNDS = ("S", "M", "M", "H", "M", "S")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--laps", type=int, default=24)
    parser.add_argument("--track", default="synthetic_proving_ground")
    parser.add_argument("--fuel", type=float, default=70.0)
    parser.add_argument("--wing", type=float, default=0.5)
    parser.add_argument("--seed", type=int, default=20260812)
    parser.add_argument("--splits", type=int, default=4,
                        help="how many mid-race timing screens to print")
    args = parser.parse_args()

    track = load_track(args.track)
    compounds = load_builtin_compounds()
    drivers = load_driver_lineup()

    entries = []
    for index, driver in enumerate(drivers):
        spec = load_builtin_vehicle(CARS[index % len(CARS)])
        entry = RaceEntry(
            car_number=index + 1,
            driver=driver,
            vehicle=Vehicle(spec, VehicleSetup(wing_level=args.wing)),
            team=TEAMS[index % len(TEAMS)],
            fuel_mass=args.fuel,
            grid_position=index + 1,
        )
        entry.fit(compounds[COMPOUNDS[index % len(COMPOUNDS)]])
        entries.append(entry)

    print(f"{track.name} -- {args.laps} laps -- {len(entries)} cars\n")
    for entry in entries:
        print(
            f"  {entry.label}  {entry.driver.name:<18}{entry.team:<10}"
            f"{entry.vehicle.name:<18}{entry.compound}"
        )

    session = RaceSession(track, entries, laps=args.laps, rng=RngHub(args.seed))
    started = time.perf_counter()
    result = session.run()
    print(f"\n({time.perf_counter() - started:.1f} s of simulation)\n")

    # Mid-race screens, each one asked for at a moment in time rather than at a
    # lap boundary -- the tower does not care which.
    finish = result.classification[0].total_time
    for index in range(1, args.splits):
        moment = finish * index / args.splits
        rows = session.timing.snapshot_at(moment)
        leader = rows[0]
        print(
            f"-- {moment / 60:.0f}:{moment % 60:04.1f} "
            f"(lap {leader.laps_completed + 1}) " + "-" * 40
        )
        for row in rows:
            entry = next(e for e in entries if e.car_number == row.car_number)
            print(
                f"{row.position:>3}  {entry.label}  {entry.driver.name:<18}"
                f"{row.gap_to_leader.formatted if row.position > 1 else 'leader':>10}"
                f"{row.interval.formatted if row.position > 1 else '':>10}"
            )
        print()

    print(result.format())

    winner = result.winner
    print(
        f"\n{winner.driver_name} wins for {winner.team} in {winner.formatted_time}, "
        f"averaging {format_lap_time(winner.total_time / winner.laps_completed)} a lap "
        f"and finishing on {winner.tyre_wear:.0%} worn {winner.compound}s "
        f"with {winner.fuel_remaining:.1f} kg left."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
