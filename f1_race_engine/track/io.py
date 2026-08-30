"""Loading and saving track definitions.

Track data lives in JSON (project rules 43 and 45): it is the format the future
web backend will serve, the format a 3D client can consume, and the format that
imported real-circuit data will be written into.  What is stored is always the
*definition*, never the built segments -- segments are derived data, and storing
them would freeze one sampling resolution into the data files.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..core.config import SimulationConfig, TrackBuildConfig
from ..core.errors import TrackDataError
from .definitions import (
    BankingDefinition,
    CornerDefinition,
    CornerDirection,
    DrsDefinition,
    ElevationDefinition,
    KerbDefinition,
    LayoutElement,
    SectorDefinition,
    StraightDefinition,
    SurfaceDefinition,
    TrackDefaults,
    TrackDefinition,
    WidthDefinition,
)
from .model import Track

__all__ = [
    "BUILTIN_TRACK_DIR",
    "builtin_track_names",
    "definition_from_dict",
    "definition_to_dict",
    "load_builtin_definition",
    "load_track",
    "load_track_definition",
    "save_track_definition",
    "track_to_json",
]

#: Directory holding the circuits shipped with the engine.
BUILTIN_TRACK_DIR = Path(__file__).resolve().parent.parent / "data" / "tracks"


# ---------------------------------------------------------------------------
# Definitions
# ---------------------------------------------------------------------------


def _layout_element_from_dict(data: dict[str, Any], index: int) -> LayoutElement:
    kind = data.get("type")
    if kind == "straight":
        return StraightDefinition(
            length=float(data["length"]), name=data.get("name")
        )
    if kind == "corner":
        return CornerDefinition(
            radius=float(data["radius"]),
            angle=float(data["angle"]),
            direction=CornerDirection(data.get("direction", "left")),
            radius_end=(
                None if data.get("radius_end") is None else float(data["radius_end"])
            ),
            entry_transition=(
                None
                if data.get("entry_transition") is None
                else float(data["entry_transition"])
            ),
            exit_transition=(
                None
                if data.get("exit_transition") is None
                else float(data["exit_transition"])
            ),
            name=data.get("name"),
            corner_id=None if data.get("corner_id") is None else int(data["corner_id"]),
            banking=None if data.get("banking") is None else float(data["banking"]),
        )
    raise TrackDataError(
        f"layout element {index}: unknown type {kind!r} "
        f"(expected 'straight' or 'corner')"
    )


def definition_from_dict(data: dict[str, Any]) -> TrackDefinition:
    """Build a :class:`TrackDefinition` from plain data."""
    if not isinstance(data, dict):
        raise TrackDataError(f"track data must be an object, got {type(data).__name__}")
    try:
        name = data["name"]
        raw_layout = data["layout"]
    except KeyError as exc:
        raise TrackDataError(f"track data is missing the {exc.args[0]!r} key") from exc
    if not isinstance(raw_layout, list) or not raw_layout:
        raise TrackDataError(f"track {name!r}: 'layout' must be a non-empty list")

    layout = tuple(
        _layout_element_from_dict(element, index)
        for index, element in enumerate(raw_layout)
    )
    return TrackDefinition(
        name=name,
        layout=layout,
        defaults=TrackDefaults.from_dict(data.get("defaults", {})),
        elevation=ElevationDefinition.from_dict(data.get("elevation", {})),
        banking=BankingDefinition.from_dict(data.get("banking", {})),
        surface=SurfaceDefinition.from_dict(data.get("surface", {})),
        width=WidthDefinition.from_dict(data.get("width", {})),
        kerbs=KerbDefinition.from_dict(data.get("kerbs", {})),
        drs=DrsDefinition.from_dict(data.get("drs", {})),
        sectors=SectorDefinition.from_dict(data.get("sectors", {})),
        country=data.get("country"),
        metadata=dict(data.get("metadata", {})),
    )


def definition_to_dict(definition: TrackDefinition) -> dict[str, Any]:
    """Plain-data form of a track definition."""
    return definition.to_dict()


def load_track_definition(path: str | Path) -> TrackDefinition:
    """Load a track definition from a JSON file."""
    file_path = Path(path)
    try:
        raw = json.loads(file_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise TrackDataError(f"track file not found: {file_path}") from exc
    except json.JSONDecodeError as exc:
        raise TrackDataError(f"{file_path} is not valid JSON: {exc}") from exc
    return definition_from_dict(raw)


def save_track_definition(definition: TrackDefinition, path: str | Path) -> None:
    """Write a track definition to a JSON file."""
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(definition_to_dict(definition), indent=2)
    file_path.write_text(payload + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Built-in circuits
# ---------------------------------------------------------------------------


def builtin_track_names() -> list[str]:
    """Names of the circuits shipped with the engine."""
    if not BUILTIN_TRACK_DIR.is_dir():
        return []
    return sorted(p.stem for p in BUILTIN_TRACK_DIR.glob("*.json"))


def load_builtin_definition(name: str) -> TrackDefinition:
    """Load a shipped circuit definition by file stem, e.g. ``"monza"``."""
    path = BUILTIN_TRACK_DIR / f"{name}.json"
    if not path.is_file():
        available = ", ".join(builtin_track_names()) or "(none)"
        raise TrackDataError(f"unknown built-in track {name!r}; available: {available}")
    return load_track_definition(path)


def load_track(
    name_or_path: str | Path,
    config: TrackBuildConfig | SimulationConfig | None = None,
    *,
    validate: bool = True,
) -> Track:
    """Load and build a circuit, by built-in name or by path.

    With ``validate=True`` (the default) the built track is checked and any
    error raises, so a broken circuit cannot silently reach the physics.
    """
    from .builder import build_track  # local import: builder imports this module's types
    from .validation import validate_track

    if isinstance(name_or_path, Path) or str(name_or_path).endswith(".json"):
        definition = load_track_definition(name_or_path)
    else:
        definition = load_builtin_definition(str(name_or_path))

    track = build_track(definition, config)
    if validate:
        validation_config = (
            config.track_validation if isinstance(config, SimulationConfig) else None
        )
        validate_track(track, validation_config).raise_for_errors()
    return track


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def track_to_json(
    track: Track, *, include_segments: bool = False, indent: int | None = 2
) -> str:
    """Serialise a built track for an external consumer."""
    return json.dumps(track.to_dict(include_segments=include_segments), indent=indent)
