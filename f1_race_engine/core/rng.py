"""Central, deterministic randomness.

Project rule 36 requires that the same seed plus the same inputs reproduce the
same race, and that random number generators are not created ad hoc across the
codebase.  A single shared stream would satisfy the letter of that rule but
breaks it in practice: as soon as a new subsystem (say, driver mistakes) draws
a number, every later draw in the simulation shifts, and *every* previously
recorded result changes.  For a project that expects to keep adding systems for
a long time, that is unacceptable.

This module therefore uses **named, hierarchical sub-streams**.  A stream is
addressed by a path plus optional qualifiers::

    hub = RngHub(seed=20260812)
    hub.stream("tyre.degradation", car=14, lap=23).normal(0.0, 1.0)

The seed of that stream is derived by hashing ``(master_seed, path)`` with
BLAKE2b, so:

* adding a new subsystem cannot perturb the streams that already exist;
* per-car and per-lap streams are independent, which keeps results identical
  whether cars are simulated in sequence or in parallel;
* replaying a single car's lap 23 needs no replay of everything before it.

Distributions are built on ``random.Random.random()`` only.  CPython's Mersenne
Twister output for ``random()`` is stable across versions, whereas the
implementations of ``gauss``/``shuffle`` are not contractually fixed, so the
transforms are implemented here to keep archived results reproducible.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from dataclasses import dataclass
from random import Random
from typing import Any, TypeVar

from .errors import F1EngineError

T = TypeVar("T")

_SEED_BYTES = 8
_MAX_SEED = 1 << (8 * _SEED_BYTES)


def derive_seed(master_seed: int, path: str) -> int:
    """Derive a stable 64-bit sub-seed from ``master_seed`` and ``path``.

    Uses BLAKE2b rather than :func:`hash`, whose results are randomised per
    process by PYTHONHASHSEED and would destroy reproducibility.
    """
    payload = f"{master_seed}\x00{path}".encode()
    digest = hashlib.blake2b(payload, digest_size=_SEED_BYTES).digest()
    return int.from_bytes(digest, "big")


def format_stream_path(name: str, qualifiers: dict[str, Any]) -> str:
    """Render a stream address, e.g. ``"tyre.wear|car=14|lap=23"``."""
    if not qualifiers:
        return name
    parts = "|".join(f"{k}={qualifiers[k]}" for k in sorted(qualifiers))
    return f"{name}|{parts}"


class RandomStream:
    """An independent, named random stream.

    Instances are produced by :class:`RngHub`; construct them directly only in
    tests.  Every draw increments :attr:`draw_count`, which makes it easy to
    spot a subsystem that is consuming randomness it should not.
    """

    __slots__ = ("_random", "_seed", "_path", "_draws")

    def __init__(self, seed: int, path: str = "<anonymous>") -> None:
        self._seed = seed % _MAX_SEED
        self._path = path
        self._random = Random(self._seed)
        self._draws = 0

    # -- identity ------------------------------------------------------------

    @property
    def path(self) -> str:
        return self._path

    @property
    def seed(self) -> int:
        return self._seed

    @property
    def draw_count(self) -> int:
        """Number of raw uniform draws taken from this stream."""
        return self._draws

    def reset(self) -> None:
        """Rewind the stream to its initial state."""
        self._random.seed(self._seed)
        self._draws = 0

    def derive(self, *path_parts: object) -> RandomStream:
        """Create a child stream addressed below this one."""
        suffix = "/".join(str(part) for part in path_parts)
        child_path = f"{self._path}/{suffix}"
        return RandomStream(derive_seed(self._seed, child_path), child_path)

    # -- primitive draw ------------------------------------------------------

    def random(self) -> float:
        """Uniform draw in ``[0.0, 1.0)``."""
        self._draws += 1
        return self._random.random()

    # -- distributions -------------------------------------------------------

    def uniform(self, low: float, high: float) -> float:
        """Uniform draw in ``[low, high)``."""
        return low + (high - low) * self.random()

    def integer(self, low: int, high: int) -> int:
        """Uniform integer in ``[low, high]`` (both inclusive)."""
        if high < low:
            raise ValueError(f"empty integer range [{low}, {high}]")
        span = high - low + 1
        return low + min(int(self.random() * span), span - 1)

    def normal(self, mean: float = 0.0, sigma: float = 1.0) -> float:
        """Normal draw via Box-Muller.

        Consumes exactly two uniform draws per call.  The second Box-Muller
        output is deliberately discarded rather than cached: a cached spare
        makes the number of draws depend on call history, which turns
        debugging a divergence into guesswork.
        """
        if sigma < 0.0:
            raise ValueError("sigma must be non-negative")
        if sigma == 0.0:
            self._draws += 2
            self._random.random()
            self._random.random()
            return mean
        u1 = self.random()
        u2 = self.random()
        # random() can return exactly 0.0; shift it off the log singularity.
        if u1 <= 0.0:
            u1 = 5e-324
        return mean + sigma * math.sqrt(-2.0 * math.log(u1)) * math.cos(math.tau * u2)

    def truncated_normal(
        self,
        mean: float = 0.0,
        sigma: float = 1.0,
        low: float = -math.inf,
        high: float = math.inf,
        *,
        max_attempts: int = 16,
    ) -> float:
        """Normal draw clipped to ``[low, high]``.

        Re-draws up to ``max_attempts`` times, then clamps.  Clamping rather
        than looping forever keeps a badly configured sigma from hanging a
        race simulation.
        """
        if low > high:
            raise ValueError(f"empty range [{low}, {high}]")
        for _ in range(max_attempts):
            value = self.normal(mean, sigma)
            if low <= value <= high:
                return value
        return min(max(self.normal(mean, sigma), low), high)

    def triangular(self, low: float, high: float, mode: float | None = None) -> float:
        """Triangular draw -- useful for asymmetric, bounded quantities."""
        if high < low:
            raise ValueError(f"empty range [{low}, {high}]")
        if high == low:
            self.random()
            return low
        peak = (low + high) / 2.0 if mode is None else mode
        if not low <= peak <= high:
            raise ValueError(f"mode {peak} outside [{low}, {high}]")
        u = self.random()
        c = (peak - low) / (high - low)
        if u < c:
            return low + math.sqrt(u * (high - low) * (peak - low))
        return high - math.sqrt((1.0 - u) * (high - low) * (high - peak))

    def chance(self, probability: float) -> bool:
        """Return ``True`` with the given probability."""
        if probability <= 0.0:
            self.random()
            return False
        if probability >= 1.0:
            self.random()
            return True
        return self.random() < probability

    def choice(self, items: Sequence[T]) -> T:
        """Pick one element uniformly."""
        if not items:
            raise ValueError("cannot choose from an empty sequence")
        return items[self.integer(0, len(items) - 1)]

    def weighted_choice(self, items: Sequence[T], weights: Sequence[float]) -> T:
        """Pick one element with the given non-negative weights."""
        if len(items) != len(weights):
            raise ValueError("items and weights must have the same length")
        if not items:
            raise ValueError("cannot choose from an empty sequence")
        total = math.fsum(weights)
        if total <= 0.0:
            raise ValueError("weights must sum to a positive value")
        target = self.random() * total
        cumulative = 0.0
        for item, weight in zip(items, weights):
            if weight < 0.0:
                raise ValueError("weights must be non-negative")
            cumulative += weight
            if target < cumulative:
                return item
        return items[-1]

    def shuffled(self, items: Sequence[T]) -> list[T]:
        """Return a shuffled copy using an explicit Fisher-Yates pass.

        Note: this exists for tie-breaks and crew-order style bookkeeping.  It
        must never be used to decide finishing order (project rule 2.1).
        """
        result = list(items)
        for i in range(len(result) - 1, 0, -1):
            j = self.integer(0, i)
            result[i], result[j] = result[j], result[i]
        return result

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"RandomStream(path={self._path!r}, seed={self._seed}, draws={self._draws})"


@dataclass(frozen=True, slots=True)
class RngSnapshot:
    """A record of which streams exist and how far each has advanced."""

    master_seed: int
    streams: tuple[tuple[str, int, int], ...]  # (path, seed, draw_count)

    def to_dict(self) -> dict[str, Any]:
        return {
            "master_seed": self.master_seed,
            "streams": [
                {"path": path, "seed": seed, "draws": draws}
                for path, seed, draws in self.streams
            ],
        }


class RngHub:
    """The single owner of randomness for one simulation run.

    Pass the hub down through the simulation; never call :mod:`random` module
    functions or construct a bare :class:`random.Random` anywhere else.
    """

    __slots__ = ("_master_seed", "_streams")

    def __init__(self, seed: int) -> None:
        if not isinstance(seed, int):
            raise F1EngineError(f"seed must be an int, got {type(seed).__name__}")
        self._master_seed = seed
        self._streams: dict[str, RandomStream] = {}

    @property
    def master_seed(self) -> int:
        return self._master_seed

    def stream(self, name: str, **qualifiers: Any) -> RandomStream:
        """Return (creating on first use) the stream at ``name``/``qualifiers``.

        Repeated calls with the same address return the *same* object, so the
        stream continues where it left off rather than restarting.
        """
        path = format_stream_path(name, qualifiers)
        stream = self._streams.get(path)
        if stream is None:
            stream = RandomStream(derive_seed(self._master_seed, path), path)
            self._streams[path] = stream
        return stream

    def seed_for(self, name: str, **qualifiers: Any) -> int:
        """Derive a stream's seed without materialising the stream."""
        return derive_seed(self._master_seed, format_stream_path(name, qualifiers))

    def spawn(self, seed_offset_label: str) -> RngHub:
        """Create an independent hub, e.g. one per session within a weekend."""
        return RngHub(derive_seed(self._master_seed, f"hub/{seed_offset_label}"))

    def reset(self) -> None:
        """Rewind every existing stream to its initial state."""
        for stream in self._streams.values():
            stream.reset()

    def forget(self) -> None:
        """Drop all streams; the next access recreates them from the seed."""
        self._streams.clear()

    @property
    def active_paths(self) -> tuple[str, ...]:
        return tuple(sorted(self._streams))

    def snapshot(self) -> RngSnapshot:
        """Capture stream bookkeeping for debugging and result provenance."""
        return RngSnapshot(
            master_seed=self._master_seed,
            streams=tuple(
                (path, self._streams[path].seed, self._streams[path].draw_count)
                for path in sorted(self._streams)
            ),
        )

    def total_draws(self) -> int:
        return sum(stream.draw_count for stream in self._streams.values())

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"RngHub(seed={self._master_seed}, streams={len(self._streams)}, "
            f"draws={self.total_draws()})"
        )
