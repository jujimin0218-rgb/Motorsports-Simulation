"""The whole game, in one object.

Everything the player has done lives here and nowhere else, which is what makes
a save a save.  Two rules keep it honest:

**Derived things are not stored.**  The championship tables are computed from
the list of race outcomes every time they are asked for, so they can never
disagree with the races that produced them.  The same goes for a team's
position and a driver's.  What *is* stored is what cannot be recomputed: the
results themselves, the money, the contracts, the state of the cars.

**The seed is part of the state.**  Reload a save and re-run a round and the
same race happens, because the randomness is addressed by season and round
rather than drawn in call order (see :mod:`app.game.rng`).  That is what makes
"try it again with a different strategy" a real comparison instead of two
different afternoons.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Iterable

from .calendar import Calendar, Circuit, Round, RoundPhase
from .car import EngineSupplier
from .development import Upgrade
from .errors import UnknownEntity
from .finance import SponsorDeal
from .people import DriverProfile
from .rng import GameRng
from .rules import Rules
from .settings import GameSettings
from .standings import RaceOutcome, Standings
from .team import Team

__all__ = ["GameState", "SeasonRecord", "SAVE_VERSION"]

#: Bumped when the save format changes shape.  A loader that sees a version it
#: does not know refuses rather than guessing.
SAVE_VERSION = 1


@dataclass(frozen=True, slots=True)
class SeasonRecord:
    """One finished season, kept for the history book."""

    season: int
    driver_champion: str = ""
    constructor_champion: str = ""
    player_team: str = ""
    player_team_position: int = 0
    standings: dict[str, Any] = field(default_factory=dict)
    race_winners: tuple[str, ...] = ()
    pole_sitters: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "season": self.season,
            "driver_champion": self.driver_champion,
            "constructor_champion": self.constructor_champion,
            "player_team": self.player_team,
            "player_team_position": self.player_team_position,
            "standings": self.standings,
            "race_winners": list(self.race_winners),
            "pole_sitters": list(self.pole_sitters),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SeasonRecord:
        return cls(
            season=int(data["season"]),
            driver_champion=str(data.get("driver_champion", "")),
            constructor_champion=str(data.get("constructor_champion", "")),
            player_team=str(data.get("player_team", "")),
            player_team_position=int(data.get("player_team_position", 0)),
            standings=dict(data.get("standings", {})),
            race_winners=tuple(data.get("race_winners", ())),
            pole_sitters=tuple(data.get("pole_sitters", ())),
        )


@dataclass(slots=True)
class GameState:
    """A saved game."""

    seed: int
    season: int
    player_team: str
    calendar: Calendar
    rules: Rules = field(default_factory=Rules)
    settings: GameSettings = field(default_factory=GameSettings)
    teams: dict[str, Team] = field(default_factory=dict)
    drivers: dict[str, DriverProfile] = field(default_factory=dict)
    engines: dict[str, EngineSupplier] = field(default_factory=dict)
    outcomes: list[RaceOutcome] = field(default_factory=list)
    """Every car's every race this season.  The championship is this, sorted."""

    race_archive: dict[str, dict[str, Any]] = field(default_factory=dict)
    """The race engine's own results, kept whole, keyed by race id.

    Not used by the championship -- that only needs the outcomes above.  This
    is what a replay is played back from, and it is deliberately the engine's
    output rather than a summary of it."""

    upgrades: list[Upgrade] = field(default_factory=list)
    """Every project any team has commissioned this season, finished or not."""

    sponsor_deals: list[SponsorDeal] = field(default_factory=list)

    history: list[SeasonRecord] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    name: str = "New Game"

    # -- who and where -------------------------------------------------------

    def team(self, team_id: str) -> Team:
        try:
            return self.teams[team_id]
        except KeyError as error:
            raise UnknownEntity(f"unknown team {team_id!r}") from error

    def driver(self, driver_id: str) -> DriverProfile:
        try:
            return self.drivers[driver_id]
        except KeyError as error:
            raise UnknownEntity(f"unknown driver {driver_id!r}") from error

    def engine(self, engine_id: str) -> EngineSupplier:
        try:
            return self.engines[engine_id]
        except KeyError as error:
            raise UnknownEntity(f"unknown engine {engine_id!r}") from error

    @property
    def player(self) -> Team:
        return self.team(self.player_team)

    def engine_for(self, team_id: str) -> EngineSupplier:
        return self.engine(self.team(team_id).engine)

    def team_of(self, driver_id: str) -> str | None:
        return self.driver(driver_id).team

    def drivers_of(self, team_id: str) -> list[DriverProfile]:
        return [self.driver(d) for d in self.team(team_id).drivers]

    @property
    def free_agents(self) -> list[DriverProfile]:
        return [d for d in self.drivers.values() if d.is_free_agent]

    # -- what a team has going on --------------------------------------------

    def upgrades_for(self, team_id: str) -> list[Upgrade]:
        return [u for u in self.upgrades if u.team_id == team_id]

    def upgrades_in_development(self, team_id: str) -> list[Upgrade]:
        return [u for u in self.upgrades_for(team_id) if u.in_development]

    def upgrades_arriving(self, round_number: int) -> list[Upgrade]:
        """Projects due to be fitted at this round, whoever owns them."""
        return [
            u
            for u in self.upgrades
            if u.in_development and u.arrives_at_round <= round_number
        ]

    def sponsor_deals_for(self, team_id: str) -> list[SponsorDeal]:
        return [d for d in self.sponsor_deals if d.team_id == team_id]

    def fragility_for(self, team_id: str, round_number: int) -> float:
        """How much extra failure rate this team's new parts are carrying.

        A car running three fresh upgrades is a car with three things on it
        nobody has raced, and the engine charges that as a hazard rate rather
        than as a chance of a DNF.
        """
        return sum(
            upgrade.fragility_at(round_number)
            for upgrade in self.upgrades_for(team_id)
        )

    # -- where the season has got to -----------------------------------------

    @property
    def current_round(self) -> Round | None:
        """The round the season is waiting on, or ``None`` once it is over."""
        return self.calendar.next_incomplete

    @property
    def current_round_number(self) -> int:
        current = self.current_round
        return current.number if current is not None else len(self.calendar) + 1

    @property
    def season_complete(self) -> bool:
        return self.current_round is None

    def round(self, number: int) -> Round:
        return self.calendar.round(number)

    def laps_for(self, number: int) -> int:
        """How long this round's race actually is.

        The calendar holds the full grand prix distance; the settings decide
        what fraction of it this game is run over."""
        return self.settings.laps_for(self.round(number).laps)

    def circuit_for(self, number: int) -> Circuit:
        return self.calendar.circuit_for(number)

    def require_phase(self, number: int, *phases: RoundPhase) -> Round:
        """Fetch a round, refusing unless it is where the caller needs it.

        Every service that changes the game goes through here.  A client that
        posts to the race endpoint without having qualified gets a 409, not a
        race."""
        entry = self.round(number)
        entry.require(*phases)
        return entry

    # -- randomness ----------------------------------------------------------

    @property
    def rng(self) -> GameRng:
        """The root of this game's randomness, rebuilt from the seed.

        A property rather than a field: it holds no state worth saving, and
        rebuilding it means a loaded save is in exactly the position the
        original was.
        """
        return GameRng(self.seed)

    def round_rng(self, number: int) -> GameRng:
        return self.rng.season(self.season).round(number)

    # -- the championship ----------------------------------------------------

    def standings(self) -> Standings:
        """Both tables, computed now."""
        return Standings.compute(
            self.outcomes,
            self.rules,
            driver_ids=[d for d in self.drivers if not self.drivers[d].retired],
            team_ids=list(self.teams),
        )

    def outcomes_for_round(self, number: int) -> list[RaceOutcome]:
        return [o for o in self.outcomes if o.round_number == number]

    def record_outcomes(self, outcomes: Iterable[RaceOutcome]) -> None:
        """File a round's results, replacing anything already filed for it.

        Replacing rather than appending is what makes a round re-runnable: a
        replayed race overwrites its own result instead of scoring twice.
        """
        incoming = list(outcomes)
        if not incoming:
            return
        numbers = {o.round_number for o in incoming}
        self.outcomes = [o for o in self.outcomes if o.round_number not in numbers]
        self.outcomes.extend(incoming)
        self.outcomes.sort(key=lambda o: (o.round_number, o.position))

    # -- persistence ---------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": SAVE_VERSION,
            "name": self.name,
            "seed": self.seed,
            "season": self.season,
            "player_team": self.player_team,
            "created_at": self.created_at,
            "rules": self.rules.to_dict(),
            "settings": self.settings.to_dict(),
            "calendar": self.calendar.to_dict(),
            "teams": {tid: team.to_dict() for tid, team in self.teams.items()},
            "drivers": {did: d.to_dict() for did, d in self.drivers.items()},
            "engines": {eid: e.to_dict() for eid, e in self.engines.items()},
            "outcomes": [o.to_dict() for o in self.outcomes],
            "race_archive": self.race_archive,
            "upgrades": [u.to_dict() for u in self.upgrades],
            "sponsor_deals": [d.to_dict() for d in self.sponsor_deals],
            "history": [record.to_dict() for record in self.history],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GameState:
        version = int(data.get("version", 0))
        if version != SAVE_VERSION:
            raise UnknownEntity(
                f"save format version {version} cannot be read by this build "
                f"(expected {SAVE_VERSION})"
            )
        return cls(
            seed=int(data["seed"]),
            season=int(data["season"]),
            player_team=str(data["player_team"]),
            calendar=Calendar.from_dict(data["calendar"]),
            rules=Rules.from_dict(data.get("rules", {})),
            settings=GameSettings.from_dict(data.get("settings", {})),
            teams={
                tid: Team.from_dict(entry)
                for tid, entry in data.get("teams", {}).items()
            },
            drivers={
                did: DriverProfile.from_dict(entry)
                for did, entry in data.get("drivers", {}).items()
            },
            engines={
                eid: EngineSupplier.from_dict(entry)
                for eid, entry in data.get("engines", {}).items()
            },
            outcomes=[RaceOutcome.from_dict(o) for o in data.get("outcomes", [])],
            race_archive=dict(data.get("race_archive", {})),
            upgrades=[Upgrade.from_dict(u) for u in data.get("upgrades", [])],
            sponsor_deals=[
                SponsorDeal.from_dict(d) for d in data.get("sponsor_deals", [])
            ],
            history=[SeasonRecord.from_dict(h) for h in data.get("history", [])],
            created_at=float(data.get("created_at", time.time())),
            name=str(data.get("name", "New Game")),
        )
