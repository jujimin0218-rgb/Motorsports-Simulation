"""What the game refuses to do, and why.

Every one of these carries a stable ``code``.  The API turns the code into an
HTTP status and hands the message to the player, so the same failure reads the
same way whether it happened in a test, in a service call or on screen.
"""

from __future__ import annotations

__all__ = [
    "ContractNotAvailable",
    "GameError",
    "InsufficientBudget",
    "InvalidDriver",
    "InvalidGamePhase",
    "InvalidStrategy",
    "RaceAlreadyCompleted",
    "SaveNotFound",
    "UnknownEntity",
]


class GameError(Exception):
    """Base class.  Never raised directly."""

    code = "GameError"
    status = 400


class InvalidGamePhase(GameError):
    """The action is real but this is not the moment for it.

    Checked in the service layer rather than the UI: hiding a button is a
    convenience for the player, not a rule the game enforces.
    """

    code = "InvalidGamePhase"
    status = 409


class InsufficientBudget(GameError):
    code = "InsufficientBudget"
    status = 402


class ContractNotAvailable(GameError):
    code = "ContractNotAvailable"
    status = 409


class InvalidDriver(GameError):
    code = "InvalidDriver"
    status = 404


class InvalidStrategy(GameError):
    code = "InvalidStrategy"
    status = 422


class RaceAlreadyCompleted(GameError):
    code = "RaceAlreadyCompleted"
    status = 409


class SaveNotFound(GameError):
    code = "SaveNotFound"
    status = 404


class UnknownEntity(GameError):
    """A team, track or engine id that is not in the data files."""

    code = "UnknownEntity"
    status = 404
