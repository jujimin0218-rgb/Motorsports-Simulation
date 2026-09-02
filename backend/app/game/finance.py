"""Money: where it comes from, where it goes, and what happens when it runs out.

The economy exists to make the three interesting decisions cost something
against each other.  A driver is paid every round whether the car is any good or
not; an upgrade is paid for once and pays back for the rest of the season; a
facility is paid for now and pays back for years.  A team that spends on all
three runs out, and the cost cap means the biggest budget cannot simply buy all
of them either.

Nothing here is a per-round tax pulled out of the air.  Every line is a thing
the team has: two salaries it agreed to, an engine deal it signed, a head count
it chose, and the sponsors it managed to attract.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .errors import UnknownEntity
from .paths import data_file
from .rules import Rules
from .standings import Standings

__all__ = [
    "Ledger",
    "LedgerLine",
    "Sponsor",
    "SponsorDeal",
    "load_sponsors",
    "round_costs",
    "season_settlement",
]

#: Running a car for a round: freight, tyres, people on the road.  Per team,
#: in millions, scaled by head count -- a bigger team is more expensive to move.
OPERATING_COST_PER_ROUND = 1.6

#: What one person costs for a round, in millions.
STAFF_COST_PER_ROUND = 0.0013


@dataclass(frozen=True, slots=True)
class LedgerLine:
    label: str
    amount: float
    """Positive is income, negative is spending."""

    def to_dict(self) -> dict[str, Any]:
        return {"label": self.label, "amount": round(self.amount, 4)}


@dataclass(frozen=True, slots=True)
class Ledger:
    """What a round or a season did to a team's money."""

    team_id: str
    lines: tuple[LedgerLine, ...] = ()

    @property
    def total(self) -> float:
        return sum(line.amount for line in self.lines)

    @property
    def income(self) -> float:
        return sum(line.amount for line in self.lines if line.amount > 0)

    @property
    def spending(self) -> float:
        return -sum(line.amount for line in self.lines if line.amount < 0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "team": self.team_id,
            "lines": [line.to_dict() for line in self.lines],
            "income": round(self.income, 4),
            "spending": round(self.spending, 4),
            "total": round(self.total, 4),
        }


# -- sponsors ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Sponsor:
    """A bet on a team.

    The base payment is for the space on the car.  The bonus is for the result,
    and the penalty is what it costs to promise something and not deliver --
    which is what stops a struggling team from signing the most demanding
    sponsor on the board just for the headline number.
    """

    id: str
    name: str
    sector: str = ""
    base_payment: float = 10.0
    reputation_required: float = 0.4
    target_kind: str = "constructors_position"
    target_value: float = 5.0
    bonus: float = 0.0
    penalty: float = 0.0
    seasons: int = 2

    def available_to(self, reputation: float) -> bool:
        """The big money will not go on a car nobody is watching."""
        return reputation >= self.reputation_required

    def met_by(self, standing: Any) -> bool:
        """Was the target hit?"""
        if standing is None:
            return False
        if self.target_kind == "constructors_position":
            return standing.position <= self.target_value
        if self.target_kind == "wins":
            return standing.wins >= self.target_value
        if self.target_kind == "podiums":
            return standing.podiums >= self.target_value
        if self.target_kind == "points_finishes":
            return standing.points >= self.target_value
        raise UnknownEntity(f"unknown sponsor target {self.target_kind!r}")

    def describe_target(self) -> str:
        return {
            "constructors_position": f"constructors P{int(self.target_value)} or better",
            "wins": f"{int(self.target_value)} win(s)",
            "podiums": f"{int(self.target_value)} podium(s)",
            "points_finishes": f"{int(self.target_value)} points",
        }.get(self.target_kind, self.target_kind)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "sector": self.sector,
            "base_payment": self.base_payment,
            "reputation_required": self.reputation_required,
            "target": {"kind": self.target_kind, "value": self.target_value},
            "target_description": self.describe_target(),
            "bonus": self.bonus,
            "penalty": self.penalty,
            "seasons": self.seasons,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Sponsor:
        target = data.get("target", {})
        return cls(
            id=str(data["id"]),
            name=str(data.get("name", data["id"])),
            sector=str(data.get("sector", "")),
            base_payment=float(data.get("base_payment", 10.0)),
            reputation_required=float(data.get("reputation_required", 0.4)),
            target_kind=str(target.get("kind", "constructors_position")),
            target_value=float(target.get("value", 5)),
            bonus=float(data.get("bonus", 0.0)),
            penalty=float(data.get("penalty", 0.0)),
            seasons=int(data.get("seasons", 2)),
        )


@dataclass(slots=True)
class SponsorDeal:
    """A sponsor a team has actually signed."""

    sponsor_id: str
    team_id: str
    seasons_remaining: int
    signed_in_season: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "sponsor": self.sponsor_id,
            "team": self.team_id,
            "seasons_remaining": self.seasons_remaining,
            "signed_in_season": self.signed_in_season,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SponsorDeal:
        return cls(
            sponsor_id=str(data["sponsor"]),
            team_id=str(data["team"]),
            seasons_remaining=int(data.get("seasons_remaining", 1)),
            signed_in_season=int(data.get("signed_in_season", 0)),
        )


def load_sponsors() -> dict[str, Sponsor]:
    path = data_file("sponsors.json")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:  # pragma: no cover - configuration
        raise UnknownEntity(f"missing sponsor data at {path}") from error
    return {entry["id"]: Sponsor.from_dict(entry) for entry in payload["sponsors"]}


# -- what a round costs ------------------------------------------------------


def round_costs(state: Any, team_id: str, *, round_number: int) -> Ledger:
    """One round's money, as lines rather than a number.

    Sponsor money arrives spread across the season rather than in a lump, which
    is what keeps a team solvent between races and is also how the real thing
    works.
    """
    team = state.team(team_id)
    rounds = max(1, len(state.calendar))
    lines: list[LedgerLine] = []

    for driver_id in team.drivers:
        profile = state.driver(driver_id)
        if profile.contract is not None:
            lines.append(
                LedgerLine(f"{profile.name} salary", -profile.contract.salary / rounds)
            )

    supplier = state.engine_for(team_id)
    engine_cost = supplier.cost_for(team_id)
    if engine_cost:
        lines.append(LedgerLine(f"{supplier.name} supply", -engine_cost / rounds))

    lines.append(LedgerLine("operations", -OPERATING_COST_PER_ROUND))
    lines.append(LedgerLine("staff", -STAFF_COST_PER_ROUND * team.staff))

    sponsors = load_sponsors()
    for deal in state.sponsor_deals_for(team_id):
        sponsor = sponsors.get(deal.sponsor_id)
        if sponsor is not None:
            lines.append(
                LedgerLine(f"{sponsor.name} sponsorship", sponsor.base_payment / rounds)
            )

    # Prize money for *last* season, paid in instalments through this one.
    # That is how the real thing works, and it is what keeps a team solvent
    # between January and the first cheque -- without it every team on the grid
    # is bankrupt by August and the economy says nothing about anybody.
    prize = state.rules.prize_money.payout(team.prize_position, 0)
    if prize:
        lines.append(LedgerLine(f"prize money (P{team.prize_position})", prize / rounds))

    return Ledger(team_id=team_id, lines=tuple(lines))


def season_settlement(
    state: Any, team_id: str, standings: Standings, rules: Rules
) -> Ledger:
    """End of season: prize money, and whether the sponsors got what they paid for."""
    standing = next(
        (row for row in standings.teams if row.team_id == team_id), None
    )
    lines: list[LedgerLine] = []
    if standing is not None:
        # The position money was already paid across the season on last year's
        # finish; what settles here is what this year's *points* were worth.
        lines.append(
            LedgerLine(
                f"championship bonus (P{standing.position})",
                rules.prize_money.per_point * standing.points,
            )
        )

    sponsors = load_sponsors()
    for deal in state.sponsor_deals_for(team_id):
        sponsor = sponsors.get(deal.sponsor_id)
        if sponsor is None:
            continue
        if sponsor.met_by(standing):
            if sponsor.bonus:
                lines.append(LedgerLine(f"{sponsor.name} bonus", sponsor.bonus))
        elif sponsor.penalty:
            lines.append(LedgerLine(f"{sponsor.name} shortfall", -sponsor.penalty))

    return Ledger(team_id=team_id, lines=tuple(lines))


def apply(ledger: Ledger, team: Any) -> float:
    """Post a ledger to a team's budget and return the new balance.

    Deliberately not :meth:`Team.spend`: a round's costs are not optional and
    refusing them would leave the team in a state where it had run a race it
    had not paid for.  Going under is a real outcome, and the bankruptcy limit
    in the rules is what decides when it becomes fatal.
    """
    team.budget += ledger.total
    return team.budget
