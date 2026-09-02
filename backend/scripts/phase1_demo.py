"""Phase 1, end to end, as a thing you can watch happen.

    python backend/scripts/phase1_demo.py

New game -> a 22-round calendar -> teams -> drivers -> a season part-run ->
save -> load -> the same game back.  No race engine yet: that is Phase 2.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.game.calendar import RoundPhase
from app.game.newgame import available_teams, new_game
from app.game.standings import RaceOutcome
from app.services.storage import SaveStore


def rule(title: str) -> None:
    print(f"\n{title}\n{'-' * len(title)}")


def main() -> int:
    rule("Teams you could take over")
    for row in available_teams():
        print(
            "  %-24s car %.3f  budget %6.1fM  rep %.2f  %s"
            % (
                row["name"], row["car_rating"], row["budget"], row["reputation"],
                ", ".join(row["drivers"]),
            )
        )

    game = new_game(player_team="harrow", seed=20260101)
    rule(f"New game: {game.name}")
    print(f"  seed {game.seed}  season {game.season}  player {game.player.name}")
    print(
        "  %d teams, %d drivers (%d free agents), %d engine suppliers"
        % (len(game.teams), len(game.drivers), len(game.free_agents), len(game.engines))
    )
    print(f"  engine: {game.engine_for(game.player_team).name}")
    print("  drivers: " + ", ".join(game.driver(d).name for d in game.player.drivers))

    rule("Calendar")
    for entry in list(game.calendar)[:3] + list(game.calendar)[-2:]:
        circuit = game.calendar.circuit(entry.circuit_id)
        print(
            "  R%-2d %-34s %5.3f km x %2d laps = %5.1f km  [%s]"
            % (
                entry.number, circuit.name, circuit.length_km, entry.laps,
                circuit.race_distance_km, circuit.physics_track.replace("synthetic_", ""),
            )
        )
        if entry.number == 3:
            print("      ...")

    rule("What each circuit asks of a car")
    for cid in ("autodromo_nazionale_monza", "circuit_de_monaco", "silverstone_circuit"):
        circuit = game.calendar.circuit(cid)
        weights = circuit.area_weights()
        best = max(weights, key=weights.get)
        print(
            "  %-34s wants %-16s (%.2f)  |  power %.2f  downforce %.2f"
            % (circuit.name, best, weights[best],
               circuit.power_sensitivity, circuit.downforce_requirement)
        )

    rule("The same car, rated at three circuits")
    car = game.player.car
    for cid in ("autodromo_nazionale_monza", "circuit_de_monaco", "silverstone_circuit"):
        circuit = game.calendar.circuit(cid)
        print(
            "  %-34s %.4f   (overall %.4f)"
            % (circuit.name, car.rating_for(circuit.area_weights()), car.overall)
        )

    # Run four rounds on paper.  Phase 2 replaces this with the race engine.
    rule("Four rounds, scored on the rules file")
    order = sorted(
        (d for d in game.drivers.values() if d.team),
        key=lambda d: -d.overall,
    )
    for number in range(1, 5):
        outcomes = []
        for position, profile in enumerate(order, start=1):
            outcomes.append(
                RaceOutcome(
                    round_number=number,
                    driver_id=profile.id,
                    team_id=profile.team or "",
                    position=position,
                    started=position,
                    fastest_lap=(position == 2),
                    pole=(position == 1),
                )
            )
        game.record_outcomes(outcomes)
        entry = game.round(number)
        while not entry.is_complete:
            entry.advance()
        order = order[1:] + order[:1]  # shuffle the front for variety
        print(f"  round {number} scored, phase now {entry.phase.value}")
    print(f"  season is now waiting on round {game.current_round_number}")

    rule("Championship")
    standings = game.standings()
    for row in standings.drivers[:5]:
        print(
            "  P%-2d %-22s %-24s %3d pts  %dW %dP"
            % (row.position, game.driver(row.driver_id).name,
               game.team(row.team_id).name if row.team_id else "",
               row.points, row.wins, row.podiums)
        )
    print("  ...")
    print("  Constructors:")
    for row in standings.teams[:4]:
        print("    P%-2d %-24s %3d pts" % (row.position, game.team(row.team_id).name, row.points))
    player_position = standings.team_position(game.player_team)
    print(f"  {game.player.name} are P{player_position}")

    rule("Save and load")
    with SaveStore(":memory:") as store:
        summary = store.save(game)
        store.autosave(game)
        print(f"  saved {summary.name!r} (season {summary.season}, round {summary.round})")
        print("  slots: " + ", ".join(f"{r.slot or 'manual'}" for r in store.list()))
        restored = store.load(summary.id)
        identical = restored.to_dict() == game.to_dict()
        print(f"  reloaded and identical: {identical}")
        print(
            "  same seed, same next race: %s"
            % (
                restored.round_rng(9).stream("race").random()
                == game.round_rng(9).stream("race").random()
            )
        )
        if not identical:
            return 1

    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
