"""A race in which things go wrong (Phase 11).

    python examples/19_race_events.py [--laps N] [--seed N] [--track NAME]

Runs a full field with hazards on and prints what broke, who hit whom, what
race control did about it, and what the race looked like afterwards.

Nothing here decides an outcome.  Failures are a hazard per kilometre driven,
contact is a hazard per lap spent fighting somebody, and the flag is a response
to what happened rather than a cause of it -- so the race that comes out is the
one the cars drove.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from f1_race_engine.core.rng import RngHub
from f1_race_engine.core.units import format_lap_time
from f1_race_engine.driver.io import builtin_driver_names, load_builtin_driver
from f1_race_engine.race import RaceEntry, RaceSession
from f1_race_engine.race.strategy import RaceStrategy
from f1_race_engine.track.io import builtin_track_names, load_track
from f1_race_engine.tyres.io import load_builtin_compounds
from f1_race_engine.vehicle import Vehicle, VehicleSetup
from f1_race_engine.vehicle.io import load_builtin_vehicle


def build_field(compounds, wing: float) -> list[RaceEntry]:
    spec = load_builtin_vehicle("reference_2024")
    entries = []
    for index, name in enumerate(builtin_driver_names()):
        entry = RaceEntry(
            car_number=index + 1,
            driver=load_builtin_driver(name),
            vehicle=Vehicle(spec, VehicleSetup(wing_level=wing)),
            fuel_mass=80.0,
            grid_position=index + 1,
            compounds=compounds.compounds,
            strategy=RaceStrategy(),
        )
        entry.fit(compounds["M"])
        entries.append(entry)
    return entries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--laps", type=int, default=24)
    parser.add_argument("--seed", type=int, default=20260812)
    parser.add_argument("--track", default="synthetic_proving_ground",
                        choices=builtin_track_names())
    parser.add_argument("--wing", type=float, default=0.7)
    parser.add_argument("--quiet", action="store_true", help="no hazards, for comparison")
    args = parser.parse_args()

    track = load_track(args.track)
    compounds = load_builtin_compounds("reference_2024")
    session = RaceSession(
        track,
        build_field(compounds, args.wing),
        laps=args.laps,
        rng=RngHub(args.seed),
        racing=True,
        standing_start=True,
        hazards=not args.quiet,
    )
    result = session.run()
    print(result.format())

    if result.incidents:
        print("\nwhat went wrong")
        for incident in result.incidents:
            print(f"  {incident}")
    else:
        print("\nnothing went wrong -- which happens, and is worth seeing")

    if result.flags:
        print("\nrace control")
        for lap, flag, reason in result.flags:
            print(f"  lap {lap:>3}  {reason}")

    finishers = len(result.finishers)
    print(
        f"\n{finishers} of {len(session.entries)} cars saw the flag; "
        f"{len(result.retirements)} did not"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
