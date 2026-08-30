"""What the API sends and receives.

Thin on purpose.  The game's own objects already know how to serialise
themselves -- every one of them has ``to_dict`` -- so these describe the shape
of a request and the envelope of a response, and the payload inside is the
game's own.  Duplicating the whole domain as Pydantic models would mean two
definitions of a team that have to be kept in step, and the second one would
lose.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = [
    "ContractOfferRequest",
    "ErrorResponse",
    "FacilityRequest",
    "InvestRequest",
    "LoadRequest",
    "NewGameRequest",
    "SaveRequest",
    "SettingsRequest",
    "SponsorRequest",
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
    rounds: int | None = Field(
        default=None,
        description=(
            "Cut the season short at this many races.  A full season is "
            "twenty-two; a shorter one is the same grid over fewer rounds."
        ),
    )
    race_distance: float | None = Field(
        default=None,
        gt=0.0,
        le=1.0,
        description=(
            "Fraction of a full grand prix each race is run over.  The engine "
            "simulates every lap it is given, so this is a shorter race and "
            "not a faster approximation of a long one."
        ),
    )


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
    rushed: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description=(
            "Shorten the project.  Half the time costs half again the money "
            "and a materially worse chance of the part working."
        ),
    )


class FacilityRequest(BaseModel):
    facility: str = Field(description="One of the six departments.")


class ContractOfferRequest(BaseModel):
    driver_id: str
    salary: float = Field(gt=0.0, description="Millions per season.")
    seasons: int = Field(default=2, ge=1, le=5)
    signing_bonus: float = Field(default=0.0, ge=0.0)
    performance_bonus: float = Field(default=0.0, ge=0.0)
    seat: int | None = Field(
        default=None,
        description="Which car to put them in.  Required when both seats are full.",
    )


class SponsorRequest(BaseModel):
    sponsor_id: str


class SettingsRequest(BaseModel):
    """How the game is played.  Every field is optional; what is left out is
    left alone."""

    race_distance: float | None = Field(
        default=None,
        gt=0.0,
        le=1.0,
        description=(
            "The fraction of a full grand prix a race is run over.  Not an "
            "approximation -- a quarter-distance race is a quarter of the laps, "
            "genuinely simulated."
        ),
    )
    difficulty: str | None = Field(
        default=None, description="easy, normal or hard.  Changes how well the AI decides."
    )
    hazards: bool | None = Field(
        default=None, description="Whether failures, contact and safety cars happen."
    )


class ErrorResponse(BaseModel):
    """The shape every failure arrives in, so a client can branch on ``code``
    rather than on a message."""

    code: str
    message: str
