"""DRS zones.

A DRS zone is three distances, not one (project rule 25):

* the **detection point**, where the gap to the car ahead is measured;
* the **activation start**, where the flap may be opened;
* the **activation end**, where it must close.

The track only stores *where* DRS is available.  Whether a given car may
actually use it -- gap under one second, not the first laps, no wet flag -- is a
race-core decision taken in Phase 9, and the drag reduction itself belongs to
the aero model.  Keeping those three concerns apart is what stops DRS from
becoming a lap-time bonus.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any

from ..core.errors import TrackBuildError
from ..core.units import Metres

__all__ = ["DrsMap", "DrsZone"]


@dataclass(frozen=True, slots=True)
class DrsZone:
    """One DRS zone on the circuit."""

    index: int
    detection_distance: Metres
    activation_start: Metres
    activation_end: Metres
    name: str | None = None

    def __post_init__(self) -> None:
        if self.activation_end <= self.activation_start:
            raise TrackBuildError(
                f"DRS zone {self.index}: activation end ({self.activation_end} m) "
                f"must be beyond its start ({self.activation_start} m)"
            )

    @property
    def length(self) -> Metres:
        """Length of the activation zone, m."""
        return self.activation_end - self.activation_start

    def contains(self, distance: Metres) -> bool:
        """Is ``distance`` inside the activation zone?"""
        return self.activation_start <= distance < self.activation_end

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "name": self.name,
            "detection_distance": self.detection_distance,
            "activation_start": self.activation_start,
            "activation_end": self.activation_end,
            "length": self.length,
        }


class DrsMap:
    """All DRS zones on a circuit, ordered by activation start."""

    __slots__ = ("_zones", "_lap_length")

    def __init__(self, zones: Iterable[DrsZone], lap_length: Metres) -> None:
        ordered = sorted(zones, key=lambda z: z.activation_start)
        self._zones = tuple(ordered)
        self._lap_length = lap_length

    @property
    def zones(self) -> tuple[DrsZone, ...]:
        return self._zones

    @property
    def lap_length(self) -> Metres:
        return self._lap_length

    @property
    def total_length(self) -> Metres:
        """Combined length of all activation zones, m."""
        return sum(zone.length for zone in self._zones)

    @property
    def coverage(self) -> float:
        """Fraction of the lap over which DRS is available."""
        if self._lap_length <= 0.0:
            return 0.0
        return self.total_length / self._lap_length

    def zone_at(self, distance: Metres) -> DrsZone | None:
        """The activation zone covering ``distance``, if any."""
        for zone in self._zones:
            if zone.contains(distance):
                return zone
        return None

    def zone_index_at(self, distance: Metres) -> int | None:
        zone = self.zone_at(distance)
        return None if zone is None else zone.index

    def overlaps(self) -> list[tuple[int, int]]:
        """Pairs of zone indices whose activation ranges overlap."""
        clashes: list[tuple[int, int]] = []
        for a, b in zip(self._zones, self._zones[1:]):
            if b.activation_start < a.activation_end:
                clashes.append((a.index, b.index))
        return clashes

    def to_dict(self) -> list[dict[str, Any]]:
        return [zone.to_dict() for zone in self._zones]

    def __len__(self) -> int:
        return len(self._zones)

    def __iter__(self) -> Iterator[DrsZone]:
        return iter(self._zones)

    def __getitem__(self, item: int) -> DrsZone:
        return self._zones[item]

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"DrsMap(zones={len(self._zones)}, coverage={self.coverage:.1%})"
