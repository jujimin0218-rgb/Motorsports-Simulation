"""Turning a game refusal into an HTTP one.

Every :class:`GameError` carries a stable code and a status, so this is one
handler rather than a try/except in each endpoint -- and a client can branch on
the code without reading English.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ..game.errors import GameError

__all__ = ["install_error_handlers"]


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(GameError)
    async def _handle(request: Request, error: GameError) -> JSONResponse:
        return JSONResponse(
            status_code=error.status,
            content={"code": error.code, "message": str(error)},
        )
