"""Research, and what it buys.

The whole balance of a season lives in one property of this module: **progress
is concave.**  Research spent in an area goes as ``invested ** e`` with ``e``
below one, so the tenth upgrade to the aerodynamics is worth a fraction of the
first.  A team that pours everything into one box beats nobody, and a team that
is behind everywhere catches up faster than a team that is ahead everywhere
pulls away.  That is the mechanism that stops round three from deciding the
championship, and it is one number in ``rules.json`` rather than a special case.

Three things about an upgrade, and all of them are decisions rather than
formalities:

**It takes time.**  Research commissioned at round five arrives at round eight,
by which point the season may have moved.  Committing to a long project is
committing to it.

**It can fail.**  Not a dice roll on top of a good outcome: the failure chance
falls with the team's facility in that area, so building the factory is what
buys reliability of development as well as speed of it.

**It costs reliability.**  A new part is a part nobody has raced.  The gain
arrives immediately and the fragility wears off over a few rounds, which is why
bringing an upgrade to the last race of a tight championship is a real question.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from f1_race_engine.core.rng import RandomStream

from .car import AREA_NAMES, FACILITY_FOR_AREA
from .errors import InsufficientBudget, UnknownEntity
from .rules import DevelopmentRules
from .team import Team

__all__ = [
    "COST_PER_POINT",
    "Upgrade",
    "UpgradeStatus",
    "commission",
    "development_gain",
    "research_earned",
]

#: What a research point costs to turn into a part, in millions.  Research is
#: the design; this is building it, and it is why a small team with a good idea
#: still cannot always bring it.
#:
#: Calibrated by running whole seasons at several values.  Higher and money
#: rather than research becomes the binding constraint for the back of the
#: grid, which stops the sliding scale below from doing anything and leaves the
#: field frozen; lower and nobody is ever short of anything.  At this value a
#: season closes the front-to-back spread by eight or nine per cent, the
#: midfield develops about twice as fast as the leader, and the smallest teams
#: still finish the year close to broke.
COST_PER_POINT = 0.030

#: How long a project takes, in rounds, by size.  Anything can be rushed and
#: nothing can be rushed for free -- see :func:`commission`.
MINIMUM_ROUNDS = 1
MAXIMUM_ROUNDS = 6

#: How fragile a brand-new part is, as a multiplier on the team's failure
#: rates, and how many rounds it takes to shake that out.
NEW_PART_FRAGILITY = 0.55
FRAGILITY_ROUNDS = 3


class UpgradeStatus(str):
    """Kept as plain strings so a save file and an API response read alike."""

    IN_DEVELOPMENT = "in_development"
    FITTED = "fitted"
    FAILED = "failed"


@dataclass(slots=True)
class Upgrade:
    """A part, from commissioned to fitted."""

    id: str
    team_id: str
    area: str
    points: float
    """Research committed to it."""

    cost: float
    """Money committed to it, in millions."""

    arrives_at_round: int
    commissioned_at_round: int
    expected_gain: float
    """What it will add to the area if it works."""

    failure_chance: float
    status: str = UpgradeStatus.IN_DEVELOPMENT
    actual_gain: float = 0.0

    @property
    def in_development(self) -> bool:
        return self.status == UpgradeStatus.IN_DEVELOPMENT

    def fragility_at(self, round_number: int) -> float:
        """How much extra failure rate this part is still carrying.

        Zero once it has been raced for a few rounds, which is the whole reason
        an upgrade brought to a title decider is a question rather than a gift.
        """
        if self.status != UpgradeStatus.FITTED:
            return 0.0
        raced = round_number - self.arrives_at_round
        if raced < 0 or raced >= FRAGILITY_ROUNDS:
            return 0.0
        return NEW_PART_FRAGILITY * (1.0 - raced / FRAGILITY_ROUNDS)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "team": self.team_id,
            "area": self.area,
            "points": round(self.points, 4),
            "cost": round(self.cost, 4),
            "arrives_at_round": self.arrives_at_round,
            "commissioned_at_round": self.commissioned_at_round,
            "expected_gain": round(self.expected_gain, 6),
            "failure_chance": round(self.failure_chance, 4),
            "status": self.status,
            "actual_gain": round(self.actual_gain, 6),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Upgrade:
        return cls(
            id=str(data["id"]),
            team_id=str(data["team"]),
            area=str(data["area"]),
            points=float(data["points"]),
            cost=float(data.get("cost", 0.0)),
            arrives_at_round=int(data["arrives_at_round"]),
            commissioned_at_round=int(data.get("commissioned_at_round", 0)),
            expected_gain=float(data.get("expected_gain", 0.0)),
            failure_chance=float(data.get("failure_chance", 0.0)),
            status=str(data.get("status", UpgradeStatus.IN_DEVELOPMENT)),
            actual_gain=float(data.get("actual_gain", 0.0)),
        )


#: The sliding scale of development allowance, by championship position.
#:
#: A real regulation, and the sport's own answer to exactly the problem it
#: solves here: a big team earns more research from its factory and its head
#: count, which on its own compounds into a field that spreads apart rather
#: than closing.  So the team leading the championship is allowed the least
#: development and the team at the back the most.  Without it the concavity in
#: :func:`development_gain` is not enough on its own -- measured, the shipped
#: grid barely closes at all -- and with it the field converges over a season
#: while leaving the leader in front.
ALLOWANCE_BY_POSITION: tuple[float, ...] = (
    0.70, 0.75, 0.80, 0.85, 0.90, 0.95, 1.00, 1.05, 1.10, 1.15,
)


def development_allowance(position: int | None) -> float:
    """The share of a full allowance a team in this position may use."""
    if position is None or position < 1:
        return 1.0
    index = min(position, len(ALLOWANCE_BY_POSITION)) - 1
    return ALLOWANCE_BY_POSITION[index]


def research_earned(
    team: Team, rules: DevelopmentRules, *, position: int | None = None
) -> float:
    """What a round's work is worth to this team.

    Facilities and head count both raise it, and both cost money to have, which
    is the trade: a big team out-develops a small one and spends the difference
    keeping the lights on.  The championship position then applies the sliding
    scale above, which is what stops that advantage from compounding into a
    procession.
    """
    facility = 1.0 + rules.facility_multiplier_per_level * (
        team.facilities.average_level - 3
    )
    staff = 0.75 + 0.25 * (team.staff / 600.0)
    return (
        rules.rd_points_per_round_base
        * facility
        * staff
        * development_allowance(position)
    )


def development_gain(
    team: Team, area: str, points: float, rules: DevelopmentRules
) -> float:
    """How much ``points`` of research would add to ``area``.

    Concave in the points spent and concave in where the area already is: the
    closer a car is to the ceiling, the less another part moves it.  Both
    together are what keeps a field converging rather than diverging.
    """
    if area not in AREA_NAMES:
        raise UnknownEntity(f"unknown car area {area!r}")
    if points <= 0.0:
        return 0.0

    current = team.car.area(area)
    headroom = max(0.0, 1.0 - current)
    efficiency = team.development_rate(area, per_level=rules.facility_multiplier_per_level)

    # 100 points at a level-3 facility, on a car at 0.80, is worth about 0.012 --
    # a little over one per cent of the area, which is roughly a tenth of a
    # second and about what a real in-season upgrade is worth.
    scale = 0.0042
    return scale * efficiency * (points**rules.diminishing_returns_exponent) * headroom


def _failure_chance(team: Team, area: str) -> float:
    """How likely this project is to produce nothing.

    Falls with the facility in that area: building the factory buys reliability
    of development, not just speed of it.
    """
    facility = FACILITY_FOR_AREA.get(area)
    level = team.facilities.level(facility) if facility else 3
    return max(0.02, 0.28 - 0.05 * level)


def _duration(points: float, rushed: float) -> int:
    """How many rounds a project of this size takes.

    ``rushed`` between 0 and 1 shortens it, and the caller pays for that in
    money and in failure chance -- see :func:`commission`.
    """
    natural = MINIMUM_ROUNDS + int(points // 90)
    natural = min(MAXIMUM_ROUNDS, natural)
    return max(MINIMUM_ROUNDS, round(natural * (1.0 - 0.5 * rushed)))


def commission(
    team: Team,
    *,
    area: str,
    points: float,
    current_round: int,
    rules: DevelopmentRules,
    rushed: float = 0.0,
    upgrade_id: str,
    cap: float | None = None,
) -> Upgrade:
    """Start a project, taking the research and the money for it.

    Rushing is a real trade rather than a slider: half the time, half again the
    cost, and a materially worse chance of the part working.
    """
    if area not in AREA_NAMES:
        raise UnknownEntity(f"unknown car area {area!r}")
    if points <= 0.0:
        raise UnknownEntity("a project needs some research in it")
    if team.rd_points < points:
        raise InsufficientBudget(
            f"{team.name} has {team.rd_points:.0f} research points, not {points:.0f}"
        )

    rushed = min(1.0, max(0.0, rushed))
    cost = COST_PER_POINT * points * (1.0 + 0.5 * rushed)
    team.spend(cost, what=f"a {area} upgrade", cap=cap)
    team.rd_points -= points

    return Upgrade(
        id=upgrade_id,
        team_id=team.id,
        area=area,
        points=points,
        cost=cost,
        arrives_at_round=current_round + _duration(points, rushed),
        commissioned_at_round=current_round,
        expected_gain=development_gain(team, area, points, rules),
        failure_chance=min(0.75, _failure_chance(team, area) * (1.0 + 0.9 * rushed)),
    )


def resolve(upgrade: Upgrade, team: Team, stream: RandomStream) -> Upgrade:
    """Fit a finished part, or find out it did not work.

    A failed project is not a refund.  The research and the money are spent
    either way, which is what makes commissioning one a decision.
    """
    if not upgrade.in_development:
        return upgrade
    if stream.random() < upgrade.failure_chance:
        upgrade.status = UpgradeStatus.FAILED
        upgrade.actual_gain = 0.0
        return upgrade

    # A part that works lands somewhere around what was expected.  The spread
    # is what makes two identical projects worth watching.
    delivered = upgrade.expected_gain * stream.uniform(0.7, 1.25)
    team.car.improve(upgrade.area, delivered)
    upgrade.status = UpgradeStatus.FITTED
    upgrade.actual_gain = delivered
    return upgrade
