"""The regulations, as data (project rule 30).

Nothing in the game knows what a win is worth.  It asks this.  Changing a
season's scoring, its length or its prize money is an edit to ``rules.json``
and no code at all -- which is the point, because those are exactly the numbers
that change between eras and between house rules.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .errors import UnknownEntity
from .paths import data_file

__all__ = ["BudgetRules", "DevelopmentRules", "PointsRules", "PrizeRules", "Rules"]


@dataclass(frozen=True, slots=True)
class PointsRules:
    """What a finishing position is worth."""

    race: tuple[int, ...] = (25, 18, 15, 12, 10, 8, 6, 4, 2, 1)
    sprint: tuple[int, ...] = ()
    fastest_lap: int = 1
    fastest_lap_within_position: int = 10
    """A fastest lap only scores inside this many positions.

    Which is what stops a car three laps down from pitting for softs on the
    last lap and taking a point off the fight at the front."""

    def for_position(self, position: int) -> int:
        """Points for finishing ``position`` (1-based).  Zero outside them."""
        if 1 <= position <= len(self.race):
            return self.race[position - 1]
        return 0

    def fastest_lap_points(self, position: int) -> int:
        if position <= self.fastest_lap_within_position:
            return self.fastest_lap
        return 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "race": list(self.race),
            "sprint": list(self.sprint),
            "fastest_lap": self.fastest_lap,
            "fastest_lap_within_position": self.fastest_lap_within_position,
        }


@dataclass(frozen=True, slots=True)
class BudgetRules:
    """Money, in millions."""

    cap: float = 135.0
    starting_budget: float = 145.0
    bankruptcy_limit: float = -25.0
    """How far a team may go under before the game stops it."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "cap": self.cap,
            "starting_budget": self.starting_budget,
            "bankruptcy_limit": self.bankruptcy_limit,
        }


@dataclass(frozen=True, slots=True)
class PrizeRules:
    """End-of-season payout, in millions."""

    per_position: tuple[float, ...] = ()
    per_point: float = 0.35

    def payout(self, position: int, points: int) -> float:
        base = (
            self.per_position[position - 1]
            if 1 <= position <= len(self.per_position)
            else 0.0
        )
        return base + self.per_point * points

    def to_dict(self) -> dict[str, Any]:
        return {"per_position": list(self.per_position), "per_point": self.per_point}


@dataclass(frozen=True, slots=True)
class DevelopmentRules:
    """How research turns into car performance.

    ``diminishing_returns_exponent`` below one is the whole balance of the
    development game: progress in an area goes as ``invested ** e``, so the
    tenth upgrade to the aerodynamics is worth a fraction of the first and a
    team that pours everything into one box beats nobody.
    """

    rd_points_per_round_base: float = 100.0
    facility_multiplier_per_level: float = 0.18
    diminishing_returns_exponent: float = 0.62

    def to_dict(self) -> dict[str, Any]:
        return {
            "rd_points_per_round_base": self.rd_points_per_round_base,
            "facility_multiplier_per_level": self.facility_multiplier_per_level,
            "diminishing_returns_exponent": self.diminishing_returns_exponent,
        }


@dataclass(frozen=True, slots=True)
class Rules:
    """One era's regulations."""

    season_length: int = 22
    cars_per_team: int = 2
    points: PointsRules = field(default_factory=PointsRules)
    budget: BudgetRules = field(default_factory=BudgetRules)
    prize_money: PrizeRules = field(default_factory=PrizeRules)
    development: DevelopmentRules = field(default_factory=DevelopmentRules)

    # -- persistence ---------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "season_length": self.season_length,
            "cars_per_team": self.cars_per_team,
            "points": self.points.to_dict(),
            "budget": self.budget.to_dict(),
            "prize_money": self.prize_money.to_dict(),
            "development": self.development.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Rules:
        points = data.get("points", {})
        budget = data.get("budget", {})
        prize = data.get("prize_money", {})
        development = data.get("development", {})
        return cls(
            season_length=int(data.get("season_length", 22)),
            cars_per_team=int(data.get("cars_per_team", 2)),
            points=PointsRules(
                race=tuple(points.get("race", PointsRules.race)),
                sprint=tuple(points.get("sprint", ())),
                fastest_lap=int(points.get("fastest_lap", 1)),
                fastest_lap_within_position=int(
                    points.get("fastest_lap_within_position", 10)
                ),
            ),
            budget=BudgetRules(
                cap=float(budget.get("cap", 135.0)),
                starting_budget=float(budget.get("starting_budget", 145.0)),
                bankruptcy_limit=float(budget.get("bankruptcy_limit", -25.0)),
            ),
            prize_money=PrizeRules(
                per_position=tuple(float(v) for v in prize.get("per_position", ())),
                per_point=float(prize.get("per_point", 0.35)),
            ),
            development=DevelopmentRules(
                rd_points_per_round_base=float(
                    development.get("rd_points_per_round_base", 100.0)
                ),
                facility_multiplier_per_level=float(
                    development.get("facility_multiplier_per_level", 0.18)
                ),
                diminishing_returns_exponent=float(
                    development.get("diminishing_returns_exponent", 0.62)
                ),
            ),
        )

    @classmethod
    def load(cls, path: Any = None) -> Rules:
        """Read the shipped rules, or another set."""
        target = data_file("rules.json") if path is None else path
        try:
            payload = json.loads(open(target, encoding="utf-8").read())
        except FileNotFoundError as error:  # pragma: no cover - configuration
            raise UnknownEntity(f"no rules file at {target}") from error
        return cls.from_dict(payload)
