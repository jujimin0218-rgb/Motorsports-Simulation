"""Starting a season.

Everything here comes out of the data files.  There is no team, driver, engine
or circuit written into the code, which is the point of project rule 30: a
different era, a licensed data set or somebody's fantasy grid is a directory of
JSON and no code at all.
"""

from __future__ import annotations

import json
import time
from typing import Any

from .calendar import Calendar
from .car import CarPerformance, EngineSupplier, Facilities
from .errors import UnknownEntity
from .paths import data_file
from .people import Contract, DriverProfile
from .rules import Rules
from .state import GameState
from .team import Team

__all__ = ["available_teams", "load_static_data", "new_game"]


def _read(*parts: str) -> dict[str, Any]:
    path = data_file(*parts)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:  # pragma: no cover - configuration
        raise UnknownEntity(f"missing data file {path}") from error


def load_static_data() -> tuple[
    dict[str, Team], dict[str, DriverProfile], dict[str, EngineSupplier]
]:
    """Read the teams, drivers and engines as they start a fresh season."""
    engines = {
        entry["id"]: EngineSupplier.from_dict(entry)
        for entry in _read("engines", "engines.json")["engines"]
    }

    teams: dict[str, Team] = {}
    for entry in _read("teams", "teams.json")["teams"]:
        team = Team(
            id=str(entry["id"]),
            name=str(entry["name"]),
            nationality=str(entry.get("nationality", "")),
            engine=str(entry.get("engine", "")),
            budget=float(entry.get("budget", 145.0)),
            reputation=float(entry.get("reputation", 0.6)),
            car=CarPerformance.from_dict(entry.get("car", {})),
            facilities=Facilities.from_dict(entry.get("facilities", {})),
            staff=int(entry.get("staff", 600)),
        )
        if team.engine and team.engine not in engines:
            raise UnknownEntity(
                f"team {team.id!r} runs engine {team.engine!r}, which is not "
                "in the engine data"
            )
        teams[team.id] = team

    drivers: dict[str, DriverProfile] = {}
    for entry in _read("drivers", "drivers.json")["drivers"]:
        contract = entry.get("contract")
        profile = DriverProfile(
            id=str(entry["id"]),
            name=str(entry["name"]),
            abbreviation=str(entry.get("abbreviation", "DRV")),
            nationality=str(entry.get("nationality", "")),
            age=int(entry.get("age", 25)),
            skills=dict(entry.get("skills", {})),
            potential=float(entry.get("potential", 0.85)),
            experience=float(entry.get("experience", 0.5)),
            reputation=float(entry.get("reputation", 0.5)),
            team=entry.get("team"),
            contract=None if contract is None else Contract.from_dict(contract),
        )
        if profile.team is not None and profile.team not in teams:
            raise UnknownEntity(
                f"driver {profile.id!r} is signed to {profile.team!r}, which "
                "is not in the team data"
            )
        drivers[profile.id] = profile

    # Seat the drivers.  Done from the drivers' side rather than the teams' so
    # that the two can never disagree about who drives what.
    for profile in drivers.values():
        if profile.team is not None:
            teams[profile.team].drivers.append(profile.id)
    for team in teams.values():
        team.drivers.sort(key=lambda d: -drivers[d].overall)

    return teams, drivers, engines


def available_teams() -> list[dict[str, Any]]:
    """The teams a new player may take over, best first.

    Offered with enough context to choose: taking the quickest car is the easy
    game and taking the smallest budget is the hard one, and the player should
    be able to see which is which before committing to a season.
    """
    teams, drivers, engines = load_static_data()
    rows = []
    for team in teams.values():
        rows.append(
            {
                "id": team.id,
                "name": team.name,
                "nationality": team.nationality,
                "engine": engines[team.engine].name if team.engine else "",
                "budget": team.budget,
                "reputation": team.reputation,
                "car_rating": round(team.car.overall, 3),
                "facility_average": round(team.facilities.average_level, 2),
                "drivers": [drivers[d].name for d in team.drivers],
            }
        )
    rows.sort(key=lambda row: -row["car_rating"])
    return rows


def new_game(
    *,
    player_team: str,
    seed: int | None = None,
    season: int | None = None,
    name: str = "",
) -> GameState:
    """Build a fresh season with the player in ``player_team``.

    ``seed`` decides everything the game will ever draw.  Left out, it is taken
    from the clock -- but it is then *stored*, so the game remains reproducible
    from the moment it starts rather than only from the moment it is saved.
    """
    teams, drivers, engines = load_static_data()
    if player_team not in teams:
        raise UnknownEntity(
            f"cannot start as {player_team!r}; "
            f"choose one of {', '.join(sorted(teams))}"
        )

    calendar = Calendar.load(season=season)
    rules = Rules.load()

    # A team's budget comes from its own data file, so the grid starts uneven
    # on purpose; the rules only supply the floor and the cap.
    state = GameState(
        seed=int(seed) if seed is not None else int(time.time() * 1000) & 0xFFFFFFFF,
        season=calendar.season,
        player_team=player_team,
        calendar=calendar,
        rules=rules,
        teams=teams,
        drivers=drivers,
        engines=engines,
        name=name or f"{teams[player_team].name} {calendar.season}",
    )
    return state
