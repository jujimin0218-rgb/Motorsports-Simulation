"""What the grid's ratings are worth, in seconds.

A Formula 1 field spans roughly two to three per cent of lap time between the
quickest car and the slowest -- about two seconds on a ninety-second lap, and
the gap between the top two teams is usually a couple of tenths.  The spans in
``app.adapters.car_builder`` are set from this measurement rather than chosen.

    python backend/scripts/calibrate_spread.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from f1_race_engine.core.units import format_lap_time
from f1_race_engine.physics import compute_lap_time
from f1_race_engine.track.io import load_track
from f1_race_engine.vehicle import VehicleSetup

from app.adapters.car_builder import build_vehicle
from app.game.newgame import new_game


def main() -> int:
    game = new_game(player_team="harrow", seed=1)
    circuits = [
        ("autodromo_nazionale_monza", 0.35),
        ("silverstone_circuit", 0.65),
        ("circuit_de_monaco", 0.95),
    ]

    for circuit_id, wing in circuits:
        circuit = game.calendar.circuit(circuit_id)
        track = load_track(circuit.physics_track)
        rows = []
        for team in game.teams.values():
            car = build_vehicle(
                team, game.engine_for(team.id), setup=VehicleSetup(wing_level=wing)
            )
            result = compute_lap_time(track, car, mass=car.total_mass(35.0))
            rows.append((result.lap_time, team))
        rows.sort()
        best = rows[0][0]
        print(f"\n{circuit.name}  (wing {wing:.2f}, {circuit.physics_track})")
        for lap, team in rows:
            print(
                "  %-24s %s  %+6.3f s  %+5.2f%%  (rating here %.4f)"
                % (
                    team.name,
                    format_lap_time(lap),
                    lap - best,
                    100.0 * (lap / best - 1.0),
                    team.car.rating_for(circuit.area_weights()),
                )
            )
        spread = rows[-1][0] - best
        print(
            "  field spread %.3f s (%.2f%%)   top two split %.3f s"
            % (spread, 100.0 * spread / best, rows[1][0] - best)
        )
    print("\nreal Formula 1: about 2-3%% front to back, a couple of tenths at the top")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
