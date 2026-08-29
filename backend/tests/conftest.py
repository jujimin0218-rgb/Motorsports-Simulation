"""Fixtures for the game's tests.

Every test that touches a game gets a fresh one with a fixed seed, because the
whole point of the seed is that a fixed one produces a fixed game.
"""

from __future__ import annotations

import pytest

from app.game.newgame import new_game
from app.game.state import GameState
from app.services.storage import SaveStore


@pytest.fixture
def game() -> GameState:
    """A new season with the player in the smallest team.

    The smallest on purpose: a bug that only shows up when the budget is tight
    or the car is slow is one the biggest team would hide.
    """
    return new_game(player_team="harrow", seed=20260101)


@pytest.fixture
def store() -> SaveStore:
    with SaveStore(":memory:") as opened:
        yield opened
