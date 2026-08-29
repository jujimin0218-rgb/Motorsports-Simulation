"""The game the server is holding.

One process, one game in memory, a SQLite file behind it.  That is deliberately
the whole architecture: the thing being built is a single-player season, and a
session store, a broker and a worker fleet would be infrastructure with nothing
to do.  The seams where that would change -- the save store and the job runner
-- are both injected, so replacing either is a constructor argument rather than
a rewrite.

Everything a player can do goes through here, and everything that changes the
game asks the round machine whether this is the moment for it first.
"""

from __future__ import annotations

import threading
from typing import Any, Callable

from ..adapters import session_runner
from ..game.calendar import RoundPhase
from ..game.errors import GameError, InvalidGamePhase, SaveNotFound, UnknownEntity
from ..game.newgame import available_teams, new_game
from ..game.state import GameState
from . import round_service
from .jobs import Job, JobRunner
from .storage import AUTOSAVE_SLOT, SaveStore, SaveSummary

__all__ = ["GameService"]


class GameService:
    """The API's view of the game."""

    def __init__(
        self,
        *,
        store: SaveStore | None = None,
        jobs: JobRunner | None = None,
        autosave: bool = True,
    ) -> None:
        self._store = store if store is not None else SaveStore("saves.db")
        self._jobs = jobs if jobs is not None else JobRunner()
        self._state: GameState | None = None
        self._save_id: str | None = None
        self._autosave = autosave
        self._lock = threading.RLock()

    # -- what is loaded ------------------------------------------------------

    @property
    def jobs(self) -> JobRunner:
        return self._jobs

    @property
    def store(self) -> SaveStore:
        return self._store

    @property
    def has_game(self) -> bool:
        return self._state is not None

    @property
    def state(self) -> GameState:
        if self._state is None:
            raise SaveNotFound("no game is loaded; start a new one or load a save")
        return self._state

    def close(self) -> None:
        self._jobs.shutdown()
        self._store.close()

    # -- starting, saving, loading -------------------------------------------

    def teams_available(self) -> list[dict[str, Any]]:
        return available_teams()

    def start(
        self,
        *,
        player_team: str,
        seed: int | None = None,
        season: int | None = None,
        name: str = "",
    ) -> GameState:
        with self._lock:
            self._state = new_game(
                player_team=player_team, seed=seed, season=season, name=name
            )
            self._save_id = None
            self._touch()
            return self._state

    def save(
        self, *, save_id: str | None = None, slot: str | None = None, name: str | None = None
    ) -> SaveSummary:
        with self._lock:
            state = self.state
            if name:
                state.name = name
            summary = self._store.save(
                state, save_id=save_id or (self._save_id if slot is None else None), slot=slot
            )
            if slot is None:
                self._save_id = summary.id
            return summary

    def load(self, *, save_id: str | None = None, slot: str | None = None) -> GameState:
        with self._lock:
            if save_id is not None:
                self._state = self._store.load(save_id)
                self._save_id = save_id
            elif slot is not None:
                self._state = self._store.load_slot(slot)
                self._save_id = None
            else:
                raise SaveNotFound("pass a save id or a slot")
            return self._state

    def saves(self) -> list[SaveSummary]:
        return self._store.list()

    def delete_save(self, save_id: str) -> None:
        with self._lock:
            self._store.delete(save_id)
            if self._save_id == save_id:
                self._save_id = None

    def _touch(self) -> None:
        """Autosave, quietly.

        Called after every step of a weekend, because losing a race that took
        ten minutes to a closed tab is not an experience worth shipping.
        """
        if self._autosave and self._state is not None:
            self._store.autosave(self._state)

    # -- reading the game ----------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        """Everything a dashboard needs, in one call."""
        state = self.state
        standings = state.standings()
        current = state.current_round
        player = state.player
        return {
            "name": state.name,
            "season": state.season,
            "seed": state.seed,
            "settings": state.settings.to_dict(),
            "player_team": state.player_team,
            "season_complete": state.season_complete,
            "current_round": None
            if current is None
            else {
                **current.to_dict(),
                "circuit": state.circuit_for(current.number).to_dict(),
                "race_laps": state.laps_for(current.number),
            },
            "team": {
                **player.to_dict(),
                "engine": state.engine_for(player.id).to_dict(),
                "car_overall": round(player.car.overall, 4),
                "championship_position": standings.team_position(player.id),
            },
            "drivers": [
                {
                    **state.driver(d).to_dict(),
                    "championship_position": standings.driver_position(d),
                    "market_value": state.driver(d).market_value,
                }
                for d in player.drivers
            ],
            "standings": standings.to_dict(),
        }

    def teams(self) -> list[dict[str, Any]]:
        state = self.state
        standings = state.standings()
        return [
            {
                **team.to_dict(),
                "engine_name": state.engine_for(team.id).name,
                "car_overall": round(team.car.overall, 4),
                "championship_position": standings.team_position(team.id),
                "driver_names": [state.driver(d).name for d in team.drivers],
            }
            for team in state.teams.values()
        ]

    def drivers(self, *, free_agents_only: bool = False) -> list[dict[str, Any]]:
        state = self.state
        pool = state.free_agents if free_agents_only else list(state.drivers.values())
        return [
            {**profile.to_dict(), "market_value": profile.market_value, "overall": round(profile.overall, 4)}
            for profile in sorted(pool, key=lambda p: -p.overall)
        ]

    def calendar(self) -> list[dict[str, Any]]:
        state = self.state
        return [
            {
                **entry.to_dict(),
                "circuit": state.calendar.circuit(entry.circuit_id).to_dict(),
                "race_laps": state.laps_for(entry.number),
            }
            for entry in state.calendar
        ]

    def race(self, race_id: str) -> dict[str, Any]:
        """The engine's own result, kept whole -- what a replay plays back."""
        archive = self.state.race_archive.get(race_id)
        if archive is None:
            raise UnknownEntity(f"no race archived as {race_id!r}")
        return archive

    def history(self) -> list[dict[str, Any]]:
        return [record.to_dict() for record in self.state.history]

    # -- running a weekend ---------------------------------------------------

    def start_round(self) -> dict[str, Any]:
        with self._lock:
            report = round_service.start_round(self.state)
            self._touch()
            return report.to_dict()

    def run_practice(self) -> dict[str, Any]:
        with self._lock:
            report = round_service.run_practice(self.state)
            self._touch()
            return report.to_dict()

    def run_qualifying_job(self) -> Job:
        """Start qualifying.

        A job because it is about two and a half minutes of simulation: three
        segments, every car running real out-laps and real flying laps on a
        track that rubbers in as it goes.
        """
        state = self.state
        entry = state.current_round
        if entry is None:
            raise InvalidGamePhase("the season is over")
        entry.require(RoundPhase.QUALIFYING)

        def work(job: Job) -> dict[str, Any]:
            with self._lock:
                job.detail = "running qualifying"
                report = round_service.run_qualifying(state)
                self._touch()
                return report.to_dict()

        return self._jobs.submit("qualifying", work, detail="qualifying")

    def run_race_job(self) -> Job:
        """Start the grand prix, reporting laps as it goes."""
        state = self.state
        entry = state.current_round
        if entry is None:
            raise InvalidGamePhase("the season is over")
        entry.require(RoundPhase.STRATEGY)
        total = max(1, state.laps_for(entry.number))
        seen: dict[int, int] = {}

        def on_lap(race_entry: Any, lap_result: Any) -> None:
            done = seen.get(race_entry.car_number, 0) + 1
            seen[race_entry.car_number] = done
            job.progress = min(0.99, min(seen.values()) / total)

        def work(current: Job) -> dict[str, Any]:
            with self._lock:
                current.detail = f"racing {total} laps"
                report = round_service.run_race(state, on_lap=on_lap)
                self._touch()
                return report.to_dict()

        job = self._jobs.submit("race", work, detail="grand prix")
        return job

    def run_development(self) -> dict[str, Any]:
        with self._lock:
            report = round_service.run_development(self.state)
            self._touch()
            return report.to_dict()

    def next_round(self) -> dict[str, Any]:
        return round_service.advance_to_next_round(self.state).to_dict()
