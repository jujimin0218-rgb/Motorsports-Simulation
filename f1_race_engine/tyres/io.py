"""Loading and saving tyre compound sets."""

from __future__ import annotations

import json
from pathlib import Path

from ..core.errors import ConfigError
from .compound import CompoundSet

__all__ = [
    "BUILTIN_TYRE_DIR",
    "builtin_compound_sets",
    "load_builtin_compounds",
    "load_compound_set",
    "save_compound_set",
]

BUILTIN_TYRE_DIR = Path(__file__).resolve().parent.parent / "data" / "tyres"


def builtin_compound_sets() -> list[str]:
    """Names of the compound sets shipped with the engine."""
    if not BUILTIN_TYRE_DIR.is_dir():
        return []
    return sorted(p.stem for p in BUILTIN_TYRE_DIR.glob("*.json"))


def load_compound_set(path: str | Path) -> CompoundSet:
    """Load a compound set from a JSON file."""
    file_path = Path(path)
    try:
        raw = json.loads(file_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"tyre file not found: {file_path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{file_path} is not valid JSON: {exc}") from exc
    return CompoundSet.from_dict(raw)


def load_builtin_compounds(name: str = "reference_2024") -> CompoundSet:
    """Load a shipped compound set by file stem."""
    path = BUILTIN_TYRE_DIR / f"{name}.json"
    if not path.is_file():
        available = ", ".join(builtin_compound_sets()) or "(none)"
        raise ConfigError(f"unknown compound set {name!r}; available: {available}")
    return load_compound_set(path)


def save_compound_set(compounds: CompoundSet, path: str | Path) -> None:
    """Write a compound set to a JSON file."""
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(
        json.dumps(compounds.to_dict(), indent=2) + "\n", encoding="utf-8"
    )
