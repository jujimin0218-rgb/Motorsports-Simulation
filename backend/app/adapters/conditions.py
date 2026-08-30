"""The sky and the road surface, carried across a weekend.

The race engine has a full weather model and a track-evolution model, and the
game was not using either of them: every session ran at a fixed temperature on
a permanently green track.  This connects them.  Nothing here simulates
weather -- the engine's model does that, moving the sky on its own during a
session -- and nothing here decides how much rubber goes down.

The one thing this layer owns is **continuity**.  The engine's own
:class:`Weekend` runs practice, qualifying and a race in one call and shares
one sky between them; the game cannot, because the player acts between the
sessions.  So the conditions are rebuilt for each session and fast-forwarded
through the ones that already happened, from the round's own random stream.
That is deterministic in both directions that matter: qualifying run twice gets
the same weather, and a save reloaded and re-run gets the same weekend.

Fast-forwarding is done on the clock and the lap count rather than by
re-simulating -- a Friday is an hour of running and several hundred laps of
rubber, and re-driving all of it to find out what the sky did would cost
minutes to answer a question worth milliseconds.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from f1_race_engine.environment import (
    AmbientConditions,
    TrackEvolution,
    WeatherModel,
    WeatherState,
)
from f1_race_engine.track.model import Track
from f1_race_engine.track.surface import TrackConditions

if TYPE_CHECKING:  # pragma: no cover
    from ..game.state import GameState

__all__ = ["RoundConditions", "SESSIONS", "build_conditions", "forecast_for"]

#: The sessions of a weekend, in order.  A session is built by advancing
#: through everything before it.
SESSIONS: tuple[str, ...] = ("practice", "qualifying", "race")

#: How long each session lasts and how much running it puts on the track.
#: An hour apiece is what a real Friday and Saturday are, and the lap counts are
#: a field's worth of it -- enough rubber to matter, which is the point.
SESSION_SECONDS = 3600.0
PRACTICE_CAR_LAPS = 220.0
QUALIFYING_CAR_LAPS = 120.0

#: The wait between sessions.  The sky keeps moving overnight, so a wet Friday
#: does not guarantee a wet Sunday.
OVERNIGHT_SECONDS = 12.0 * 3600.0


@dataclass(slots=True)
class RoundConditions:
    """One weekend's sky and road, positioned at the start of a session."""

    session: str
    weather: WeatherModel
    conditions: TrackConditions
    evolution: TrackEvolution

    @property
    def state(self) -> WeatherState:
        return self.weather.state

    @property
    def ambient(self) -> AmbientConditions:
        return self.weather.state.ambient

    def summary(self) -> dict[str, Any]:
        """What a player would look at before deciding anything."""
        state = self.weather.state
        return {
            "session": self.session,
            "air_temperature": round(state.air_temperature, 1),
            "track_temperature": round(state.track_temperature, 1),
            "rain_intensity": round(state.rain_intensity, 4),
            "raining": bool(state.raining),
            "cloud_cover": round(state.cloud_cover, 3),
            "wind_speed": round(state.wind_speed, 2),
            "relative_humidity": round(state.relative_humidity, 3),
            "water_depth": round(self.evolution.mean_water_depth, 5),
            "wet_fraction": round(self.evolution.wet_fraction, 4),
            "rubber": round(
                sum(segment.rubber for segment in self.conditions)
                / max(1, len(list(self.conditions))),
                4,
            ),
        }


def forecast_for(state: GameState, round_number: int) -> Any:
    """The venue's climate for the time of year this round is held."""
    return state.circuit_for(round_number).forecast()


def build_conditions(
    state: GameState,
    round_number: int,
    track: Track,
    *,
    session: str = "race",
) -> RoundConditions:
    """The sky and the road as ``session`` is about to start.

    Built from the round's own random stream, so it is the same weekend
    whenever it is asked for -- which is what makes a reloaded save re-run the
    race it ran the first time rather than a similar one.
    """
    if session not in SESSIONS:
        raise ValueError(f"unknown session {session!r}")

    from f1_race_engine.core.config import default_config

    settings = default_config()
    weather = WeatherModel(
        forecast_for(state, round_number),
        state.round_rng(round_number).engine_hub("weather"),
        config=settings.weather,
    )
    conditions = TrackConditions(track.segments, settings.track_conditions)
    evolution = TrackEvolution(
        conditions, settings.track_evolution, settings.track_conditions
    )

    # Walk the weekend up to this session.  The sky moves on the clock and the
    # rubber goes down by the laps run, both of which the engine's own models
    # do -- this only says how much of each has happened.
    for done in SESSIONS[: SESSIONS.index(session)]:
        laps = PRACTICE_CAR_LAPS if done == "practice" else QUALIFYING_CAR_LAPS
        moved = weather.advance(SESSION_SECONDS)
        evolution.apply_weather(moved, SESSION_SECONDS)
        evolution.run_laps(laps)
        overnight = weather.advance(OVERNIGHT_SECONDS)
        evolution.apply_weather(overnight, OVERNIGHT_SECONDS)

    return RoundConditions(
        session=session,
        weather=weather,
        conditions=conditions,
        evolution=evolution,
    )
