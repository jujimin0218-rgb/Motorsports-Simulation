"""Loading and saving drivers."""

from __future__ import annotations

import json
from pathlib import Path

from ..core.errors import ConfigError
from .model import Driver

__all__ = [
    "BUILTIN_DRIVER_DIR",
    "builtin_driver_names",
    "load_builtin_driver",
    "load_driver",
    "load_driver_lineup",
    "save_driver",
]

BUILTIN_DRIVER_DIR = Path(__file__).resolve().parent.parent / "data" / "drivers"


def builtin_driver_names() -> list[str]:
    """Names of the driver files shipped with the engine."""
    if not BUILTIN_DRIVER_DIR.is_dir():
        return []
    return sorted(p.stem for p in BUILTIN_DRIVER_DIR.glob("*.json"))


def load_driver(path: str | Path) -> Driver:
    """Load one driver from a JSON file."""
    file_path = Path(path)
    try:
        raw = json.loads(file_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"driver file not found: {file_path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{file_path} is not valid JSON: {exc}") from exc
    return Driver.from_dict(raw)


def load_builtin_driver(name: str) -> Driver:
    """Load a shipped driver by file stem."""
    path = BUILTIN_DRIVER_DIR / f"{name}.json"
    if not path.is_file():
        available = ", ".join(builtin_driver_names()) or "(none)"
        raise ConfigError(f"unknown built-in driver {name!r}; available: {available}")
    return load_driver(path)


def load_driver_lineup() -> list[Driver]:
    """Every shipped driver, ordered by file name."""
    return [load_builtin_driver(name) for name in builtin_driver_names()]


def save_driver(driver: Driver, path: str | Path) -> None:
    """Write a driver to a JSON file."""
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(json.dumps(driver.to_dict(), indent=2) + "\n", encoding="utf-8")
