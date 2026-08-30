"""The end of a season, and the start of the next one.

Until now the game stopped at round twenty-two.  This is what happens instead,
and the design question it answers is the one every management game gets wrong
in one of two directions: carry everything over and the third season is decided
before it starts, or reset everything and none of the first two mattered.

What carries over, and what does not:

**Money carries.**  A good season pays for next year's car, which is the whole
reason a season is worth winning beyond the trophy.

**Reputation carries, slowly.**  It moves toward where the team finished rather
than to it, so one good year does not make a big team and one bad year does not
unmake one.  It is the resource that takes seasons to build, which is what makes
it worth building.

**Facilities carry.**  A factory is the slowest advantage in the game and the
one that lasts.

**Car performance does not.**  Every winter is a new car, and the new one is
built from where the old one got to rather than being it.  Without this the
ratings inflate: a full season of development adds two or three points to every
car on the grid, and after five seasons everybody is at 0.99 and the game has
no headroom left.  So the grid is **rebased** -- the spread is kept, the level
is brought back down -- which is also what a regulation change does in reality.

**Research does not carry.**  A part designed for last year's car is worth
nothing on this year's.

**Drivers age.**  A young one improves toward their potential, an old one falls
away from it, and one who has fallen far enough retires -- which is what keeps
the transfer market from being the same twenty names for a decade.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .car import AREA_NAMES
from .finance import season_settlement
from .penalties import PenaltyKind
from .state import SeasonRecord

if TYPE_CHECKING:  # pragma: no cover
    from .state import GameState

__all__ = ["SeasonSummary", "close_season", "start_next_season"]

#: Where a season of development is pulled back to.
#:
#: This is the *design level of the grid* -- the mean the shipped teams start a
#: game at -- and it is that number rather than a lower one on purpose.  The
#: winter is meant to remove the inflation a season of development added, which
#: is two or three points, not to undo the grid.  Set it lower and every season
#: hands the whole field a worse car than it started with; leave it out
#: altogether and the grid runs out of headroom in five seasons and development
#: stops meaning anything.
#:
#: The *spread* the teams earned is kept, at slightly less than all of it, so a
#: season of getting it right still decides who starts next season in front.
REBASE_TO_LEVEL = 0.841
REBASE_KEEP_SPREAD = 0.85

#: How fast reputation follows results.  Slow on purpose: it is the resource
#: that takes seasons, which is what makes it worth having.
REPUTATION_RATE = 0.22

#: Age at which a driver starts losing more than they gain, and the age past
#: which they may stop altogether.
PEAK_AGE = 29
RETIREMENT_AGE = 34

#: How much of the gap to their potential a young driver closes in a season,
#: and how much an old one loses.  Both small: a driver who gains half a season
#: of ability every winter is not a driver, they are a slider.
GROWTH_RATE = 0.16
DECLINE_RATE = 0.05


@dataclass(frozen=True, slots=True)
class SeasonSummary:
    """What the year came to."""

    season: int
    driver_champion: str
    constructor_champion: str
    player_position: int
    settlements: dict[str, Any]
    retirements: tuple[str, ...]
    record: SeasonRecord

    def to_dict(self) -> dict[str, Any]:
        return {
            "season": self.season,
            "driver_champion": self.driver_champion,
            "constructor_champion": self.constructor_champion,
            "player_position": self.player_position,
            "settlements": self.settlements,
            "retirements": list(self.retirements),
            "record": self.record.to_dict(),
        }


def close_season(state: GameState) -> SeasonSummary:
    """Settle the year and write it into the history book.

    Only the money and the record.  The winter -- ageing, rebasing, the new
    calendar -- is :func:`start_next_season`, so a player can look at a
    finished season before committing to the next one.
    """
    standings = state.standings()

    settlements: dict[str, Any] = {}
    for team in state.teams.values():
        ledger = season_settlement(state, team.id, standings, state.rules)
        team.budget += ledger.total
        settlements[team.id] = ledger.to_dict()

    winners: list[str] = []
    poles: list[str] = []
    for number in range(1, len(state.calendar) + 1):
        outcomes = state.outcomes_for_round(number)
        winner = next((o for o in outcomes if o.position == 1 and not o.retired), None)
        if winner is not None:
            winners.append(winner.driver_id)
        pole = next((o for o in outcomes if o.pole), None)
        if pole is not None:
            poles.append(pole.driver_id)

    player_position = standings.team_position(state.player_team) or 0
    record = SeasonRecord(
        season=state.season,
        driver_champion=standings.driver_champion or "",
        constructor_champion=standings.constructor_champion or "",
        player_team=state.player_team,
        player_team_position=player_position,
        standings=standings.to_dict(),
        race_winners=tuple(winners),
        pole_sitters=tuple(poles),
    )
    state.history.append(record)

    return SeasonSummary(
        season=state.season,
        driver_champion=record.driver_champion,
        constructor_champion=record.constructor_champion,
        player_position=player_position,
        settlements=settlements,
        retirements=(),
        record=record,
    )


def start_next_season(state: GameState) -> dict[str, Any]:
    """The winter.

    Everything that changes between one season and the next, in the order it
    has to happen: the standings are read before they are cleared, the cars are
    rebased before the research is thrown away, and the drivers age before the
    market opens on them.
    """
    from .calendar import Calendar

    standings = state.standings()
    finished_season = state.season

    reputations = _settle_reputation(state, standings)
    rebased = _rebase_cars(state)
    aged, retired = _age_drivers(state)
    contracts = _advance_contracts(state)

    # Prize money next year is paid on where everybody finished this year.
    for team in state.teams.values():
        team.prize_position = standings.team_position(team.id) or team.prize_position
        team.season_spending = 0.0
        team.rd_points = 0.0

    # The season itself.
    state.season = finished_season + 1
    state.calendar = Calendar.load(season=state.season)
    state.outcomes = []
    state.upgrades = []
    state.penalties = []
    state.engines_used = {}
    state.race_archive = {}
    state.replays = {}

    for deal in list(state.sponsor_deals):
        deal.seasons_remaining -= 1
    state.sponsor_deals = [d for d in state.sponsor_deals if d.seasons_remaining > 0]

    return {
        "season": state.season,
        "rebased": rebased,
        "reputations": reputations,
        "drivers_aged": aged,
        "retired": retired,
        "contracts_expired": contracts,
        "rounds": len(state.calendar),
    }


def _settle_reputation(state: GameState, standings: Any) -> dict[str, float]:
    """Move each team's standing toward where it finished.

    Toward, not to.  A team that wins once is not suddenly a great team and a
    team that has one bad year is not suddenly nobody, and the fact that it
    takes seasons is what makes reputation worth spending seasons on.
    """
    teams = max(1, len(state.teams))
    moved: dict[str, float] = {}
    for team in state.teams.values():
        position = standings.team_position(team.id) or teams
        deserved = 1.0 - (position - 1) / max(1, teams - 1)
        team.reputation += REPUTATION_RATE * (deserved - team.reputation)
        team.reputation = min(0.99, max(0.05, team.reputation))
        moved[team.id] = round(team.reputation, 4)
    return moved


def _rebase_cars(state: GameState) -> dict[str, float]:
    """Design next year's car from where this year's got to.

    The spread the teams earned is kept and the level is brought back down, so
    a season of development still decides who starts next season in front
    without the grid running out of headroom by 2031.
    """
    levels = [team.car.overall for team in state.teams.values()]
    mean = sum(levels) / max(1, len(levels))
    rebased: dict[str, float] = {}
    for team in state.teams.values():
        for area in AREA_NAMES:
            current = team.car.area(area)
            team.car.set_area(
                area, REBASE_TO_LEVEL + REBASE_KEEP_SPREAD * (current - mean)
            )
        rebased[team.id] = round(team.car.overall, 4)
    return rebased


def _age_drivers(state: GameState) -> tuple[dict[str, float], list[str]]:
    """A year older, and better or worse for it."""
    from .people import SKILL_NAMES

    aged: dict[str, float] = {}
    retired: list[str] = []
    for profile in state.drivers.values():
        if profile.retired:
            continue
        profile.age += 1
        profile.experience = min(0.99, (profile.age - 18) / 18.0)
        profile.form = 0.0

        if profile.age <= PEAK_AGE:
            for name in SKILL_NAMES:
                gap = profile.potential - profile.skill(name)
                if gap > 0:
                    profile.skills[name] = min(
                        0.99, profile.skill(name) + GROWTH_RATE * gap
                    )
        else:
            years = profile.age - PEAK_AGE
            for name in SKILL_NAMES:
                profile.skills[name] = max(
                    0.30, profile.skill(name) - DECLINE_RATE * years * 0.5
                )
        aged[profile.id] = round(profile.overall, 4)

        # A driver who has fallen far enough, and is old enough, stops.  Which
        # is what keeps the market from being the same twenty names for a
        # decade.
        if profile.age >= RETIREMENT_AGE and profile.overall < 0.72:
            profile.retired = True
            if profile.team:
                team = state.team(profile.team)
                if profile.id in team.drivers:
                    team.drivers.remove(profile.id)
            profile.team = None
            profile.contract = None
            retired.append(profile.id)
    return aged, retired


def _advance_contracts(state: GameState) -> list[str]:
    """Count a season off every contract, and free anybody whose ran out."""
    expired: list[str] = []
    for profile in state.drivers.values():
        if profile.contract is None or profile.retired:
            continue
        profile.contract.advance_season()
        if profile.contract.seasons_remaining <= 0:
            if profile.team:
                team = state.team(profile.team)
                if profile.id in team.drivers:
                    team.drivers.remove(profile.id)
            profile.team = None
            profile.contract = None
            expired.append(profile.id)
    return expired
