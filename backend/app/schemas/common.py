"""What the API sends and receives.

Thin on purpose.  The game's own objects already know how to serialise
themselves -- every one of them has ``to_dict`` -- so these describe the shape
of a request and the envelope of a response, and the payload inside is the
game's own.  Duplicating the whole domain as Pydantic models would mean two
definitions of a team that have to be kept in step, and the second one would
lose.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

__all__ = [
    "ErrorResponse",
    "InvestRequest",
    "LoadRequest",
    "NewGameRequest",
    "SaveRequest",
    "StrategyRequest",
]


class NewGameRequest(BaseModel):
    player_team: str = Field(description="Id of the team to take over.")
    seed: int | None = Field(
        default=None,
        description=(
            "Everything the game will ever draw comes from this.  Left out, "
            "one is taken from the clock and then stored, so the game is "
            "reproducible from its first moment rather than from its first save."
        ),
    )
    season: int | None = None
    name: str = ""


class SaveRequest(BaseModel):
    save_id: str | None = Field(
        default=None, description="Overwrite this save rather than creating one."
    )
    slot: str | None = Field(
        default=None, description="Write to a named slot, such as the autosave."
    )
    name: str | None = None


class LoadRequest(BaseModel):
    save_id: str | None = None
    slot: str | None = None


class StrategyRequest(BaseModel):
    """How a car intends to cover the distance.

    Every field is optional: a player who sets nothing gets the strategist's
    own plan, which is what an AI team gets too.
    """

    driver_id: str
    starting_compound: str | None = Field(
        default=None, description="S, M, H, I or W."
    )
    planned_stops: int | None = Field(default=None, ge=0, le=4)
    pace: str = Field(
        default="standard", description="push, standard or conserve."
    )
    aggression: str = Field(
        default="balanced", description="attack, balanced or defend."
    )


class InvestRequest(BaseModel):
    area: str = Field(description="One of the car's six development areas.")
    points: float = Field(gt=0.0, description="Research points to spend.")


class ErrorResponse(BaseModel):
    """The shape every failure arrives in, so a client can branch on ``code``
    rather than on a message."""

    code: str
    message: str
