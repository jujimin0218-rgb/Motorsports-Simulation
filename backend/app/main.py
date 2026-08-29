"""The server.

    uvicorn app.main:app --reload --app-dir backend

Three layers below this and none of them know about HTTP: the game, the
services that step it, and the adapter that hands a round to the race engine.
The engine itself knows about none of them.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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

    return app


app = create_app()
