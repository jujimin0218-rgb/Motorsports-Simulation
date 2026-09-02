"""Signing drivers, and being turned down.

A negotiation here is not a price check.  A driver decides whether to take a
seat, and money is only one of the things they are deciding on: a quick car and
a team with a history are worth real salary to somebody who wants to win, and a
driver at the top of the market will refuse a backmarker at any price the
backmarker can pay.  That asymmetry is the whole transfer market -- without it
the richest team simply buys the best driver every year and the rest of the
grid is scenery.

What a driver weighs, and roughly how much of the decision each is:

* **the car**, most of it -- a driver wants to win, and they can see the times;
* **the money**, against what they believe they are worth;
* **the team's standing**, which is slow to move and is what a big team is
  still trading on years after it stopped winning;
* **their own standing**, which cuts both ways: a driver with nothing to lose
  will take a risk a champion will not.

The offer that gets accepted is therefore rarely the biggest one, and a small
team's route to a good driver is a quick car rather than a chequebook.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from f1_race_engine.core.rng import RandomStream

from .errors import ContractNotAvailable, InsufficientBudget, InvalidDriver
from .people import Contract, DriverProfile
from .team import Team

__all__ = [
    "NegotiationResult",
    "Offer",
    "evaluate",
    "market_asking_price",
    "sign",
]

#: How much of the decision each factor is.  They sum to one, and the car being
#: the largest is the point: a driver wants to win.
WEIGHT_CAR = 0.42
WEIGHT_MONEY = 0.31
WEIGHT_REPUTATION = 0.19
WEIGHT_LENGTH = 0.08

#: The score an offer has to reach.  Set so that a fair offer from a team of a
#: driver's own standing is usually accepted and a lowball is not.
ACCEPTANCE_THRESHOLD = 0.55

#: How much of the decision is left to chance.  Small: a driver who would take
#: the seat takes it, and one who would not cannot be talked round by a coin.
NOISE = 0.06

#: The floor, as a fraction of what the driver is asking.
#:
#: Below this an offer is refused outright, whatever the car and whatever the
#: team.  Money is not purely a weighted term, because in a real negotiation it
#: is not: there is a number below which nobody is having the conversation, and
#: without this a journeyman would take a midfield seat for a fifth of their
#: value simply because the car was good -- which would make the salary on
#: every offer outside the top of the grid meaningless.
MINIMUM_OFFER_FRACTION = 0.62


@dataclass(frozen=True, slots=True)
class Offer:
    """What a team is putting on the table.  Money in millions."""

    team_id: str
    driver_id: str
    salary: float
    seasons: int = 2
    signing_bonus: float = 0.0
    performance_bonus: float = 0.0

    @property
    def first_year_cost(self) -> float:
        return self.salary + self.signing_bonus

    def to_dict(self) -> dict[str, Any]:
        return {
            "team": self.team_id,
            "driver": self.driver_id,
            "salary": self.salary,
            "seasons": self.seasons,
            "signing_bonus": self.signing_bonus,
            "performance_bonus": self.performance_bonus,
        }


@dataclass(frozen=True, slots=True)
class NegotiationResult:
    """What the driver said, and enough of why for the player to try again."""

    accepted: bool
    score: float
    asking_price: float
    reason: str
    breakdown: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "score": round(self.score, 4),
            "asking_price": round(self.asking_price, 3),
            "reason": self.reason,
            "breakdown": {k: round(v, 4) for k, v in self.breakdown.items()},
        }


def market_asking_price(driver: DriverProfile, team: Team) -> float:
    """What this driver wants from this team, in millions a season.

    Not one number for the whole grid: a driver charges a slow team more, which
    is the mechanism that stops a backmarker from buying its way to the front
    cheaply and is also exactly what happens in reality.
    """
    base = driver.market_value
    # A car below the driver's own standing costs extra to put them in.
    shortfall = max(0.0, driver.overall - team.car.overall)
    return round(base * (1.0 + 2.2 * shortfall), 2)


def evaluate(
    offer: Offer,
    driver: DriverProfile,
    team: Team,
    *,
    stream: RandomStream | None = None,
) -> NegotiationResult:
    """Would this driver take this seat?"""
    if driver.retired:
        raise InvalidDriver(f"{driver.name} has retired")
    if offer.seasons < 1:
        raise ContractNotAvailable("a contract has to run for at least one season")

    asking = market_asking_price(driver, team)

    # The car, judged against what the driver thinks they are worth.  A driver
    # rated 0.95 looking at a 0.80 car scores this near zero however much money
    # is on the table.
    car = _normalise(team.car.overall - driver.overall + 0.12, span=0.30)

    # The money, against the asking price.  Overpaying helps, but with a
    # ceiling: nobody signs for a backmarker purely because it doubled the
    # offer.
    money = _normalise(offer.first_year_cost / max(asking, 0.1) - 0.85, span=0.55)

    # What the team is, which is slow to change and is what a big team trades
    # on for years after it stops winning.
    reputation = _normalise(team.reputation - 0.45 * driver.reputation, span=0.55)

    # Security.  A young driver wants a long deal; an established one wants to
    # stay free for the seat that might open up.
    wanted = 3 if driver.age < 26 else 2
    length = _normalise(1.0 - abs(offer.seasons - wanted) / 3.0, span=1.0)

    score = (
        WEIGHT_CAR * car
        + WEIGHT_MONEY * money
        + WEIGHT_REPUTATION * reputation
        + WEIGHT_LENGTH * length
    )
    if stream is not None:
        score += NOISE * (stream.random() - 0.5) * 2.0

    breakdown = {
        "car": car,
        "money": money,
        "reputation": reputation,
        "length": length,
    }
    insulting = offer.first_year_cost < MINIMUM_OFFER_FRACTION * asking
    accepted = score >= ACCEPTANCE_THRESHOLD and not insulting
    if insulting:
        # Say so plainly, rather than reporting whichever term happened to
        # score lowest -- the player needs to know it was the number.
        return NegotiationResult(
            accepted=False,
            score=score,
            asking_price=asking,
            reason=f"wants about {asking:.1f}M a season, not {offer.salary:.1f}M",
            breakdown=breakdown,
        )
    return NegotiationResult(
        accepted=accepted,
        score=score,
        asking_price=asking,
        reason=_reason(accepted, breakdown, offer, asking),
        breakdown=breakdown,
    )


def _normalise(value: float, *, span: float) -> float:
    """Squash a difference into 0..1 without a cliff at either end."""
    return min(1.0, max(0.0, 0.5 + value / (2.0 * span)))


def _reason(
    accepted: bool, breakdown: dict[str, float], offer: Offer, asking: float
) -> str:
    if accepted:
        return "signed"
    weakest = min(breakdown, key=breakdown.get)
    return {
        "car": "not convinced by the car",
        "money": f"wants about {asking:.1f}M a season, not {offer.salary:.1f}M",
        "reputation": "does not rate the team",
        "length": "unhappy with the length of the deal",
    }[weakest]


def sign(
    offer: Offer,
    driver: DriverProfile,
    team: Team,
    *,
    seat: int | None = None,
    release_clause: float | None = None,
) -> None:
    """Put a driver in a car.

    Takes the signing bonus now; the salary is charged round by round, which is
    what makes a big contract a running cost rather than a one-off.
    """
    if driver.team is not None and driver.team != team.id:
        raise ContractNotAvailable(
            f"{driver.name} is under contract to {driver.team}"
        )
    if not team.can_afford(offer.signing_bonus):
        raise InsufficientBudget(
            f"{team.name} cannot pay a {offer.signing_bonus:.1f}M signing bonus"
        )
    team.spend(offer.signing_bonus, what=f"signing {driver.name}")

    driver.team = team.id
    driver.contract = Contract(
        salary=offer.salary,
        seasons_remaining=offer.seasons,
        signing_bonus=offer.signing_bonus,
        performance_bonus=offer.performance_bonus,
        release_clause=(
            release_clause
            if release_clause is not None
            else round(offer.salary * 2.5, 2)
        ),
    )
    if driver.id not in team.drivers:
        if seat is not None and 0 <= seat < len(team.drivers):
            replaced = team.drivers[seat]
            team.drivers[seat] = driver.id
            if replaced != driver.id:
                driver.skills  # touch, so the intent is clear in a diff
        else:
            team.drivers.append(driver.id)
