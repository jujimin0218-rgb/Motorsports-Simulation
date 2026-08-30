"""Saving and loading, on SQLite.

One row per save, with the whole :class:`GameState` in it as JSON and the few
fields a save list needs to show lifted out into columns.  That split is
deliberate: listing saves is a query rather than a parse of every game on disk,
while the game itself stays one document with no schema to migrate every time a
field is added to a team.

Reloading is exact.  The state that comes back is the state that went in --
including the seed -- so a round replayed after a load is the same round.

One connection, guarded by a lock, opened with ``check_same_thread=False``.  A
SQLite connection is bound to the thread that opened it unless told otherwise,
and this store is reached from three: the request thread, the pool a sync
endpoint runs in, and the worker running a race.  Serialising it is correct
rather than merely convenient -- these writes are a save file, they are small
and rare, and two of them interleaving would be a corrupted game.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..game.errors import SaveNotFound
from ..game.state import GameState

__all__ = ["SaveStore", "SaveSummary", "AUTOSAVE_SLOT"]

#: The slot the game writes to on its own.  Reserved so that an autosave can
#: never quietly overwrite a save the player made deliberately.
AUTOSAVE_SLOT = "autosave"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS saves (
    id          TEXT PRIMARY KEY,
    slot        TEXT,
    name        TEXT NOT NULL,
    season      INTEGER NOT NULL,
    round       INTEGER NOT NULL,
    player_team TEXT NOT NULL,
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL,
    payload     TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS saves_slot ON saves(slot) WHERE slot IS NOT NULL;
CREATE INDEX IF NOT EXISTS saves_updated ON saves(updated_at DESC);
"""


@dataclass(frozen=True, slots=True)
class SaveSummary:
    """Enough to draw a load-game screen without opening the save."""

    id: str
    name: str
    season: int
    round: int
    player_team: str
    created_at: float
    updated_at: float
    slot: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "slot": self.slot,
            "name": self.name,
            "season": self.season,
            "round": self.round,
            "player_team": self.player_team,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class SaveStore:
    """The save file.  ``:memory:`` is a perfectly good one, and is what the
    tests use."""

    __slots__ = ("_path", "_connection", "_lock")

    def __init__(self, path: str | Path = "saves.db") -> None:
        self._path = str(path)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(self._path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.executescript(_SCHEMA)
        self._connection.commit()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self) -> SaveStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- writing -------------------------------------------------------------

    def save(
        self,
        state: GameState,
        *,
        save_id: str | None = None,
        slot: str | None = None,
    ) -> SaveSummary:
        """Write a game, creating it or overwriting it in place.

        Passing ``slot`` writes to a named slot -- the autosave, say -- and
        replaces whatever was in it.  Passing ``save_id`` overwrites that
        particular save.  Passing neither creates a new one.
        """
        payload = json.dumps(state.to_dict(), separators=(",", ":"))
        now = time.time()
        with self._lock:
            existing = None
            if save_id is not None:
                existing = self._row(save_id)
            elif slot is not None:
                existing = self._connection.execute(
                    "SELECT * FROM saves WHERE slot = ?", (slot,)
                ).fetchone()

            summary = SaveSummary(
                id=existing["id"] if existing else (save_id or uuid.uuid4().hex),
                name=state.name,
                season=state.season,
                round=state.current_round_number,
                player_team=state.player_team,
                created_at=existing["created_at"] if existing else now,
                updated_at=now,
                slot=slot
                if slot is not None
                else (existing["slot"] if existing else None),
            )
            self._connection.execute(
                "INSERT INTO saves (id, slot, name, season, round, player_team, "
                "created_at, updated_at, payload) VALUES (?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET slot=excluded.slot, "
                "name=excluded.name, season=excluded.season, "
                "round=excluded.round, player_team=excluded.player_team, "
                "updated_at=excluded.updated_at, payload=excluded.payload",
                (
                    summary.id,
                    summary.slot,
                    summary.name,
                    summary.season,
                    summary.round,
                    summary.player_team,
                    summary.created_at,
                    summary.updated_at,
                    payload,
                ),
            )
            self._connection.commit()
            return summary

    def autosave(self, state: GameState) -> SaveSummary:
        return self.save(state, slot=AUTOSAVE_SLOT)

    # -- reading -------------------------------------------------------------

    def load(self, save_id: str) -> GameState:
        with self._lock:
            row = self._row(save_id)
        if row is None:
            raise SaveNotFound(f"no save with id {save_id!r}")
        return GameState.from_dict(json.loads(row["payload"]))

    def load_slot(self, slot: str) -> GameState:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM saves WHERE slot = ?", (slot,)
            ).fetchone()
        if row is None:
            raise SaveNotFound(f"nothing saved in slot {slot!r}")
        return GameState.from_dict(json.loads(row["payload"]))

    def list(self, *, limit: int = 50) -> list[SaveSummary]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM saves ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [
            SaveSummary(
                id=row["id"],
                slot=row["slot"],
                name=row["name"],
                season=row["season"],
                round=row["round"],
                player_team=row["player_team"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    def delete(self, save_id: str) -> None:
        with self._lock:
            cursor = self._connection.execute(
                "DELETE FROM saves WHERE id = ?", (save_id,)
            )
            self._connection.commit()
        if cursor.rowcount == 0:
            raise SaveNotFound(f"no save with id {save_id!r}")

    def _row(self, save_id: str) -> sqlite3.Row | None:
        return self._connection.execute(
            "SELECT * FROM saves WHERE id = ?", (save_id,)
        ).fetchone()
