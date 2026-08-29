"""Phase 3: the management game, over a season.

    python backend/scripts/phase3_demo.py [--rounds 8]

Races are skipped here on purpose -- Phase 2 already showed the engine running
one, and a full round is ten minutes.  What this shows is everything *between*
the races: research earned and spent, parts arriving and failing, money coming
in and going out, sponsors, the cost cap biting, and nine AI teams making the
same decisions with the same information.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.game.ai import remaining_demand, run_ai_development
from app.game.calendar import RoundPhase
from app.game.contracts import market_asking_price
from app.game.development import resolve
from app.game.newgame import new_game
from app.services import management_service as ms
from app.services import round_service


def rule(title: str) -> None:
    print(f"\n{title}\n{'-' * len(title)}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", type=int, default=8)
    parser.add_argument("--team", default="harrow")
    args = parser.parse_args()

    state = new_game(player_team=args.team, seed=20260101)
    player = state.player
    start_car = player.car.overall
    start_budget = player.budget

    rule(f"{player.name} -- starting position")
    print(f"  car {start_car:.4f}   budget {start_budget:.1f}M   reputation {player.reputation:.2f}")
    print(f"  facilities {player.facilities.to_dict()}")
    print(f"  staff {player.staff}")

    rule("Sponsors this team can reach")
    for row in ms.available_sponsors(state, player.id):
        mark = "available" if row["available"] else (
            f"needs +{row['reputation_shortfall']:.2f} reputation"
        )
        print("  %-20s %5.1fM/season  %-28s %s"
              % (row["name"], row["base_payment"], row["target_description"], mark))
    for row in ms.available_sponsors(state, player.id):
        if row["available"]:
            got = ms.sign_sponsor(state, player.id, row["id"])
            print(f"  -> signed {got['sponsor']['name']} for {got['seasons']} seasons")
            break

    rule("What the season asks for")
    for area, value in sorted(remaining_demand(state, 1).items(), key=lambda kv: -kv[1]):
        print(f"  {area:<18} {value:.3f}")

    rule(f"{args.rounds} rounds of the management loop")
    print("  (races skipped -- see phase2_demo.py for the engine running one)")
    for number in range(1, args.rounds + 1):
        entry = state.round(number)
        # Walk the weekend without running the sessions: practice, qualifying,
        # strategy, race, result.
        while entry.phase is not RoundPhase.RESULT:
            entry.advance()

        report = round_service.run_development(state)
        detail = report.detail

        # The player spends, using the same information the AI has.
        options = ms.development_options(state, player.id)
        best = max(
            options["areas"],
            key=lambda a: a["gain_at_current_points"] * a["remaining_demand"],
        )
        note = ""
        if options["rd_points"] > 120 and options["budget"] > 20:
            try:
                upgrade = ms.commission_upgrade(
                    state, player.id, area=best["area"],
                    points=options["rd_points"] * 0.8,
                )
                note = (f"commissioned {upgrade.area} "
                        f"({upgrade.points:.0f} pts, {upgrade.cost:.1f}M, R{upgrade.arrives_at_round})")
            except Exception as error:  # noqa: BLE001 - shown, not swallowed
                note = f"could not commission: {error}"
        else:
            note = "held"

        fitted = [u for u in detail["upgrades_fitted"] if u["team"] == player.id]
        arrivals = "".join(
            f"  [{u['area']} {u['status']} {u['actual_gain']:+.4f}]" for u in fitted
        )
        print("  R%-2d  car %.4f  budget %6.1fM  cap left %5.1fM  research %5.0f  %s%s"
              % (number, player.car.overall, player.budget,
                 player.cap_headroom(state.rules.budget.cap),
                 player.rd_points, note, arrivals))

    rule("What the AI did with the same information")
    for decision in run_ai_development(state)[:5]:
        team = state.team(decision.team_id)
        print("  %-24s %s" % (team.name, decision.to_dict()))

    rule("Where everybody's car ended up")
    ordered = sorted(state.teams.values(), key=lambda t: -t.car.overall)
    for team in ordered:
        marker = " <-- you" if team.id == player.id else ""
        print("  %-24s %.4f   budget %6.1fM   cap spent %5.1fM%s"
              % (team.name, team.car.overall, team.budget, team.season_spending, marker))

    rule("The player's season so far")
    money = ms.finances(state, player.id)
    print(f"  car   {start_car:.4f} -> {player.car.overall:.4f}  ({player.car.overall - start_car:+.4f})")
    print(f"  money {start_budget:.1f}M -> {player.budget:.1f}M  ({player.budget - start_budget:+.1f}M)")
    print(f"  projected to the flag: {money['projected_to_season_end']:.1f}M")
    print(f"  cost cap: {money['season_spending']:.1f}M of {money['cap']:.0f}M spent")

    rule("A driver the player might want")
    target = max(state.free_agents, key=lambda d: d.overall)
    asking = market_asking_price(target, player)
    for multiplier in (0.5, 1.0, 1.5):
        answer = ms.negotiate(
            state, player.id, target.id, salary=round(asking * multiplier, 1)
        )
        print("  %-22s at %5.1fM -> %-6s %s"
              % (target.name, asking * multiplier,
                 "SIGN" if answer["accepted"] else "no", answer["reason"]))
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
