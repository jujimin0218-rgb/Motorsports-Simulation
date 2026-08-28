"""Two cars fighting, and what it costs both of them.

    python examples/18_racing.py [--laps 12] [--track NAME]

Phase 9 is the phase where the cars can finally see each other, and everything
it produces comes out of one hole in the air (project rule 29):

* behind another car the air is already bent, so a wing makes less downforce --
  which is why following is hard, and why it is hardest exactly where the
  corners are quickest;
* the same hole is a hole, so there is less air to push out of the way -- which
  is why a slipstream is worth speed on a straight;
* DRS opens that gap further, but only for a car that was within a second at
  the detection point.

Nothing is rolled for.  A car gets past when the gap has closed to a car length
somewhere the road is wide enough, and the gap closes because one car was
quicker than the other over the stretch of road behind them.

Run it at both circuits.  Where there are straights, the tow does the work and
a quicker car gets by in a lap or two; where there are not, it can sit there
for the whole race.
"""

from __future__ import annotations

import argparse

from f1_race_engine.core.rng import RngHub
from f1_race_engine.driver import Driver, DriverAttributes
from f1_race_engine.race import RaceEntry, RaceSession
from f1_race_engine.track.io import load_track
from f1_race_engine.tyres.io import load_builtin_compounds
from f1_race_engine.vehicle import Vehicle, VehicleSetup
from f1_race_engine.vehicle.io import load_builtin_vehicle


def driver(name: str, pace: float, racecraft: float) -> Driver:
    return Driver(
        name=name, abbreviation=name[:3].upper(),
        attributes=DriverAttributes(
            pace=pace, qualifying=pace, racecraft=racecraft, consistency=1.0,
            tyre_management=0.90, braking=pace, cornering=pace,
            throttle_control=pace, wet_skill=0.90, risk_management=1.0,
        ),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--laps", type=int, default=12)
    parser.add_argument("--track", default="synthetic_power_circuit")
    parser.add_argument("--leader-pace", type=float, default=0.88)
    parser.add_argument("--chaser-pace", type=float, default=0.96)
    parser.add_argument("--defence", type=float, default=0.92)
    parser.add_argument("--fuel", type=float, default=50.0)
    parser.add_argument("--seed", type=int, default=4)
    args = parser.parse_args()

    track = load_track(args.track)
    compounds = load_builtin_compounds()
    spec = load_builtin_vehicle("reference_2024")

    def field():
        pairs = (
            ("Leader", args.leader_pace, args.defence),
            ("Chaser", args.chaser_pace, 0.90),
        )
        out = []
        for index, (name, pace, craft) in enumerate(pairs):
            entry = RaceEntry(
                car_number=index + 1, driver=driver(name, pace, craft),
                vehicle=Vehicle(spec, VehicleSetup(wing_level=0.5)),
                fuel_mass=args.fuel, grid_position=index + 1,
            )
            entry.fit(compounds["M"])
            out.append(entry)
        return out

    print(f"{track.name} -- {args.laps} laps")
    print(
        f"car 1 pace {args.leader_pace:.2f} racecraft {args.defence:.2f} starts P1\n"
        f"car 2 pace {args.chaser_pace:.2f} racecraft 0.90 starts P2\n"
    )

    racing = RaceSession(
        track, field(), laps=args.laps, rng=RngHub(args.seed),
        racing=True, standing_start=True,
    ).run()

    # The same race with the cars unable to see each other, which is the pace
    # each of them actually had.
    alone = RaceSession(
        track, field(), laps=args.laps, rng=RngHub(args.seed),
        racing=False, standing_start=True,
    ).run()

    print(racing.format())

    print("\nwhat the fight cost")
    header = f"{'car':>4}{'racing':>11}{'clear air':>12}{'lost':>8}"
    print(header)
    print("-" * len(header))
    for row in racing.classification:
        clear = alone.of(row.car_number).total_time
        print(
            f"{row.car_number:>4}{row.formatted_time:>11}"
            f"{alone.of(row.car_number).formatted_time:>12}"
            f"{row.total_time - clear:>+8.2f}"
        )

    if racing.overtakes:
        print("\novertakes")
        for move in racing.overtakes:
            where = "with DRS" if move.drs else ""
            print(
                f"  lap {move.lap:>2} at {move.distance:>6.0f} m: "
                f"car {move.attacker} passed car {move.defender} {where}"
            )
    else:
        print("\nnobody got past: the gap never closed anywhere it could be used")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
