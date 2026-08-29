"""The HTTP surface.

Thin by design: every endpoint resolves the service, calls one method and
returns what it gets.  All the rules -- what phase a round is in, whether a
team can afford something, whether a save exists -- live below this, so an
endpoint has nothing to decide and no way to disagree with the game about it.

The two long sessions, qualifying and the race, return a **job** rather than a
result.  A grand prix is minutes of simulation and holding a request open for
it would be a lie about what is happening; the client starts it and polls.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from ..game.errors import SaveNotFound
from ..schemas.common import LoadRequest, NewGameRequest, SaveRequest
from ..services.game_service import GameService
from .dependencies import get_service

router = APIRouter(prefix="/api")


# -- the game ----------------------------------------------------------------


@router.get("/game", summary="Everything a dashboard needs")
def read_game(service: GameService = Depends(get_service)) -> dict[str, Any]:
    return service.snapshot()


@router.get("/game/teams", summary="Teams a new player may take over")
def selectable_teams(service: GameService = Depends(get_service)) -> list[dict[str, Any]]:
    return service.teams_available()


@router.post("/game/new", summary="Start a season")
def start_game(
    request: NewGameRequest, service: GameService = Depends(get_service)
) -> dict[str, Any]:
    service.start(
        player_team=request.player_team,
        seed=request.seed,
        season=request.season,
        name=request.name,
    )
    return service.snapshot()


@router.post("/game/save")
def save_game(
    request: SaveRequest, service: GameService = Depends(get_service)
) -> dict[str, Any]:
    return service.save(
        save_id=request.save_id, slot=request.slot, name=request.name
    ).to_dict()


@router.post("/game/load")
def load_game(
    request: LoadRequest, service: GameService = Depends(get_service)
) -> dict[str, Any]:
    service.load(save_id=request.save_id, slot=request.slot)
    return service.snapshot()


@router.get("/game/saves")
def list_saves(service: GameService = Depends(get_service)) -> list[dict[str, Any]]:
    return [summary.to_dict() for summary in service.saves()]


@router.delete("/game/saves/{save_id}")
def delete_save(save_id: str, service: GameService = Depends(get_service)) -> dict[str, str]:
    service.delete_save(save_id)
    return {"deleted": save_id}


# -- the season --------------------------------------------------------------


@router.get("/season")
def read_season(service: GameService = Depends(get_service)) -> dict[str, Any]:
    state = service.state
    current = state.current_round
    return {
        "season": state.season,
        "rounds": len(state.calendar),
        "current_round": None if current is None else current.number,
        "phase": None if current is None else current.phase.value,
        "complete": state.season_complete,
        "settings": state.settings.to_dict(),
    }


@router.get("/calendar")
def read_calendar(service: GameService = Depends(get_service)) -> list[dict[str, Any]]:
    return service.calendar()


@router.get("/teams")
def read_teams(service: GameService = Depends(get_service)) -> list[dict[str, Any]]:
    return service.teams()


@router.get("/drivers")
def read_drivers(
    free_agents: bool = Query(default=False, description="Only drivers without a seat."),
    service: GameService = Depends(get_service),
) -> list[dict[str, Any]]:
    return service.drivers(free_agents_only=free_agents)


@router.get("/standings")
def read_standings(service: GameService = Depends(get_service)) -> dict[str, Any]:
    return service.state.standings().to_dict()


@router.get("/history")
def read_history(service: GameService = Depends(get_service)) -> list[dict[str, Any]]:
    return service.history()


# -- a race weekend ----------------------------------------------------------


@router.post("/round/start")
def start_round(service: GameService = Depends(get_service)) -> dict[str, Any]:
    return service.start_round()


@router.post("/round/practice")
def run_practice(service: GameService = Depends(get_service)) -> dict[str, Any]:
    return service.run_practice()


@router.post("/qualifying/run", summary="Start qualifying (returns a job)")
def run_qualifying(service: GameService = Depends(get_service)) -> dict[str, Any]:
    return service.run_qualifying_job().to_dict()


@router.post("/race/run", summary="Start the grand prix (returns a job)")
def run_race(service: GameService = Depends(get_service)) -> dict[str, Any]:
    return service.run_race_job().to_dict()


@router.post("/round/development")
def run_development(service: GameService = Depends(get_service)) -> dict[str, Any]:
    return service.run_development()


@router.get("/round/next")
def next_round(service: GameService = Depends(get_service)) -> dict[str, Any]:
    return service.next_round()


@router.get("/race/{race_id}", summary="A finished race, whole, for the replay")
def read_race(race_id: str, service: GameService = Depends(get_service)) -> dict[str, Any]:
    return service.race(race_id)


# -- jobs --------------------------------------------------------------------


@router.get("/jobs/{job_id}")
def read_job(job_id: str, service: GameService = Depends(get_service)) -> dict[str, Any]:
    job = service.jobs.get(job_id)
    if job is None:
        raise SaveNotFound(f"no job {job_id!r}")
    return job.to_dict()


@router.get("/jobs")
def list_jobs(
    limit: int = Query(default=10, ge=1, le=40),
    service: GameService = Depends(get_service),
) -> list[dict[str, Any]]:
    return [job.to_dict() for job in service.jobs.recent(limit)]
