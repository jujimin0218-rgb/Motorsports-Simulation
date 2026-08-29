"""Where an endpoint gets the game from.

One service for the process, created on first use.  A test replaces it with
``app.dependency_overrides[get_service]``, which is why every endpoint asks for
it rather than reaching for a module global.
"""

from __future__ import annotations

import os

from ..services.game_service import GameService

__all__ = ["get_service", "reset_service"]

_service: GameService | None = None


def get_service() -> GameService:
    global _service
    if _service is None:
        _service = GameService(
            store=None if not os.environ.get("F1_GAME_SAVE_DB") else None,
        )
    return _service


def reset_service() -> None:
    """Drop the process's game.  For tests and for a clean shutdown."""
    global _service
    if _service is not None:
        _service.close()
    _service = None
