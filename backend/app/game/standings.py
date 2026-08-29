"""The championship, computed rather than accumulated.

Both tables are derived from the list of results the season has produced so
far, every time they are asked for.  That costs a few microseconds and buys
something worth much more: there is no running total anywhere that can drift
out of step with the races that produced it.  Delete a result and the table is
correct; replay a round and the table is correct.

What a position is worth is not decided here -- it comes from
:class:`~app.game.rules.PointsRules`, which comes from ``rules.json``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from .rules import Rules

__all__ = ["DriverStanding", "RaceOutcome", "Standings", "TeamStanding"]


@dataclass(frozen=True, slots=True)
class RaceOutcome:
    """One car's race, reduced to what a championship needs to know.

    The race engine's own :class:`RaceResult` is far richer than this and is
    kept whole for the replay; this is the projection of it that the standings
    are built from.
    """

    round_number: int
    driver_id: str
    team_id: str
    position: int
    """Classified finishing position, 1-based.  A retirement still has one."""

    started: int = 0
    laps_completed: int = 0
    retired: bool = False
    fastest_lap: bool = False
    pole: bool = False

    @property
    def is_win(self) -> bool:
        return self.position == 1 and not self.retired

    @property
    def is_podium(self) -> bool:
        return self.position <= 3 and not self.retired

    def points(self, rules: Rules) -> int:
        """What this drive scored.

        A retirement scores nothing however it is classified, and the fastest
        lap only pays inside the positions the rules say it pays in.
        """
        if self.retired:
            return 0
        total = rules.points.for_position(self.position)
        if self.fastest_lap:
            total += rules.points.fastest_lap_points(self.position)
        return total

    def to_dict(self) -> dict[str, Any]:
        return {
            "round": self.round_number,
            "driver": self.driver_id,
            "team": self.team_id,
            "position": self.position,
            "started": self.started,
            "laps_completed": self.laps_completed,
            "retired": self.retired,
            "fastest_lap": self.fastest_lap,
            "pole": self.pole,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RaceOutcome:
        return cls(
            round_number=int(data["round"]),
            driver_id=str(data["driver"]),
            team_id=str(data["team"]),
            position=int(data["position"]),
            started=int(data.get("started", 0)),
            laps_completed=int(data.get("laps_completed", 0)),
            retired=bool(data.get("retired", False)),
            fastest_lap=bool(data.get("fastest_lap", False)),
            pole=bool(data.get("pole", False)),
        )


@dataclass(slots=True)
class _Tally:
    """The counting shared by both tables."""

    points: int = 0
    wins: int = 0
    podiums: int = 0
    poles: int = 0
    fastest_laps: int = 0
    dnfs: int = 0
    starts: int = 0
    best_finish: int = 0

    def add(self, outcome: RaceOutcome, rules: Rules) -> None:
        self.starts += 1
        self.points += outcome.points(rules)
        if outcome.retired:
            self.dnfs += 1
        else:
            if outcome.is_win:
                self.wins += 1
            if outcome.is_podium:
                self.podiums += 1
            if self.best_finish == 0 or outcome.position < self.best_finish:
                self.best_finish = outcome.position
        if outcome.pole:
            self.poles += 1
        if outcome.fastest_lap:
            self.fastest_laps += 1

    def as_dict(self) -> dict[str, int]:
        return {
            "points": self.points,
            "wins": self.wins,
            "podiums": self.podiums,
            "poles": self.poles,
            "fastest_laps": self.fastest_laps,
            "dnfs": self.dnfs,
            "starts": self.starts,
            "best_finish": self.best_finish,
        }


def _ordering_key(tally: _Tally) -> tuple:
    """Points, then wins, then podiums, then best finish.

    Countback rather than alphabetical: two drivers level on points are
    separated by who won more, which is how the sport does it and, more to the
    point, is a rule a player can see the reason for.
    """
    best = tally.best_finish if tally.best_finish else 99
    return (-tally.points, -tally.wins, -tally.podiums, best)


@dataclass(frozen=True, slots=True)
class DriverStanding:
    position: int
    driver_id: str
    team_id: str
    points: int
    wins: int
    podiums: int
    poles: int
    fastest_laps: int
    dnfs: int
    starts: int
    best_finish: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "position": self.position,
            "driver": self.driver_id,
            "team": self.team_id,
            "points": self.points,
            "wins": self.wins,
            "podiums": self.podiums,
            "poles": self.poles,
            "fastest_laps": self.fastest_laps,
            "dnfs": self.dnfs,
            "starts": self.starts,
            "best_finish": self.best_finish,
        }


@dataclass(frozen=True, slots=True)
class TeamStanding:
    position: int
    team_id: str
    points: int
    wins: int
    podiums: int
    poles: int
    fastest_laps: int
    dnfs: int
    starts: int
    best_finish: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "position": self.position,
            "team": self.team_id,
            "points": self.points,
            "wins": self.wins,
            "podiums": self.podiums,
            "poles": self.poles,
            "fastest_laps": self.fastest_laps,
            "dnfs": self.dnfs,
            "starts": self.starts,
            "best_finish": self.best_finish,
        }


@dataclass(frozen=True, slots=True)
class Standings:
    """Both championships, as of the results handed in."""

    drivers: tuple[DriverStanding, ...] = ()
    teams: tuple[TeamStanding, ...] = ()

    @classmethod
    def compute(
        cls,
        outcomes: Iterable[RaceOutcome],
        rules: Rules,
        *,
        driver_ids: Sequence[str] = (),
        team_ids: Sequence[str] = (),
    ) -> Standings:
        """Build both tables.

        ``driver_ids`` and ``team_ids`` seed the tables with everyone who is in
        the championship, so a driver who has not scored still appears -- at
        the bottom, with zero, which is where a player expects to find them
        rather than missing entirely.
        """
        driver_tallies: dict[str, _Tally] = {d: _Tally() for d in driver_ids}
        team_tallies: dict[str, _Tally] = {t: _Tally() for t in team_ids}
        driver_team: dict[str, str] = {}

        for outcome in outcomes:
            driver_tallies.setdefault(outcome.driver_id, _Tally()).add(outcome, rules)
            team_tallies.setdefault(outcome.team_id, _Tally()).add(outcome, rules)
            driver_team[outcome.driver_id] = outcome.team_id

        ordered_drivers = sorted(
            driver_tallies.items(), key=lambda item: (_ordering_key(item[1]), item[0])
        )
        ordered_teams = sorted(
            team_tallies.items(), key=lambda item: (_ordering_key(item[1]), item[0])
        )
        return cls(
            drivers=tuple(
                DriverStanding(
                    position=index,
                    driver_id=driver_id,
                    team_id=driver_team.get(driver_id, ""),
                    **tally.as_dict(),
                )
                for index, (driver_id, tally) in enumerate(ordered_drivers, start=1)
            ),
            teams=tuple(
                TeamStanding(position=index, team_id=team_id, **tally.as_dict())
                for index, (team_id, tally) in enumerate(ordered_teams, start=1)
            ),
        )

    # -- lookups -------------------------------------------------------------

    @property
    def driver_champion(self) -> str | None:
        return self.drivers[0].driver_id if self.drivers else None

    @property
    def constructor_champion(self) -> str | None:
        return self.teams[0].team_id if self.teams else None

    def driver_position(self, driver_id: str) -> int | None:
        for row in self.drivers:
            if row.driver_id == driver_id:
                return row.position
        return None

    def team_position(self, team_id: str) -> int | None:
        for row in self.teams:
            if row.team_id == team_id:
                return row.position
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "drivers": [row.to_dict() for row in self.drivers],
            "teams": [row.to_dict() for row in self.teams],
        }
