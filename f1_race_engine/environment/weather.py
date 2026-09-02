"""Weather that moves (project rule 30).

A race weekend's weather is not a setting.  It is a process: the air warms and
cools, the track lags behind it because asphalt has thermal mass, the wind
wanders, and showers arrive and pass without asking anyone.  A simulator that
takes "rain = 0.4" as an input can never produce the thing that makes a wet
race a wet race -- *not knowing whether it is going to rain*.

So this module models the process and lets the session read it:

* **air temperature** is an Ornstein-Uhlenbeck walk around the forecast mean:
  it wanders, and it is pulled back;
* **track temperature** chases a target (air, plus sun, minus rain) through a
  first-order lag, so a cloud cools the track long after it has gone;
* **rain** is a two-state process -- dry, or a shower -- with the shower's end
  a Poisson event, so showers have no fixed length: some pass in three minutes
  and some settle in for the afternoon;
* **intensity** relaxes towards the state's target, so rain arrives and clears
  over a couple of minutes rather than switching;
* **wind** wanders in both speed and direction.

Everything is drawn from one seeded stream, so the same seed gives the same
afternoon and a different seed gives a different one.  Nobody anywhere writes
down what the weather will do.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Any

from ..core.config import WeatherConfig
from ..core.errors import ConfigError
from ..core.interpolation import clamp
from ..core.rng import RngHub
from ..core.units import Celsius, Pascals, Seconds
from .conditions import AmbientConditions

__all__ = ["Forecast", "WeatherModel", "WeatherState"]


@dataclass(frozen=True, slots=True)
class Forecast:
    """What the meteorologists said, which is not what will happen."""

    air_temperature: Celsius = 24.0
    """Mean air temperature for the session."""

    cloud_cover: float = 0.3
    """0 (clear) to 1 (overcast).  Decides how much sun reaches the track."""

    rain_probability: float = 0.0
    """Chance that it rains at some point in an hour of running.

    Not a switch: it scales how often a shower starts.  A 30% forecast can give
    a dry session or a soaked one, and which you get depends on the seed."""

    wind_speed: float = 3.0
    wind_direction: float = 0.0
    pressure: Pascals = 101_325.0
    relative_humidity: float = 0.45

    def __post_init__(self) -> None:
        if not 0.0 <= self.cloud_cover <= 1.0:
            raise ConfigError("cloud_cover must lie in [0, 1]")
        if not 0.0 <= self.rain_probability <= 1.0:
            raise ConfigError("rain_probability must lie in [0, 1]")
        if self.wind_speed < 0.0:
            raise ConfigError("wind_speed must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        return {
            "air_temperature": self.air_temperature,
            "cloud_cover": self.cloud_cover,
            "rain_probability": self.rain_probability,
            "wind_speed": self.wind_speed,
            "wind_direction": self.wind_direction,
            "pressure": self.pressure,
            "relative_humidity": self.relative_humidity,
        }


@dataclass(frozen=True, slots=True)
class WeatherState:
    """The weather at one moment of a session."""

    elapsed: Seconds = 0.0
    air_temperature: Celsius = 24.0
    track_temperature: Celsius = 38.0
    rain_intensity: float = 0.0
    cloud_cover: float = 0.3
    wind_speed: float = 3.0
    wind_direction: float = 0.0
    pressure: Pascals = 101_325.0
    relative_humidity: float = 0.45
    raining: bool = False
    """Whether a shower is currently overhead.  Intensity lags this."""

    @property
    def is_wet(self) -> bool:
        return self.rain_intensity > 0.005

    @property
    def ambient(self) -> AmbientConditions:
        """The conditions the physics reads.

        A :class:`~f1_race_engine.environment.conditions.AmbientConditions` is
        immutable on purpose: a lap recorded at one moment keeps the weather it
        was actually run in.
        """
        return AmbientConditions(
            air_temperature=self.air_temperature,
            track_temperature=self.track_temperature,
            pressure=self.pressure,
            relative_humidity=self.relative_humidity,
            wind_speed=self.wind_speed,
            wind_direction=self.wind_direction,
            rain_intensity=self.rain_intensity,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "elapsed": self.elapsed,
            "air_temperature": self.air_temperature,
            "track_temperature": self.track_temperature,
            "rain_intensity": self.rain_intensity,
            "cloud_cover": self.cloud_cover,
            "wind_speed": self.wind_speed,
            "wind_direction": self.wind_direction,
            "raining": self.raining,
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        rain = f", rain {self.rain_intensity:.2f}" if self.is_wet else ""
        return (
            f"WeatherState(air {self.air_temperature:.1f}C, "
            f"track {self.track_temperature:.1f}C{rain})"
        )


class WeatherModel:
    """Advances the weather through a session."""

    __slots__ = ("forecast", "config", "_rng", "_state", "_target_intensity")

    def __init__(
        self,
        forecast: Forecast | None = None,
        rng: RngHub | None = None,
        *,
        config: WeatherConfig | None = None,
        seed: int = 0,
    ) -> None:
        self.forecast = forecast or Forecast()
        self.config = config or WeatherConfig()
        self._rng = rng or RngHub(seed)
        self._target_intensity = 0.0
        self._state = self._initial()

    # -- state ---------------------------------------------------------------

    def _initial(self) -> WeatherState:
        forecast = self.forecast
        track = forecast.air_temperature + self.config.solar_gain * (
            1.0 - forecast.cloud_cover
        )
        return WeatherState(
            elapsed=0.0,
            air_temperature=forecast.air_temperature,
            track_temperature=track,
            rain_intensity=0.0,
            cloud_cover=forecast.cloud_cover,
            wind_speed=forecast.wind_speed,
            wind_direction=forecast.wind_direction,
            pressure=forecast.pressure,
            relative_humidity=forecast.relative_humidity,
            raining=False,
        )

    @property
    def state(self) -> WeatherState:
        return self._state

    def reset(self) -> None:
        self._target_intensity = 0.0
        self._state = self._initial()

    # -- the process ---------------------------------------------------------

    def advance(self, duration: Seconds) -> WeatherState:
        """Move the weather forward by ``duration`` seconds.

        Stepped internally at the configured resolution so the answer does not
        depend on how often a caller happens to ask (rule 12, applied to time
        rather than distance).
        """
        if duration <= 0.0:
            return self._state
        step = self.config.step
        remaining = duration
        while remaining > 1e-9:
            dt = min(step, remaining)
            self._state = self._advance_one(self._state, dt)
            remaining -= dt
        return self._state

    def _advance_one(self, state: WeatherState, dt: Seconds) -> WeatherState:
        cfg = self.config
        forecast = self.forecast
        stream = self._rng.stream("weather", minute=int(state.elapsed // 60.0))

        raining, target = self._rain(state, dt, stream)
        intensity = _relax(
            state.rain_intensity, target, dt, cfg.intensity_relaxation
        )

        # Air temperature: an Ornstein-Uhlenbeck walk around the forecast, with
        # rain pulling the mean it is walking around downwards rather than
        # pushing the temperature itself -- so a long shower cools the session
        # by a bounded amount, and it comes back afterwards.
        air = _relax(
            state.air_temperature,
            forecast.air_temperature - cfg.rain_air_cooling * intensity,
            dt,
            cfg.temperature_relaxation,
        )
        air += stream.normal(0.0, cfg.temperature_volatility) * math.sqrt(
            dt / cfg.step
        )

        # Cloud follows the rain: it is overcast while a shower is overhead.
        cloud = _relax(
            state.cloud_cover,
            max(forecast.cloud_cover, 0.35 + 0.65 * intensity),
            dt,
            cfg.intensity_relaxation * 2.0,
        )

        # The track chases a target and gets there slowly.
        target_track = (
            air + cfg.solar_gain * (1.0 - cloud) - cfg.rain_track_cooling * intensity
        )
        track = _relax(state.track_temperature, target_track, dt, cfg.track_relaxation)

        wind = max(
            _relax(state.wind_speed, forecast.wind_speed, dt, cfg.wind_relaxation)
            + stream.normal(0.0, cfg.wind_volatility) * math.sqrt(dt / cfg.step),
            0.0,
        )
        direction = state.wind_direction + stream.normal(
            0.0, cfg.wind_direction_volatility
        ) * math.sqrt(dt / cfg.step)

        return replace(
            state,
            elapsed=state.elapsed + dt,
            air_temperature=clamp(air, -30.0, 60.0),
            track_temperature=clamp(track, -30.0, 85.0),
            rain_intensity=clamp(intensity, 0.0, 1.0),
            cloud_cover=clamp(cloud, 0.0, 1.0),
            wind_speed=wind,
            wind_direction=direction % math.tau,
            raining=raining,
        )

    def _rain(self, state: WeatherState, dt: Seconds, stream: Any) -> tuple[bool, float]:
        """Whether a shower is overhead, and how hard it is trying to rain.

        Two Poisson processes: one starts a shower and one ends it.  Neither
        knows the session length, so rain is not scheduled to arrive at a
        dramatic moment -- it either does or it does not.
        """
        cfg = self.config
        if state.raining:
            ending = 1.0 - math.exp(-dt / cfg.mean_shower_duration)
            if stream.chance(ending):
                return False, 0.0
            return True, self._target_intensity

        rate_per_hour = cfg.shower_onset_per_hour + self.forecast.rain_probability * 1.4
        starting = 1.0 - math.exp(-rate_per_hour * dt / 3600.0)
        if stream.chance(starting):
            # How hard it rains is drawn once, when the shower arrives.
            # How hard it rains is drawn once, when the shower arrives: mostly
            # light, occasionally torrential.
            self._target_intensity = clamp(
                0.12 - 0.42 * math.log(max(1.0 - stream.random(), 1e-9)), 0.05, 1.0
            )
            return True, self._target_intensity
        return False, 0.0

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"WeatherModel({self._state!r}, at {self._state.elapsed / 60:.0f} min)"


def _relax(value: float, target: float, dt: float, time_constant: float) -> float:
    """First-order lag: how a thing with thermal mass chases a target."""
    if time_constant <= 0.0:
        return target
    return target + (value - target) * math.exp(-dt / time_constant)
