"""What the player does between races.

Every operation here takes money, research or both, and every one of them can
be refused -- which is the point.  A management game where nothing can be
turned down is a settings screen.

The refusals are all real constraints rather than rules invented to say no:
there is no research banked, there is no money, the cost-cap allowance is
spent, the driver would not sign, the sponsor will not put its name on this
car.  Each one comes back with a code the client can branch on and enough
detail to try something else.
"""

from __future__ import annotations

from typing import Any

from ..game import development, finance
from ..game.car import AREA_NAMES, FACILITY_NAMES, MAX_FACILITY_LEVEL
from ..game.contracts import Offer, evaluate, sign
from ..game.development import Upgrade
from ..game.errors import ContractNotAvailable, InvalidDriver, UnknownEntity
from ..game.state import GameState

__all__ = [
    "FACILITY_COST",
    "available_sponsors",
    "commission_upgrade",
    "development_options",
    "finances",
    "negotiate",
    "sign_driver",
    "sign_sponsor",
    "upgrade_facility",
]

#: What a level costs, in millions, by the level being bought.  Steep on
#: purpose: a factory is the slowest and most expensive advantage in the game,
#: and it is the one that lasts.
FACILITY_COST: dict[int, float] = {2: 14.0, 3: 24.0, 4: 40.0, 5: 65.0}


# -- research ----------------------------------------------------------------


def development_options(state: GameState, team_id: str) -> dict[str, Any]:
    """What this team could develop, and what it would get for it.

    Shown per area at the team's actual banked research, so the player is
    choosing between real options rather than reading a table of rates.
    """
    team = state.team(team_id)
    rules = state.rules.development
    from ..game.ai import remaining_demand

    demand = remaining_demand(state, state.current_round_number)
    points = team.rd_points
    return {
        "rd_points": round(points, 1),
        "budget": round(team.budget, 2),
        "cap_headroom": round(team.cap_headroom(state.rules.budget.cap), 2),
        "cost_per_point": development.COST_PER_POINT,
        "areas": [
            {
                "area": area,
                "current": round(team.car.area(area), 4),
                "gain_at_current_points": round(
                    development.development_gain(team, area, points, rules), 5
                ),
                "remaining_demand": round(demand[area], 4),
                "efficiency": round(
                    team.development_rate(
                        area, per_level=rules.facility_multiplier_per_level
                    ),
                    3,
                ),
            }
            for area in AREA_NAMES
        ],
        "in_development": [
            u.to_dict() for u in state.upgrades_in_development(team_id)
        ],
    }


def commission_upgrade(
    state: GameState,
    team_id: str,
    *,
    area: str,
    points: float,
    rushed: float = 0.0,
) -> Upgrade:
    """Start a project."""
    team = state.team(team_id)
    current = state.current_round_number
    index = len(state.upgrades_for(team_id)) + 1
    upgrade = development.commission(
        team,
        area=area,
        points=points,
        current_round=current,
        rules=state.rules.development,
        rushed=rushed,
        upgrade_id=f"{state.season}-{current}-{team_id}-{index}",
        cap=state.rules.budget.cap,
    )
    state.upgrades.append(upgrade)
    return upgrade


def upgrade_facility(state: GameState, team_id: str, facility: str) -> dict[str, Any]:
    """Put up a building.

    The slowest advantage in the game and the one that lasts: it does not make
    the car quicker, it makes every future development in that area worth more.
    """
    if facility not in FACILITY_NAMES:
        raise UnknownEntity(f"unknown facility {facility!r}")
    team = state.team(team_id)
    level = team.facilities.level(facility)
    if level >= MAX_FACILITY_LEVEL:
        raise UnknownEntity(f"{facility} is already at the maximum level")

    cost = FACILITY_COST[level + 1]
    team.spend(cost, what=f"a {facility} upgrade", cap=state.rules.budget.cap)
    team.facilities.upgrade(facility)
    return {
        "facility": facility,
        "level": team.facilities.level(facility),
        "cost": cost,
        "budget": round(team.budget, 2),
    }


# -- drivers -----------------------------------------------------------------


def negotiate(
    state: GameState,
    team_id: str,
    driver_id: str,
    *,
    salary: float,
    seasons: int = 2,
    signing_bonus: float = 0.0,
    performance_bonus: float = 0.0,
) -> dict[str, Any]:
    """Ask, without committing.

    The answer includes what the driver is asking and which part of the offer
    is weakest, so a refusal is information rather than a closed door.
    """
    team = state.team(team_id)
    driver = state.driver(driver_id)
    offer = Offer(
        team_id=team_id,
        driver_id=driver_id,
        salary=salary,
        seasons=seasons,
        signing_bonus=signing_bonus,
        performance_bonus=performance_bonus,
    )
    stream = state.rng.season(state.season).stream(
        "negotiation", team=team_id, driver=driver_id
    )
    result = evaluate(offer, driver, team, stream=stream)
    return {**result.to_dict(), "offer": offer.to_dict()}


def sign_driver(
    state: GameState,
    team_id: str,
    driver_id: str,
    *,
    salary: float,
    seasons: int = 2,
    signing_bonus: float = 0.0,
    performance_bonus: float = 0.0,
    seat: int | None = None,
) -> dict[str, Any]:
    """Make the offer for real.

    The driver is asked once, with the same stream the preview used, so a
    negotiation that came back yes is a negotiation that signs.
    """
    team = state.team(team_id)
    driver = state.driver(driver_id)
    if driver.team is not None and driver.team != team_id:
        raise ContractNotAvailable(
            f"{driver.name} is under contract to "
            f"{state.team(driver.team).name}; buy the contract out first"
        )
    if driver.retired:
        raise InvalidDriver(f"{driver.name} has retired")

    offer = Offer(
        team_id=team_id,
        driver_id=driver_id,
        salary=salary,
        seasons=seasons,
        signing_bonus=signing_bonus,
        performance_bonus=performance_bonus,
    )
    stream = state.rng.season(state.season).stream(
        "negotiation", team=team_id, driver=driver_id
    )
    result = evaluate(offer, driver, team, stream=stream)
    if not result.accepted:
        raise ContractNotAvailable(
            f"{driver.name} turned it down: {result.reason}"
        )

    # Replacing somebody means letting them go first, or the team ends the day
    # with three drivers and two cars.
    if seat is not None and 0 <= seat < len(team.drivers):
        replaced = state.driver(team.drivers[seat])
        if replaced.id != driver.id:
            replaced.team = None
            replaced.contract = None
    elif len(team.drivers) >= state.rules.cars_per_team:
        raise ContractNotAvailable(
            f"{team.name} has no free seat; say which one to replace"
        )

    sign(offer, driver, team, seat=seat)
    return {
        "driver": driver.id,
        "team": team.id,
        "contract": driver.contract.to_dict() if driver.contract else None,
        "budget": round(team.budget, 2),
        "asking_price": result.asking_price,
    }


# -- sponsors ----------------------------------------------------------------


def available_sponsors(state: GameState, team_id: str) -> list[dict[str, Any]]:
    """Who would put their name on this car.

    Gated on reputation, which is the point: the big money will not go on a car
    nobody is watching, so reputation is worth building rather than being a
    number on a screen.
    """
    team = state.team(team_id)
    signed = {deal.sponsor_id for deal in state.sponsor_deals_for(team_id)}
    taken = {deal.sponsor_id for deal in state.sponsor_deals}
    rows = []
    for sponsor in finance.load_sponsors().values():
        rows.append(
            {
                **sponsor.to_dict(),
                "available": (
                    sponsor.available_to(team.reputation)
                    and sponsor.id not in taken
                ),
                "signed": sponsor.id in signed,
                "reputation_shortfall": round(
                    max(0.0, sponsor.reputation_required - team.reputation), 3
                ),
            }
        )
    rows.sort(key=lambda row: -row["base_payment"])
    return rows


def sign_sponsor(state: GameState, team_id: str, sponsor_id: str) -> dict[str, Any]:
    """Take a sponsor on, and the target that comes with it."""
    team = state.team(team_id)
    sponsors = finance.load_sponsors()
    sponsor = sponsors.get(sponsor_id)
    if sponsor is None:
        raise UnknownEntity(f"unknown sponsor {sponsor_id!r}")
    if any(deal.sponsor_id == sponsor_id for deal in state.sponsor_deals):
        raise ContractNotAvailable(f"{sponsor.name} is already on a car")
    if not sponsor.available_to(team.reputation):
        raise ContractNotAvailable(
            f"{sponsor.name} wants a team with a reputation of "
            f"{sponsor.reputation_required:.2f}; {team.name} is at "
            f"{team.reputation:.2f}"
        )

    state.sponsor_deals.append(
        finance.SponsorDeal(
            sponsor_id=sponsor_id,
            team_id=team_id,
            seasons_remaining=sponsor.seasons,
            signed_in_season=state.season,
        )
    )
    return {
        "sponsor": sponsor.to_dict(),
        "seasons": sponsor.seasons,
        "per_season": sponsor.base_payment,
    }


# -- money -------------------------------------------------------------------


def finances(state: GameState, team_id: str) -> dict[str, Any]:
    """Where this team's money is going, as lines rather than a number."""
    team = state.team(team_id)
    ledger = finance.round_costs(state, team_id, round_number=state.current_round_number)
    rounds_left = sum(1 for entry in state.calendar if not entry.is_complete)
    return {
        "budget": round(team.budget, 2),
        "season_spending": round(team.season_spending, 2),
        "cap": state.rules.budget.cap,
        "cap_headroom": round(team.cap_headroom(state.rules.budget.cap), 2),
        "bankruptcy_limit": state.rules.budget.bankruptcy_limit,
        "per_round": ledger.to_dict(),
        "projected_to_season_end": round(team.budget + ledger.total * rounds_left, 2),
        "rounds_remaining": rounds_left,
        "sponsors": [
            deal.to_dict() for deal in state.sponsor_deals_for(team_id)
        ],
    }
