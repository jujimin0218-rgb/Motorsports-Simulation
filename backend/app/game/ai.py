"""The teams the player is racing against.

The rule this module is written to (project rule 27): **the AI does not
cheat.**  It runs the same simulation, reads the same numbers the player can
read, spends the same money under the same cost cap, and its cars are built by
the same adapter.  Raising the difficulty makes it *decide better* -- it never
makes it faster.

What that leaves it to actually do is the interesting part, because these are
the same decisions the player is making:

**Where to develop.**  Not "the weakest area", which is the obvious answer and
the wrong one.  The right question is where the next hundred points buy the
most *lap time over the races that are left* -- so a team looking at eight
power circuits develops its engine even if its aerodynamics are worse, and the
same team in October develops nothing at all because the parts would arrive
after the flag.

**When to commit.**  Research banked is research not on the car; research spent
on a project that arrives too late is worse than useless.  Money and cost-cap
allowance are two separate things to run out of, and a good team watches both.

**Who to drive.**  At the end of a season the AI looks at whether a free agent
would improve one of its cars *and would sign*, which is not the same question
as who is best available.

Difficulty is one number, ``ai_quality``.  It blurs the AI's reading of what a
circuit needs and how much of its allowance to commit -- an easy AI develops
the wrong thing at the wrong time, a hard one does what a good team would do.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from f1_race_engine.core.rng import RandomStream

from .car import AREA_NAMES
from .contracts import Offer, evaluate, market_asking_price, sign
from .development import (
    COST_PER_POINT,
    MAXIMUM_ROUNDS,
    commission,
    development_gain,
)
from .errors import GameError
from .settings import Difficulty

if TYPE_CHECKING:  # pragma: no cover
    from .state import GameState

__all__ = ["AiDecision", "run_ai_development", "run_ai_transfers"]


@dataclass(frozen=True, slots=True)
class AiDecision:
    """What one AI team chose to do, and what it thought it was doing."""

    team_id: str
    action: str
    detail: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"team": self.team_id, "action": self.action, **self.detail}


def remaining_demand(state: GameState, from_round: int) -> dict[str, float]:
    """What the rest of the season asks of a car, area by area.

    The whole reason an AI's development is worth watching: a team with eight
    power circuits left and two street circuits should build an engine, and the
    same team with the order reversed should not.  Nobody tells it that -- it
    reads the calendar, which the player can read too.
    """
    demand = {name: 0.0 for name in AREA_NAMES}
    rounds = 0
    for entry in state.calendar:
        if entry.number < from_round or entry.is_complete:
            continue
        weights = state.calendar.circuit(entry.circuit_id).area_weights()
        for name in AREA_NAMES:
            demand[name] += weights[name]
        rounds += 1
    if rounds == 0:
        return demand
    return {name: value / rounds for name, value in demand.items()}


def _blur(value: float, quality: float, stream: RandomStream) -> float:
    """How wrong the AI is allowed to be about a number it can see.

    At quality 1.0 it reads it correctly.  Lower, and it misjudges -- which is
    what an easy opponent should be, rather than one that has been handed a
    slower car.
    """
    spread = 0.55 * (1.0 - quality)
    return value * (1.0 + spread * (stream.random() - 0.5) * 2.0)


def _best_area(
    state: GameState, team_id: str, points: float, quality: float, stream: RandomStream
) -> tuple[str, float]:
    """Where this team's next ``points`` of research are worth the most.

    Gain in an area, multiplied by how much the remaining calendar asks for
    that area.  Both halves matter: developing a strength nobody needs is as
    wasteful as developing a weakness nobody needs.
    """
    team = state.team(team_id)
    demand = remaining_demand(state, state.current_round_number)
    rules = state.rules.development

    scored: list[tuple[float, str]] = []
    for area in AREA_NAMES:
        gain = development_gain(team, area, points, rules)
        value = _blur(gain * demand[area], quality, stream)
        scored.append((value, area))
    scored.sort(reverse=True)
    return scored[0][1], scored[0][0]


def run_ai_development(state: GameState) -> list[AiDecision]:
    """Let every AI team spend its round.

    Called once a round, after the race.  The player's own team is skipped --
    those are the player's decisions.
    """
    quality = state.settings.difficulty.ai_quality
    current = state.current_round_number
    remaining = sum(1 for entry in state.calendar if not entry.is_complete)
    cap = state.rules.budget.cap
    decisions: list[AiDecision] = []

    for team in state.teams.values():
        if team.id == state.player_team:
            continue
        stream = state.round_rng(current).stream("ai.development", team=team.id)

        # A project that arrives after the flag is research thrown away, and
        # the AI knows what month it is.
        if remaining <= 1:
            decisions.append(
                AiDecision(team.id, "hold", {"reason": "no rounds left to develop for"})
            )
            continue

        # How much to commit.  A good team commits most of what it has when
        # there is season left to use it, and keeps something back late.
        eagerness = 0.45 + 0.45 * quality
        if remaining < MAXIMUM_ROUNDS:
            eagerness *= remaining / MAXIMUM_ROUNDS
        points = team.rd_points * _blur(eagerness, quality, stream)

        affordable_by_money = max(0.0, team.budget - 12.0) / COST_PER_POINT
        affordable_by_cap = team.cap_headroom(cap) / COST_PER_POINT
        points = min(points, affordable_by_money, affordable_by_cap)
        if points < 25.0:
            decisions.append(
                AiDecision(
                    team.id,
                    "hold",
                    {
                        "reason": "nothing worth committing",
                        "rd_points": round(team.rd_points, 1),
                        "budget": round(team.budget, 1),
                        "cap_headroom": round(team.cap_headroom(cap), 1),
                    },
                )
            )
            continue

        area, expected = _best_area(state, team.id, points, quality, stream)
        # Rushing is for a team that is behind and running out of season.
        behind = max(0.0, 0.92 - team.car.overall)
        rushed = min(1.0, behind * 3.0) if remaining < 8 else 0.0

        try:
            upgrade = commission(
                team,
                area=area,
                points=points,
                current_round=current,
                rules=state.rules.development,
                rushed=rushed,
                upgrade_id=f"{state.season}-{current}-{team.id}",
                cap=cap,
            )
        except GameError as error:
            decisions.append(AiDecision(team.id, "hold", {"reason": str(error)}))
            continue

        state.upgrades.append(upgrade)
        decisions.append(
            AiDecision(
                team.id,
                "commission",
                {
                    "area": area,
                    "points": round(points, 1),
                    "cost": round(upgrade.cost, 2),
                    "arrives_at_round": upgrade.arrives_at_round,
                    "expected_gain": round(upgrade.expected_gain, 5),
                    "rushed": round(rushed, 2),
                },
            )
        )
    return decisions


def run_ai_transfers(state: GameState) -> list[AiDecision]:
    """Let every AI team look at its driver line-up.

    Run between seasons.  The question is not "who is the best free agent" but
    "would a free agent improve one of my cars *and* sign for me", which is a
    different and much more interesting question for a team at the back.
    """
    quality = state.settings.difficulty.ai_quality
    decisions: list[AiDecision] = []
    free = sorted(state.free_agents, key=lambda d: -d.overall)
    if not free:
        return decisions

    for team in state.teams.values():
        if team.id == state.player_team or not team.drivers:
            continue
        stream = state.rng.season(state.season).stream("ai.transfers", team=team.id)

        seat = min(
            range(len(team.drivers)), key=lambda i: state.driver(team.drivers[i]).overall
        )
        incumbent = state.driver(team.drivers[seat])
        if incumbent.contract is not None and not incumbent.contract.expires_this_season:
            continue

        for candidate in free:
            if candidate.overall <= incumbent.overall + 0.01:
                continue
            asking = market_asking_price(candidate, team)
            offer = Offer(
                team_id=team.id,
                driver_id=candidate.id,
                salary=round(asking * _blur(1.05, quality, stream), 2),
                seasons=2,
            )
            if offer.salary > team.budget * 0.30:
                continue
            verdict = evaluate(offer, candidate, team, stream=stream)
            if not verdict.accepted:
                continue

            incumbent.team = None
            incumbent.contract = None
            team.drivers[seat] = candidate.id
            sign(offer, candidate, team, seat=seat)
            free.remove(candidate)
            decisions.append(
                AiDecision(
                    team.id,
                    "signed",
                    {
                        "driver": candidate.id,
                        "replaced": incumbent.id,
                        "salary": offer.salary,
                    },
                )
            )
            break
    return decisions
