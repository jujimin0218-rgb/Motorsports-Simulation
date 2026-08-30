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

A zone may **wrap the start/finish line**, and several real ones do: at Monza
the flap opens on the exit of the Parabolica and closes on the approach to the
Rettifilo, with the timing line in between.  The line is a timing device, not a
feature of the road, so nothing about a zone should change when it moves.  A
zone whose end is behind its start is therefore read as wrapping, which is why
:class:`DrsZone` needs to know the lap length.
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
    lap_length: Metres | None = None
    """Lap length, m.  Required only for a zone that wraps the timing line."""

    def __post_init__(self) -> None:
        if self.activation_end > self.activation_start:
            return
        if self.lap_length is None or self.lap_length <= 0.0:
            raise TrackBuildError(
                f"DRS zone {self.index}: activation end ({self.activation_end} m) is "
                f"not beyond its start ({self.activation_start} m), so the zone wraps "
                f"the start/finish line -- which needs the lap length to describe"
            )
        if self.activation_start >= self.lap_length or self.activation_end < 0.0:
            raise TrackBuildError(
                f"DRS zone {self.index}: activation range "
                f"({self.activation_start} m, {self.activation_end} m) falls outside "
                f"a lap of {self.lap_length} m"
            )
        if self.length <= 0.0:
            raise TrackBuildError(
                f"DRS zone {self.index}: activation zone has no length"
            )

    @property
    def wraps(self) -> bool:
        """Whether the zone runs across the start/finish line."""
        return self.activation_end <= self.activation_start

    @property
    def length(self) -> Metres:
        """Length of the activation zone, m."""
        if not self.wraps:
            return self.activation_end - self.activation_start
        assert self.lap_length is not None
        return (self.activation_end - self.activation_start) % self.lap_length

    def contains(self, distance: Metres) -> bool:
        """Is ``distance`` inside the activation zone?"""
        if not self.wraps:
            return self.activation_start <= distance < self.activation_end
        return distance >= self.activation_start or distance < self.activation_end

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "index": self.index,
            "name": self.name,
            "detection_distance": self.detection_distance,
            "activation_start": self.activation_start,
            "activation_end": self.activation_end,
            "length": self.length,
        }
        if self.lap_length is not None:
            payload["lap_length"] = self.lap_length
        return payload


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
        """Pairs of zone indices whose activation ranges overlap.

        Compared as arcs of the lap rather than as intervals on a line, so a
        zone that wraps the timing line is checked against the others properly
        instead of appearing to end before it starts.
        """
        clashes: list[tuple[int, int]] = []
        for i, a in enumerate(self._zones):
            for b in self._zones[i + 1 :]:
                if self._arcs_overlap(a, b):
                    # Reported low index first: with a wrapping zone the order
                    # the zones sort in says nothing useful.
                    clashes.append(tuple(sorted((a.index, b.index))))  # type: ignore[arg-type]
        return sorted(clashes)

    def _arcs_overlap(self, a: DrsZone, b: DrsZone) -> bool:
        """Whether two activation arcs share any of the lap between them."""
        length = self._lap_length
        if length <= 0.0:
            return False
        # Two arcs on a circle overlap unless each one's start lies outside the
        # other, which is exactly what ``contains`` answers.
        return (
            a.contains(b.activation_start % length)
            or b.contains(a.activation_start % length)
        )

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
