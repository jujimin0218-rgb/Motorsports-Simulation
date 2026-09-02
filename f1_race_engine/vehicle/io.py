"""Loading and saving vehicle specifications.

Cars are data (project rules 43 and 45).  Storing a specification as JSON means
a car development model (Phase 5 onward) can write one out, a web backend can
serve one, and a calibration pass can adjust one -- all without touching code.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..core.errors import ConfigError
from .model import VehicleSpec

__all__ = [
    "BUILTIN_VEHICLE_DIR",
    "builtin_vehicle_names",
    "load_builtin_vehicle",
    "load_vehicle_spec",
    "save_vehicle_spec",
]

BUILTIN_VEHICLE_DIR = Path(__file__).resolve().parent.parent / "data" / "vehicles"


def builtin_vehicle_names() -> list[str]:
    """Names of the cars shipped with the engine."""
    if not BUILTIN_VEHICLE_DIR.is_dir():
        return []
    return sorted(p.stem for p in BUILTIN_VEHICLE_DIR.glob("*.json"))


def load_vehicle_spec(path: str | Path) -> VehicleSpec:
    """Load a vehicle specification from a JSON file."""
    file_path = Path(path)
    try:
        raw = json.loads(file_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"vehicle file not found: {file_path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{file_path} is not valid JSON: {exc}") from exc
    return VehicleSpec.from_dict(raw)


def load_builtin_vehicle(name: str) -> VehicleSpec:
    """Load a shipped car by file stem, e.g. ``"reference_2024"``."""
    path = BUILTIN_VEHICLE_DIR / f"{name}.json"
    if not path.is_file():
        available = ", ".join(builtin_vehicle_names()) or "(none)"
        raise ConfigError(f"unknown built-in vehicle {name!r}; available: {available}")
    return load_vehicle_spec(path)


def save_vehicle_spec(spec: VehicleSpec, path: str | Path) -> None:
    """Write a vehicle specification to a JSON file."""
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(json.dumps(spec.to_dict(), indent=2) + "\n", encoding="utf-8")
