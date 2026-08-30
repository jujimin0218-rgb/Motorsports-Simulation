"""The server.

    uvicorn app.main:app --reload --app-dir backend

Three layers below this and none of them know about HTTP: the game, the
services that step it, and the adapter that hands a round to the race engine.
The engine itself knows about none of them.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api.dependencies import reset_service
from .api.errors import install_error_handlers
from .api.routes import router

__all__ = ["app", "create_app"]


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Nothing to do on the way up; on the way down, let go of the game.

    The job runner owns threads and the save store owns a SQLite connection,
    and both should be released rather than left to the interpreter."""
    yield
    reset_service()


def create_app() -> FastAPI:
    app = FastAPI(
        lifespan=_lifespan,
        title="F1 Season Management",
        version="0.1.0",
        summary="A season built on top of the physics-based race engine.",
        description=(
            "The management layer never simulates a race.  It assembles the "
            "field, hands it to f1_race_engine, and reads the result back."
        ),
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    install_error_handlers(app)
    app.include_router(router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    _mount_frontend(app)
    return app


#: The built frontend, when there is one.
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def _mount_frontend(app: FastAPI) -> None:
    """Serve the built frontend from this same process, if it has been built.

    Two processes and a proxy is the right shape while developing -- Vite
    reloads, the API restarts, neither waits for the other -- and it is the
    wrong shape for somebody who just wants to play.  So when ``frontend/dist``
    exists it is served from here, which makes the whole thing one command and
    one port, and incidentally removes the CORS question entirely: the page and
    the API are then the same origin.

    Without a build this does nothing at all, and ``npm run dev`` works exactly
    as before.
    """
    if not (FRONTEND_DIST / "index.html").is_file():
        return

    app.mount(
        "/assets",
        StaticFiles(directory=FRONTEND_DIST / "assets"),
        name="assets",
    )

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        """Any path the API did not claim is a route inside the app.

        Registered last, so it never shadows ``/api`` or ``/health``: FastAPI
        matches in order.  A file that really is on disk is served; everything
        else gets ``index.html`` and the client router works out what it means,
        which is what makes a deep link like ``/standings`` survive a reload.
        """
        candidate = (FRONTEND_DIST / path).resolve()
        if (
            path
            and candidate.is_file()
            and candidate.is_relative_to(FRONTEND_DIST.resolve())
        ):
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")


app = create_app()
