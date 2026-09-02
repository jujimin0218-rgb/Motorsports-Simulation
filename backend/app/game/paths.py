"""Where the game's static data lives.

Kept in one place so that the data directory can move -- or be pointed at a
different set of teams and drivers -- without every loader knowing about it.
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = ["data_dir", "data_file"]

_ENV_VAR = "F1_GAME_DATA_DIR"
_DEFAULT = Path(__file__).resolve().parents[3] / "data"


def data_dir() -> Path:
    """The directory holding ``rules.json`` and friends.

    ``F1_GAME_DATA_DIR`` overrides it, which is what lets a test run against a
    fixture set and a player run against a community one.
    """
    override = os.environ.get(_ENV_VAR)
    return Path(override) if override else _DEFAULT


def data_file(*parts: str) -> Path:
    return data_dir().joinpath(*parts)
