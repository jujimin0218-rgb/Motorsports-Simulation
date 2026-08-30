"""Track surface: the static properties and the evolving condition.

This module draws a line that the rest of the engine depends on.

**Static surface properties** -- asphalt type, base grip, roughness -- are part
of the circuit.  They are built once and shared by all twenty cars, and they
live on :class:`~f1_race_engine.track.segment.TrackSegment`.

**Surface condition** -- rubber laid down, marbles off-line, standing water,
grip evolution over a session -- changes while the session runs.  It lives here
in :class:`TrackConditions`, a small mutable array running parallel to the
segments.  Physics asks for the *effective* grip at a distance and gets the
combination of both.

The split is deliberate.  Track evolution, rain and drying (Phase 10) only ever
mutate :class:`TrackConditions`; the track geometry stays immutable and
shareable.  In Phase 1 every condition sits at its neutral value, so the
effective grip equals the static grip exactly -- the model is real and
calibratable, it simply has nothing to report yet.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from ..core.config import TrackConditionsConfig
from ..core.errors import TrackBuildError
from ..core.interpolation import clamp
from ..core.units import Metres
from .segment import KerbType, SurfaceType, TrackSegment

__all__ = [
    "KerbMap",
    "SurfaceCondition",
    "SurfaceRegion",
    "SurfaceMap",
    "TrackConditions",
]


@dataclass(frozen=True, slots=True)
class SurfaceRegion:
    """A stretch of track with distinct static surface properties."""

    start: Metres
    end: Metres
    surface_type: SurfaceType = SurfaceType.ASPHALT
    grip: float = 1.0
    roughness: float = 0.5
    name: str | None = None

    def __post_init__(self) -> None:
        if self.end <= self.start:
            raise TrackBuildError(
                f"surface region {self.name or ''} ends ({self.end} m) at or "
                f"before it starts ({self.start} m)"
            )
        if self.grip <= 0.0:
            raise TrackBuildError(f"surface grip must be positive, got {self.grip}")

    def contains(self, distance: Metres) -> bool:
        return self.start <= distance < self.end

    def to_dict(self) -> dict[str, Any]:
        return {
            "start": self.start,
            "end": self.end,
            "surface_type": self.surface_type.value,
            "grip": self.grip,
            "roughness": self.roughness,
            "name": self.name,
        }


class SurfaceMap:
    """Static surface properties as a function of distance.

    Regions override the circuit default; anything not covered by a region uses
    the defaults supplied at construction.
    """

    __slots__ = ("_regions", "_default_type", "_default_grip", "_default_roughness")

    def __init__(
        self,
        regions: Iterable[SurfaceRegion] = (),
        *,
        default_type: SurfaceType = SurfaceType.ASPHALT,
        default_grip: float = 1.0,
        default_roughness: float = 0.5,
    ) -> None:
        self._regions = tuple(sorted(regions, key=lambda r: r.start))
        self._default_type = default_type
        self._default_grip = default_grip
        self._default_roughness = default_roughness

    @property
    def regions(self) -> tuple[SurfaceRegion, ...]:
        return self._regions

    def region_at(self, distance: Metres) -> SurfaceRegion | None:
        for region in self._regions:
            if region.contains(distance):
                return region
        return None

    def at(self, distance: Metres) -> tuple[SurfaceType, float, float]:
        """Return ``(surface_type, grip, roughness)`` at ``distance``."""
        region = self.region_at(distance)
        if region is None:
            return self._default_type, self._default_grip, self._default_roughness
        return region.surface_type, region.grip, region.roughness

    def to_dict(self) -> dict[str, Any]:
        return {
            "default_type": self._default_type.value,
            "default_grip": self._default_grip,
            "default_roughness": self._default_roughness,
            "regions": [r.to_dict() for r in self._regions],
        }


class KerbMap:
    """Where kerbing is available, as a function of distance.

    Kept beside the surface map because both answer the same kind of question
    -- what is under (or beside) the car here -- and because both must be
    resolved at an exact distance rather than read off a sampled segment.
    """

    __slots__ = ("_regions", "_default")

    def __init__(
        self,
        regions: Iterable[tuple[float, float, KerbType]] = (),
        *,
        default: KerbType = KerbType.NONE,
    ) -> None:
        self._regions = tuple(sorted(regions, key=lambda r: r[0]))
        self._default = default

    @property
    def regions(self) -> tuple[tuple[float, float, KerbType], ...]:
        return self._regions

    def at(self, distance: Metres) -> KerbType:
        for start, end, kerb in self._regions:
            if start <= distance < end:
                return kerb
        return self._default

    def to_dict(self) -> dict[str, Any]:
        return {
            "default": self._default.value,
            "regions": [
                {"start": start, "end": end, "kerb": kerb.value}
                for start, end, kerb in self._regions
            ],
        }


@dataclass(slots=True)
class SurfaceCondition:
    """Mutable, session-dependent state of one segment's surface.

    All fields are neutral at zero, which is why a freshly built track behaves
    exactly like its static definition.
    """

    rubber: float = 0.0
    """Rubber laid into the racing line, 0 (green) to 1 (fully rubbered in)."""

    marbles: float = 0.0
    """Marbles off the racing line, 0 to 1."""

    water_depth: float = 0.0
    """Standing water depth, m.  0 is dry."""

    temperature_offset: float = 0.0
    """Deviation of this segment's surface temperature from the circuit
    average, K.  Shaded and exposed sections differ by several degrees."""

    def reset(self) -> None:
        self.rubber = 0.0
        self.marbles = 0.0
        self.water_depth = 0.0
        self.temperature_offset = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "rubber": self.rubber,
            "marbles": self.marbles,
            "water_depth": self.water_depth,
            "temperature_offset": self.temperature_offset,
        }


class TrackConditions:
    """Per-segment surface condition for one session.

    Owned by the session, never by the track: two cars running different
    sessions on the same circuit share the immutable :class:`Track` and hold
    separate :class:`TrackConditions`.
    """

    __slots__ = ("_conditions", "_config", "_segments")

    def __init__(
        self,
        segments: Sequence[TrackSegment],
        config: TrackConditionsConfig | None = None,
    ) -> None:
        self._segments = segments
        self._config = config or TrackConditionsConfig()
        self._conditions = [SurfaceCondition() for _ in segments]

    # -- access --------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._conditions)

    def __getitem__(self, index: int) -> SurfaceCondition:
        return self._conditions[index]

    @property
    def config(self) -> TrackConditionsConfig:
        return self._config

    def reset(self) -> None:
        """Return every segment to green-track conditions."""
        for condition in self._conditions:
            condition.reset()

    # -- the model ------------------------------------------------------------

    def grip_multiplier(self, index: int, *, off_line: bool = False) -> float:
        """Condition-derived grip multiplier for segment ``index``.

        Three independent effects, each neutral at zero:

        * rubbering in raises grip towards ``rubber_grip_gain``;
        * marbles reduce it, but only ``off_line`` -- marbles collect *beside*
          the racing line, which is exactly why leaving it is expensive and why
          a car on it gains grip through a session rather than losing it;
        * a wet surface reduces it, saturating once the road is properly wet.

        The wet term is the *asphalt*, not the tyre.  Wet asphalt has a lower
        friction coefficient than dry asphalt whatever is running on it, and a
        damp track has nearly all of that penalty already.  What deeper water
        does is lift a tyre off the road, which depends entirely on the tread
        and is answered in :mod:`f1_race_engine.tyres.wet`.
        """
        condition = self._conditions[index]
        cfg = self._config
        multiplier = 1.0 + cfg.rubber_grip_gain * clamp(condition.rubber, 0.0, 1.0)
        if off_line:
            multiplier *= 1.0 - cfg.marble_grip_penalty * clamp(
                condition.marbles, 0.0, 1.0
            )
        if condition.water_depth > 0.0:
            wetness = min(condition.water_depth / cfg.reference_water_depth, 1.0)
            multiplier *= 1.0 - cfg.wet_surface_penalty * wetness
        return max(multiplier, cfg.min_grip_multiplier)

    def effective_grip(self, index: int, *, off_line: bool = False) -> float:
        """Static segment grip combined with the current condition."""
        return self._segments[index].surface_grip * self.grip_multiplier(
            index, off_line=off_line
        )

    def segment_gradient(self, index: int) -> float:
        """The gradient of the segment this condition belongs to.

        Exposed so the evolution model can drain water down the camber without
        having to be handed the track as well as the conditions."""
        return self._segments[index].gradient

    def is_wet(self, index: int) -> bool:
        return self._conditions[index].water_depth > 0.0

    @property
    def any_wet(self) -> bool:
        return any(c.water_depth > 0.0 for c in self._conditions)

    @property
    def mean_rubber(self) -> float:
        if not self._conditions:
            return 0.0
        return sum(c.rubber for c in self._conditions) / len(self._conditions)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mean_rubber": self.mean_rubber,
            "any_wet": self.any_wet,
            "segments": [c.to_dict() for c in self._conditions],
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"TrackConditions(segments={len(self._conditions)}, "
            f"mean_rubber={self.mean_rubber:.2f}, wet={self.any_wet})"
        )
