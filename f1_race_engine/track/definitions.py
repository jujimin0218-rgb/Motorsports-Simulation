"""Track *definitions* -- the input to the builder.

Project rule 9 is emphatic on this point: a ``CornerDefinition`` is **not** a
corner.  It is a handful of parameters from which the builder generates the
real thing, a run of segments carrying continuous curvature.  Nobody types
segments by hand.

A definition has two parts:

* the **layout** -- an ordered list of straights and corners that establishes
  the arc-length axis of the lap;
* the **overlays** -- elevation, banking, surface, width, kerbs, DRS and
  sectors, each a function of distance applied on top of that axis.

Adding a new overlay in a later phase (wind exposure, drainage, pit-lane
geometry) means adding one definition class and one sampling call in the
builder.  Nothing already written has to change.

Everything that determines the circuit's *shape* lives here rather than in
:class:`~f1_race_engine.core.config.TrackBuildConfig`, so that changing the
sampling resolution can never change the track.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ..core.errors import TrackBuildError
from ..core.interpolation import clamp
from ..core.units import Degrees, Metres, deg_to_rad
from .drs import DrsZone
from .segment import KerbType, SurfaceType

__all__ = [
    "BankingDefinition",
    "CornerDefinition",
    "CornerDirection",
    "DrsDefinition",
    "ElevationDefinition",
    "KerbDefinition",
    "KerbRegion",
    "LayoutElement",
    "SectorDefinition",
    "StraightDefinition",
    "SurfaceDefinition",
    "SurfaceRegionDefinition",
    "TrackDefaults",
    "TrackDefinition",
    "WidthDefinition",
]


class CornerDirection(str, Enum):
    """Which way a corner turns."""

    LEFT = "left"
    RIGHT = "right"

    @property
    def sign(self) -> int:
        """``+1`` for left, ``-1`` for right -- the sign of the curvature."""
        return 1 if self is CornerDirection.LEFT else -1


# ---------------------------------------------------------------------------
# Geometry defaults
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TrackDefaults:
    """Per-circuit defaults used where a definition does not say otherwise.

    These belong to the track data, not to the simulation config: two circuits
    may reasonably have different transition characteristics or width, and a
    track's shape must not shift when the engine is re-tuned.
    """

    transition_factor: float = 0.55
    """Clothoid transition length as a multiple of corner radius.

    Real corners ease into and out of their radius over a transition spiral;
    turn-in is not a step change in curvature.  0.55 x radius gives about 14 m
    for a hairpin and 60 m for a fast sweeper, which is the right order for a
    modern circuit."""

    min_transition_length: Metres = 4.0
    """Floor on a transition length, m."""

    max_transition_fraction: float = 0.45
    """Cap on each transition as a fraction of the corner's pure-arc length, so
    every corner keeps a constant-radius section in the middle."""

    track_width: Metres = 13.0
    """Default usable track width, m."""

    surface_type: SurfaceType = SurfaceType.ASPHALT
    surface_grip: float = 1.0
    """Baseline static grip multiplier (1.0 = reference asphalt)."""

    roughness: float = 0.5
    """Baseline surface roughness, 0 (smooth) to 1 (abrasive)."""

    kerb: KerbType = KerbType.NONE

    def __post_init__(self) -> None:
        if self.transition_factor < 0.0:
            raise TrackBuildError("transition_factor must be non-negative")
        if self.min_transition_length < 0.0:
            raise TrackBuildError("min_transition_length must be non-negative")
        if not 0.0 <= self.max_transition_fraction <= 0.5:
            raise TrackBuildError("max_transition_fraction must lie in [0, 0.5]")
        if self.track_width <= 0.0:
            raise TrackBuildError("track_width must be positive")
        if self.surface_grip <= 0.0:
            raise TrackBuildError("surface_grip must be positive")
        if not 0.0 <= self.roughness <= 1.0:
            raise TrackBuildError("roughness must lie in [0, 1]")

    def to_dict(self) -> dict[str, Any]:
        return {
            "transition_factor": self.transition_factor,
            "min_transition_length": self.min_transition_length,
            "max_transition_fraction": self.max_transition_fraction,
            "track_width": self.track_width,
            "surface_type": self.surface_type.value,
            "surface_grip": self.surface_grip,
            "roughness": self.roughness,
            "kerb": self.kerb.value,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TrackDefaults:
        payload = dict(data)
        if "surface_type" in payload:
            payload["surface_type"] = SurfaceType(payload["surface_type"])
        if "kerb" in payload:
            payload["kerb"] = KerbType(payload["kerb"])
        return cls(**payload)


# ---------------------------------------------------------------------------
# Layout elements
# ---------------------------------------------------------------------------


class LayoutElement:
    """Base class for the ordered elements that make up the lap."""

    name: str | None

    def arc_length(self, defaults: TrackDefaults) -> Metres:
        """Length this element contributes to the lap, m."""
        raise NotImplementedError

    def turn_angle(self, defaults: TrackDefaults) -> float:
        """Signed heading change this element produces, radians."""
        raise NotImplementedError

    def to_dict(self) -> dict[str, Any]:
        raise NotImplementedError


@dataclass(frozen=True)
class StraightDefinition(LayoutElement):
    """A straight of the given length."""

    length: Metres
    name: str | None = None

    def __post_init__(self) -> None:
        if self.length <= 0.0:
            raise TrackBuildError(
                f"straight {self.name or ''} must have positive length, "
                f"got {self.length}"
            )

    def arc_length(self, defaults: TrackDefaults) -> Metres:
        return self.length

    def turn_angle(self, defaults: TrackDefaults) -> float:
        return 0.0

    def to_dict(self) -> dict[str, Any]:
        return {"type": "straight", "length": self.length, "name": self.name}


@dataclass(frozen=True)
class CornerDefinition(LayoutElement):
    """Parameters from which the builder generates a corner.

    The generated corner is an entry transition (curvature ramping from 0 to
    ``1/radius``), an arc, and an exit transition back to zero.  The
    transitions turn the car as well, so the arc is shortened to keep the total
    turn angle exactly equal to :attr:`angle`.

    Set :attr:`radius_end` and the arc becomes a curvature ramp rather than a
    constant, which is how a real corner that tightens or opens out is
    described.  It is not a cosmetic detail: a decreasing-radius corner has to
    be braked for its *exit*, so it is slower than its entry radius suggests,
    and one that opens out can be got on the power in early.  Modelled as two
    separate corners instead, the car would be allowed to accelerate through
    the join.
    """

    radius: Metres
    angle: Degrees
    direction: CornerDirection = CornerDirection.LEFT
    radius_end: Metres | None = None
    """Radius at the end of the arc, m.  ``None`` keeps it constant."""

    entry_transition: Metres | None = None
    exit_transition: Metres | None = None
    name: str | None = None
    corner_id: int | None = None
    banking: Degrees | None = None
    """Optional banking through this corner, degrees, signed like curvature.
    A convenience over a separate :class:`BankingDefinition` entry."""

    def __post_init__(self) -> None:
        if self.radius <= 0.0:
            raise TrackBuildError(
                f"corner {self.label} must have a positive radius, got {self.radius}"
            )
        if self.radius_end is not None and self.radius_end <= 0.0:
            raise TrackBuildError(
                f"corner {self.label} must have a positive radius_end, "
                f"got {self.radius_end}"
            )
        if not 0.0 < self.angle <= 360.0:
            raise TrackBuildError(
                f"corner {self.label} angle must lie in (0, 360] degrees, "
                f"got {self.angle}"
            )
        for value, field_name in (
            (self.entry_transition, "entry_transition"),
            (self.exit_transition, "exit_transition"),
        ):
            if value is not None and value < 0.0:
                raise TrackBuildError(
                    f"corner {self.label} {field_name} must be non-negative"
                )

    @property
    def label(self) -> str:
        return self.name or (f"T{self.corner_id}" if self.corner_id is not None else "?")

    @property
    def angle_rad(self) -> float:
        """Unsigned turn angle, radians."""
        return deg_to_rad(self.angle)

    @property
    def curvature(self) -> float:
        """Signed curvature at the start of the arc, 1/m."""
        return self.direction.sign / self.radius

    @property
    def exit_radius(self) -> Metres:
        """Radius at the end of the arc, m; equal to :attr:`radius` by default."""
        return self.radius if self.radius_end is None else self.radius_end

    @property
    def curvature_end(self) -> float:
        """Signed curvature at the end of the arc, 1/m."""
        return self.direction.sign / self.exit_radius

    @property
    def is_constant_radius(self) -> bool:
        """Whether the arc holds one radius all the way through."""
        return self.radius_end is None or self.radius_end == self.radius

    @property
    def mean_curvature_magnitude(self) -> float:
        """Average unsigned curvature of the arc, 1/m.

        Curvature varies linearly along the arc, so its mean is the average of
        the ends -- and the heading a ramp turns is that mean times its length.
        """
        return 0.5 * (1.0 / self.radius + 1.0 / self.exit_radius)

    @property
    def tightest_radius(self) -> Metres:
        """Smallest radius reached inside the corner, m."""
        return min(self.radius, self.exit_radius)

    def pure_arc_length(self) -> Metres:
        """Length of the corner if it had no transitions, m."""
        return self.angle_rad / self.mean_curvature_magnitude

    def transitions(self, defaults: TrackDefaults) -> tuple[Metres, Metres]:
        """Resolved ``(entry, exit)`` transition lengths, m.

        A requested transition is capped at
        ``max_transition_fraction * pure_arc_length`` so the corner always
        retains a constant-radius section.
        """
        pure = self.pure_arc_length()
        cap = defaults.max_transition_fraction * pure

        def resolve(explicit: Metres | None, radius: Metres) -> Metres:
            if explicit is not None:
                return clamp(explicit, 0.0, cap)
            nominal = max(
                defaults.transition_factor * radius,
                defaults.min_transition_length,
            )
            return clamp(nominal, 0.0, cap)

        # Each transition is sized by the radius it joins: the entry ramps up
        # to the entry radius and the exit ramps down from the exit one.
        return (
            resolve(self.entry_transition, self.radius),
            resolve(self.exit_transition, self.exit_radius),
        )

    def arc_length(self, defaults: TrackDefaults) -> Metres:
        """Total length of the generated corner, m."""
        entry, exit_ = self.transitions(defaults)
        return entry + self.constant_arc_length(defaults) + exit_

    def constant_arc_length(self, defaults: TrackDefaults) -> Metres:
        """Length of the arc between the two transitions, m.

        Curvature is linear in distance everywhere in the corner, so each part
        turns the car by its mean curvature times its length::

            angle = k_entry * Le / 2 + (k_entry + k_exit) / 2 * La
                    + k_exit * Lx / 2

        Solving for ``La`` keeps the total turn exactly equal to the requested
        angle whatever the transitions cost.  With one radius throughout this
        is the familiar ``pure - (Le + Lx) / 2``.
        """
        entry, exit_ = self.transitions(defaults)
        turned_by_transitions = 0.5 * (
            entry / self.radius + exit_ / self.exit_radius
        )
        return (self.angle_rad - turned_by_transitions) / self.mean_curvature_magnitude

    def turn_angle(self, defaults: TrackDefaults) -> float:
        return self.direction.sign * self.angle_rad

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "type": "corner",
            "radius": self.radius,
            "angle": self.angle,
            "direction": self.direction.value,
            "name": self.name,
            "corner_id": self.corner_id,
        }
        if self.radius_end is not None:
            payload["radius_end"] = self.radius_end
        if self.entry_transition is not None:
            payload["entry_transition"] = self.entry_transition
        if self.exit_transition is not None:
            payload["exit_transition"] = self.exit_transition
        if self.banking is not None:
            payload["banking"] = self.banking
        return payload


# ---------------------------------------------------------------------------
# Overlay definitions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ElevationDefinition:
    """Elevation control points, ``(distance_m, elevation_m)``."""

    control_points: tuple[tuple[float, float], ...] = ()
    method: str = "monotone_cubic"

    def to_dict(self) -> dict[str, Any]:
        return {
            "control_points": [list(p) for p in self.control_points],
            "method": self.method,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ElevationDefinition:
        return cls(
            control_points=tuple(
                (float(p[0]), float(p[1])) for p in data.get("control_points", ())
            ),
            method=data.get("method", "monotone_cubic"),
        )


@dataclass(frozen=True)
class BankingDefinition:
    """Banking control points, ``(distance_m, banking_degrees)``."""

    control_points: tuple[tuple[float, float], ...] = ()
    method: str = "monotone_cubic"

    def to_dict(self) -> dict[str, Any]:
        return {
            "control_points": [list(p) for p in self.control_points],
            "method": self.method,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BankingDefinition:
        return cls(
            control_points=tuple(
                (float(p[0]), float(p[1])) for p in data.get("control_points", ())
            ),
            method=data.get("method", "monotone_cubic"),
        )


@dataclass(frozen=True)
class SurfaceRegionDefinition:
    """A stretch of track with non-default surface properties."""

    start: Metres
    end: Metres
    surface_type: SurfaceType = SurfaceType.ASPHALT
    grip: float | None = None
    roughness: float | None = None
    name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "start": self.start,
            "end": self.end,
            "surface_type": self.surface_type.value,
            "name": self.name,
        }
        if self.grip is not None:
            payload["grip"] = self.grip
        if self.roughness is not None:
            payload["roughness"] = self.roughness
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SurfaceRegionDefinition:
        return cls(
            start=float(data["start"]),
            end=float(data["end"]),
            surface_type=SurfaceType(data.get("surface_type", "asphalt")),
            grip=None if data.get("grip") is None else float(data["grip"]),
            roughness=(
                None if data.get("roughness") is None else float(data["roughness"])
            ),
            name=data.get("name"),
        )


@dataclass(frozen=True)
class SurfaceDefinition:
    """Static surface properties across the lap."""

    regions: tuple[SurfaceRegionDefinition, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"regions": [r.to_dict() for r in self.regions]}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SurfaceDefinition:
        return cls(
            regions=tuple(
                SurfaceRegionDefinition.from_dict(r) for r in data.get("regions", ())
            )
        )


@dataclass(frozen=True)
class WidthDefinition:
    """Track width control points, ``(distance_m, width_m)``."""

    control_points: tuple[tuple[float, float], ...] = ()
    method: str = "linear"

    def to_dict(self) -> dict[str, Any]:
        return {
            "control_points": [list(p) for p in self.control_points],
            "method": self.method,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WidthDefinition:
        return cls(
            control_points=tuple(
                (float(p[0]), float(p[1])) for p in data.get("control_points", ())
            ),
            method=data.get("method", "linear"),
        )


@dataclass(frozen=True)
class KerbRegion:
    """Kerbing over a stretch of track."""

    start: Metres
    end: Metres
    kerb: KerbType = KerbType.MEDIUM

    def to_dict(self) -> dict[str, Any]:
        return {"start": self.start, "end": self.end, "kerb": self.kerb.value}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> KerbRegion:
        return cls(
            start=float(data["start"]),
            end=float(data["end"]),
            kerb=KerbType(data.get("kerb", "medium")),
        )


@dataclass(frozen=True)
class KerbDefinition:
    """Where kerbs are available."""

    regions: tuple[KerbRegion, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"regions": [r.to_dict() for r in self.regions]}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> KerbDefinition:
        return cls(regions=tuple(KerbRegion.from_dict(r) for r in data.get("regions", ())))


@dataclass(frozen=True)
class DrsDefinition:
    """DRS zones, as ``(detection, activation_start, activation_end)`` metres."""

    zones: tuple[DrsZone, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"zones": [z.to_dict() for z in self.zones]}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DrsDefinition:
        zones = []
        for index, raw in enumerate(data.get("zones", ())):
            zones.append(
                DrsZone(
                    index=int(raw.get("index", index)),
                    detection_distance=float(raw["detection_distance"]),
                    activation_start=float(raw["activation_start"]),
                    activation_end=float(raw["activation_end"]),
                    name=raw.get("name"),
                    lap_length=(
                        None if raw.get("lap_length") is None else float(raw["lap_length"])
                    ),
                )
            )
        return cls(zones=tuple(zones))


@dataclass(frozen=True)
class SectorDefinition:
    """Timing sector boundaries, as distances from the start/finish line.

    Two boundaries give the usual three sectors.  The list must be strictly
    increasing and lie strictly inside the lap.
    """

    boundaries: tuple[float, ...] = ()

    @property
    def sector_count(self) -> int:
        return len(self.boundaries) + 1

    def sector_of(self, distance: Metres) -> int:
        """1-based sector index containing ``distance``."""
        sector = 1
        for boundary in self.boundaries:
            if distance >= boundary:
                sector += 1
            else:
                break
        return sector

    def to_dict(self) -> dict[str, Any]:
        return {"boundaries": list(self.boundaries)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SectorDefinition:
        return cls(boundaries=tuple(float(b) for b in data.get("boundaries", ())))


# ---------------------------------------------------------------------------
# The complete definition
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TrackDefinition:
    """Everything needed to build one circuit."""

    name: str
    layout: tuple[LayoutElement, ...]
    defaults: TrackDefaults = field(default_factory=TrackDefaults)
    elevation: ElevationDefinition = field(default_factory=ElevationDefinition)
    banking: BankingDefinition = field(default_factory=BankingDefinition)
    surface: SurfaceDefinition = field(default_factory=SurfaceDefinition)
    width: WidthDefinition = field(default_factory=WidthDefinition)
    kerbs: KerbDefinition = field(default_factory=KerbDefinition)
    drs: DrsDefinition = field(default_factory=DrsDefinition)
    sectors: SectorDefinition = field(default_factory=SectorDefinition)
    country: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.layout:
            raise TrackBuildError(f"track {self.name!r} has an empty layout")

    # -- derived quantities --------------------------------------------------

    @property
    def lap_length(self) -> Metres:
        """Total lap length implied by the layout, m.

        Depends only on the definition -- never on the build configuration --
        so changing the sampling resolution cannot change the circuit.
        """
        return math.fsum(element.arc_length(self.defaults) for element in self.layout)

    @property
    def total_turn_angle(self) -> float:
        """Signed total heading change over the lap, radians."""
        return math.fsum(element.turn_angle(self.defaults) for element in self.layout)

    @property
    def corners(self) -> tuple[CornerDefinition, ...]:
        return tuple(e for e in self.layout if isinstance(e, CornerDefinition))

    @property
    def straights(self) -> tuple[StraightDefinition, ...]:
        return tuple(e for e in self.layout if isinstance(e, StraightDefinition))

    @property
    def corner_count(self) -> int:
        return len(self.corners)

    def element_distances(self) -> list[tuple[float, float, LayoutElement]]:
        """``(start, end, element)`` for every layout element."""
        spans: list[tuple[float, float, LayoutElement]] = []
        cursor = 0.0
        for element in self.layout:
            length = element.arc_length(self.defaults)
            spans.append((cursor, cursor + length, element))
            cursor += length
        return spans

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "country": self.country,
            "defaults": self.defaults.to_dict(),
            "layout": [element.to_dict() for element in self.layout],
            "elevation": self.elevation.to_dict(),
            "banking": self.banking.to_dict(),
            "surface": self.surface.to_dict(),
            "width": self.width.to_dict(),
            "kerbs": self.kerbs.to_dict(),
            "drs": self.drs.to_dict(),
            "sectors": self.sectors.to_dict(),
            "metadata": dict(self.metadata),
        }
