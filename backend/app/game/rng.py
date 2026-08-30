"""One seed, and everything downstream of it (project rule 21).

The race engine already owns a deterministic randomness system: :class:`RngHub`
addresses streams by name and derives sub-seeds with BLAKE2b, so the same seed
and the same address always produce the same draw regardless of what else ran
first.  This does not replace any of that.  It is the *addressing scheme* the
management layer uses on top of it, so that a game and the races inside it draw
from one tree:

.. code-block:: text

    GameSeed
      |
      +-- season/2026
      |     |
      |     +-- round/7
      |     |     +-- qualifying   -> handed to the engine as its RngHub
      |     |     +-- race         -> handed to the engine as its RngHub
      |     |     +-- development  -> the game's own draws
      |     |
      |     +-- market             -> contract negotiations
      |
      +-- season/2027

Two properties matter and both fall out of the address rather than being
arranged for.  A save reloaded and re-run reaches the same address and gets the
same race, because nothing in the path depends on call order.  And running the
same round twice -- a replay, a what-if -- gets the same answer for the same
reason, which is what makes "load and try a different strategy" mean anything.
"""

from __future__ import annotations

from typing import Any

from f1_race_engine.core.rng import RandomStream, RngHub, derive_seed

__all__ = ["GameRng"]


class GameRng:
    """The management layer's view of the game's randomness.

    Never construct a :class:`random.Random`, and never call the :mod:`random`
    module, anywhere else in the game.  Ask this for a stream.
    """

    __slots__ = ("_seed", "_path", "_hub")

    def __init__(self, seed: int, path: str = "game") -> None:
        self._seed = int(seed)
        self._path = path
        self._hub = RngHub(self._seed)

    # -- identity ------------------------------------------------------------

    @property
    def seed(self) -> int:
        return self._seed

    @property
    def path(self) -> str:
        return self._path

    def __repr__(self) -> str:  # pragma: no cover - display helper
        return f"GameRng(seed={self._seed}, path={self._path!r})"

    # -- walking down the tree -----------------------------------------------

    def child(self, *parts: object) -> GameRng:
        """A sub-tree, addressed by name.

        The seed is derived from this one and the address, so two children with
        different names never collide and the same name always lands on the
        same stream.
        """
        suffix = "/".join(str(part) for part in parts)
        path = f"{self._path}/{suffix}"
        return GameRng(derive_seed(self._seed, path), path)

    def season(self, year: int) -> GameRng:
        return self.child("season", year)

    def round(self, number: int) -> GameRng:
        return self.child("round", number)

    def session(self, name: str) -> GameRng:
        return self.child("session", name)

    # -- drawing -------------------------------------------------------------

    def stream(self, name: str, **qualifiers: Any) -> RandomStream:
        """A named stream for the game's own draws.

        Repeated calls with the same address return the same stream, so it
        continues where it left off rather than restarting -- which is what the
        engine's hub does and what makes a sequence of draws reproducible.
        """
        return self._hub.stream(name, **qualifiers)

    def engine_hub(self, label: str) -> RngHub:
        """A hub to hand to the race engine for one session.

        The engine takes ownership of it and addresses its own streams
        underneath, so the game must not draw from it afterwards -- give each
        session its own.
        """
        return self._hub.spawn(label)

    # -- persistence ---------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {"seed": self._seed, "path": self._path}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GameRng:
        return cls(int(data["seed"]), str(data.get("path", "game")))
