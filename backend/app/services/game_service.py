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

import logging
import threading
from typing import Any

from ..adapters.live import build_live, build_live_qualifying, field_lap
from ..game.calendar import RoundPhase
from ..game.errors import InvalidGamePhase, SaveNotFound, UnknownEntity
from ..game.newgame import available_teams, new_game
from ..game.state import GameState
from . import management_service, round_service
from .jobs import Job, JobRunner
from .storage import SaveStore, SaveSummary

__all__ = ["GameService"]

_log = logging.getLogger(__name__)


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
        self._autosave_error: str | None = None
        """What went wrong the last time the game tried to save itself.

        Surfaced on the snapshot so the player finds out before they close the
        tab rather than after."""
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
        rounds: int | None = None,
        race_distance: float | None = None,
    ) -> GameState:
        with self._lock:
            self._state = new_game(
                player_team=player_team,
                seed=seed,
                season=season,
                name=name,
                rounds=rounds,
                race_distance=race_distance,
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
                # Carrying on from a slot save does not make the game *own*
                # that slot.  The autosave is rewritten after every phase, so
                # a deliberate save that wrote back into it would be gone by
                # the next one -- it gets a save of its own instead.
                self._save_id = (
                    None if self._store.slot_of(save_id) is not None else save_id
                )
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

        A failure here is *reported and swallowed*, which is the opposite of
        what this file does everywhere else, and deliberately.  The autosave is
        a convenience on top of the work; if the save file has gone
        unwritable -- a full disk, a file deleted underneath a running server --
        letting that propagate would throw away the race the player just spent
        ten minutes on in order to complain about the thing that was meant to
        protect it.  The result is kept, the game stays live, and the player
        can save somewhere else.
        """
        if not self._autosave or self._state is None:
            return
        try:
            self._store.autosave(self._state)
            self._autosave_error = None
        except Exception as error:  # noqa: BLE001 - reported, see above
            self._autosave_error = f"{type(error).__name__}: {error}"
            _log.warning("autosave failed: %s", self._autosave_error)

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
            "autosave_error": self._autosave_error,
            # Which races can actually be played back.  Told rather than
            # guessed: without this a client has to ask for one and read the
            # 404 to find out, and only the most recent few are kept.
            "replays": sorted(state.replays),
            "player_team": state.player_team,
            # How long *this* season is.  A game started with `rounds` set has a
            # shorter calendar than the shipped one, and a screen that wants to
            # say "round 1 of 3" has to be told rather than assume the full set.
            "rounds": len(state.calendar),
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
                    "overall": round(state.driver(d).overall, 4),
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
        """The engine's own result, kept whole."""
        archive = self.state.race_archive.get(race_id)
        if archive is None:
            raise UnknownEntity(f"no race archived as {race_id!r}")
        return archive

    def replay(self, race_id: str) -> dict[str, Any]:
        """Where every car was, every couple of seconds."""
        replay = self.state.replays.get(race_id)
        if replay is None:
            raise UnknownEntity(
                f"no replay for {race_id!r}; races run before this build have "
                "a result but no track to play back"
            )
        return replay

    def track_geometry(self, round_number: int | None = None) -> dict[str, Any]:
        """The circuit a round is driven on, as a plan view.

        By round rather than by circuit id, because what matters to a client is
        which engine circuit this round actually runs on -- the calendar's
        circuit and the geometry underneath it are deliberately separate
        things.
        """
        from ..adapters.geometry import build_geometry
        from ..adapters.session_runner import track_for

        state = self.state
        number = round_number or state.current_round_number
        circuit = state.circuit_for(min(number, len(state.calendar)))
        geometry = build_geometry(track_for(circuit))
        return {**geometry.to_dict(), "circuit": circuit.to_dict()}

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

        session: Any = None
        labels: dict[int, dict[str, Any]] = {}

        def on_start(started: Any, field: Any) -> None:
            nonlocal session
            session = started
            labels.update(_labels_for(state, field))

        segments_done = 0

        def work(job: Job) -> dict[str, Any]:
            # Every flying lap that counts moves the board, so the order builds
            # up the way it does on a timing screen rather than arriving in
            # three jumps.
            def lap_set(lap: Any) -> None:
                job.live = build_live_qualifying(
                    session,
                    labels,
                    segment=lap.segment,
                    done=segments_done,
                    total=len(session.format),
                    complete=False,
                )

            def segment_done(name: str, done: int, total: int) -> None:
                nonlocal segments_done
                segments_done = done
                job.detail = f"{name} complete"
                job.progress = done / total
                # A finished segment is a result of its own -- who is through
                # and who is out -- so it is marked as one.
                job.live = build_live_qualifying(
                    session,
                    labels,
                    segment=name,
                    done=done,
                    total=total,
                    complete=True,
                )

            with self._lock:
                job.detail = "Q1 running"
                report = round_service.run_qualifying(
                    state,
                    on_segment=segment_done,
                    on_lap=lap_set,
                    on_start=on_start,
                )
                self._touch()
                return report.to_dict()

        return self._jobs.submit("qualifying", work, detail="qualifying")

    def run_race_job(self) -> Job:
        """Start the grand prix, showing it as it goes.

        The job carries the timing screen, not just a fraction: a race is
        minutes long and a bar creeping across says the same thing whether the
        player is leading it or three laps down.
        """
        state = self.state
        entry = state.current_round
        if entry is None:
            raise InvalidGamePhase("the season is over")
        entry.require(RoundPhase.STRATEGY)
        total = max(1, state.laps_for(entry.number))

        session: Any = None
        labels: dict[int, dict[str, Any]] = {}
        published = 0

        def on_start(started: Any, field: Any) -> None:
            nonlocal session
            session = started
            labels.update(_labels_for(state, field))

        def on_lap(race_entry: Any, lap_result: Any) -> None:
            nonlocal published
            lap = field_lap(session)
            if lap <= published:
                return
            published = lap
            job.progress = min(0.99, lap / total)
            job.live = build_live(session, labels, lap=lap, laps=total)

        def work(current: Job) -> dict[str, Any]:
            with self._lock:
                current.detail = f"racing {total} laps"
                report = round_service.run_race(
                    state, on_lap=on_lap, on_start=on_start
                )
                self._touch()
                return report.to_dict()

        job = self._jobs.submit("race", work, detail="grand prix")
        return job

    def run_development(self) -> dict[str, Any]:
        with self._lock:
            report = round_service.run_development(self.state)
            self._touch()
            return report.to_dict()

    def update_settings(
        self,
        *,
        race_distance: float | None = None,
        difficulty: str | None = None,
        hazards: bool | None = None,
    ) -> dict[str, Any]:
        """Change how the game is played.

        The race distance takes effect from the next race rather than
        retroactively: a round already run stays the length it was run at, so
        the season's results stay the season's results.
        """
        from ..game.settings import Difficulty

        with self._lock:
            settings = self.state.settings
            if race_distance is not None:
                settings.race_distance = race_distance
                settings.__post_init__()
            if difficulty is not None:
                settings.difficulty = Difficulty(difficulty)
            if hazards is not None:
                settings.hazards = hazards
            self._touch()
            return settings.to_dict()

    # -- the winter ----------------------------------------------------------

    def close_season(self) -> dict[str, Any]:
        """Settle the year and write it into the history book.

        Refused while there are rounds left, because a championship settled in
        August is not a championship.
        """
        from ..game import season as season_module

        with self._lock:
            state = self.state
            if not state.season_complete:
                raise InvalidGamePhase(
                    f"the {state.season} season still has round "
                    f"{state.current_round_number} to run"
                )
            if any(record.season == state.season for record in state.history):
                raise InvalidGamePhase(f"{state.season} has already been settled")
            summary = season_module.close_season(state)
            self._touch()
            return summary.to_dict()

    def start_next_season(self) -> dict[str, Any]:
        """The winter: age, rebase, re-sign, and a new calendar."""
        from ..game import season as season_module

        with self._lock:
            state = self.state
            if not state.season_complete:
                raise InvalidGamePhase(
                    f"the {state.season} season is still running"
                )
            if not any(record.season == state.season for record in state.history):
                raise InvalidGamePhase(
                    f"settle {state.season} before starting the next one"
                )
            report = season_module.start_next_season(state)
            self._touch()
            return {**report, "snapshot": self.snapshot()}

    def next_round(self) -> dict[str, Any]:
        return round_service.advance_to_next_round(self.state).to_dict()

    # -- between the races ---------------------------------------------------

    def _team_id(self, team_id: str | None) -> str:
        """Whose team an endpoint is talking about.

        Defaults to the player's.  A named team is allowed for reading -- a
        player can look at what a rival has been developing -- and the write
        operations below all resolve to the player's own regardless, because
        spending somebody else's money is not a move.
        """
        return team_id or self.state.player_team

    def development_options(self, team_id: str | None = None) -> dict[str, Any]:
        return management_service.development_options(self.state, self._team_id(team_id))

    def upgrades(self, team_id: str | None = None) -> list[dict[str, Any]]:
        return [u.to_dict() for u in self.state.upgrades_for(self._team_id(team_id))]

    def commission_upgrade(
        self, *, area: str, points: float, rushed: float = 0.0
    ) -> dict[str, Any]:
        with self._lock:
            upgrade = management_service.commission_upgrade(
                self.state,
                self.state.player_team,
                area=area,
                points=points,
                rushed=rushed,
            )
            self._touch()
            return upgrade.to_dict()

    def upgrade_facility(self, facility: str) -> dict[str, Any]:
        with self._lock:
            result = management_service.upgrade_facility(
                self.state, self.state.player_team, facility
            )
            self._touch()
            return result

    def finances(self, team_id: str | None = None) -> dict[str, Any]:
        return management_service.finances(self.state, self._team_id(team_id))

    def available_sponsors(self, team_id: str | None = None) -> list[dict[str, Any]]:
        return management_service.available_sponsors(self.state, self._team_id(team_id))

    def sign_sponsor(self, sponsor_id: str) -> dict[str, Any]:
        with self._lock:
            result = management_service.sign_sponsor(
                self.state, self.state.player_team, sponsor_id
            )
            self._touch()
            return result

    def negotiate(self, driver_id: str, **terms: Any) -> dict[str, Any]:
        return management_service.negotiate(
            self.state, self.state.player_team, driver_id, **terms
        )

    def sign_driver(self, driver_id: str, **terms: Any) -> dict[str, Any]:
        with self._lock:
            result = management_service.sign_driver(
                self.state, self.state.player_team, driver_id, **terms
            )
            self._touch()
            return result


def _labels_for(state: GameState, field: Any) -> dict[int, dict[str, Any]]:
    """Who is in which car, for a screen that shows a session as it runs.

    The engine works in car numbers and the game knows the names behind them,
    which is the same seam the replay is built across.
    """
    return {
        item.car_number: {
            "driver": state.driver(item.driver_id).name,
            "team": state.team(item.team_id).name,
            "is_player": item.team_id == state.player_team,
        }
        for item in field
    }
