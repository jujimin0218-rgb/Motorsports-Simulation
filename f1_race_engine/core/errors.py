"""Exception hierarchy for the race engine.

Every error raised by the engine derives from :class:`F1EngineError` so that
embedding applications (CLI, FastAPI service, 3D client bridge) can catch
engine failures without catching unrelated exceptions.
"""

from __future__ import annotations


class F1EngineError(Exception):
    """Base class for all engine errors."""


class ConfigError(F1EngineError):
    """Raised when configuration data is malformed or out of range."""


class UnitError(F1EngineError):
    """Raised when a unit conversion receives an impossible value."""


class ValidationError(F1EngineError):
    """Base class for validation failures across every system.

    Carries the report so a caller can inspect the findings rather than parse
    the message.
    """

    def __init__(self, message: str, report: object | None = None) -> None:
        super().__init__(message)
        self.report = report


class TrackError(F1EngineError):
    """Base class for track-related failures."""


class TrackBuildError(TrackError):
    """Raised when a track definition cannot be turned into a track."""


class TrackDataError(TrackError):
    """Raised when track data on disk is malformed."""


class TrackValidationError(ValidationError, TrackError):
    """Raised when a built track fails validation checks."""


class PhysicsValidationError(ValidationError):
    """Raised when a vehicle or physics model fails its sanity checks."""
