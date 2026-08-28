"""A race weekend: one circuit, one afternoon, three sessions.

This is where the three systems meet, and the point of putting them together is
that none of them can be understood alone:

* the **weather** does not restart between sessions, so a Saturday shower is
  still draining when qualifying begins;
* the **track surface** carries over too, so every lap anybody runs in practice
  makes qualifying quicker for everybody -- and a shower washes that away;
* **qualifying** sets the grid, and the grid is a set of distances behind the
  line that the race has to cover from a standstill;
* **strategy** is decided from what the tyres actually did on this track in
  this condition, and abandoned the moment it starts raining.

One weather model and one track surface are shared by every session, which is
the whole of the wiring.  Everything else was already true.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from ..core.config import SimulationConfig
from ..core.errors import EntryError
from ..core.rng import RngHub
from ..environment.evolution import TrackEvolution
from ..environment.weather import Forecast, WeatherModel, WeatherState
from ..simulation.lap import LapSimulator
from ..track.model import Track
from ..track.surface import TrackConditions
from .entry import RaceEntry
from .pitlane import PitLane
from .qualifying import DEFAULT_FORMAT, QualifyingResult, QualifyingSegment, QualifyingSession
from .session import RaceResult, RaceSession
from .strategy import compound_for_conditions

__all__ = ["Weekend", "WeekendResult"]


@dataclass(frozen=True)
class WeekendResult:
    """Everything that happened, and the weather it happened in."""

    track_name: str
    qualifying: QualifyingResult | None
    race: RaceResult
    weather_log: tuple[WeatherState, ...] = field(repr=False, default=())
    practice_laps: int = 0

    @property
    def pole(self) -> int | None:
        return self.qualifying.pole if self.qualifying is not None else None

    @property
    def winner(self) -> int | None:
        champion = self.race.winner
        return champion.car_number if champion is not None else None

    @property
    def pole_converted(self) -> bool:
        return self.pole is not None and self.pole == self.winner

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "track": self.track_name,
            "practice_laps": self.practice_laps,
            "race": self.race.to_dict(),
            "weather": [state.to_dict() for state in self.weather_log],
        }
        if self.qualifying is not None:
            payload["qualifying"] = self.qualifying.to_dict()
        return payload

    def format(self, names: dict[int, str] | None = None) -> str:
        parts = []
        if self.qualifying is not None:
            parts.append(self.qualifying.format(names))
            parts.append("")
        parts.append(self.race.format())
        return "\n".join(parts)


class Weekend:
    """Runs practice, qualifying and a race on one shared circuit and sky."""

    __slots__ = (
        "track", "entries", "laps", "config", "rng", "weather", "conditions",
        "evolution", "pit_lane", "format", "practice_laps", "_log",
    )

    def __init__(
        self,
        track: Track,
        entries: Iterable[RaceEntry],
        *,
        laps: int,
        rng: RngHub | None = None,
        forecast: Forecast | None = None,
        config: SimulationConfig | None = None,
        pit_lane: PitLane | None = None,
        segments: Sequence[QualifyingSegment] = DEFAULT_FORMAT,
        practice_laps: int = 12,
    ) -> None:
        self.entries = tuple(entries)
        if not self.entries:
            raise EntryError("a weekend needs at least one entry")
        if laps < 1:
            raise EntryError("a race needs at least one lap")

        self.track = track
        self.laps = laps
        self.config = config or self.entries[0].vehicle.config
        self.rng = rng or RngHub(self.config.randomness.seed)
        self.weather = WeatherModel(
            forecast or Forecast(),
            self.rng.spawn("weather"),
            config=self.config.weather,
        )
        self.conditions = TrackConditions(
            track.segments, self.config.track_conditions
        )
        self.evolution = TrackEvolution(
            self.conditions, self.config.track_evolution, self.config.track_conditions
        )
        self.pit_lane = pit_lane or PitLane.for_track(track.length)
        self.format = tuple(segments)
        self.practice_laps = practice_laps
        self._log: list[WeatherState] = []

    # -- the weekend ---------------------------------------------------------

    def run(self, *, qualify: bool = True) -> WeekendResult:
        """Run the weekend and return everything that happened."""
        self._log = [self.weather.state]

        if self.practice_laps > 0:
            self._practice()

        result: QualifyingResult | None = None
        if qualify:
            result = self._qualify()
            for position, car in enumerate(result.order, start=1):
                for entry in self.entries:
                    if entry.car_number == car:
                        entry.grid_position = position

        race = self._race()
        return WeekendResult(
            track_name=self.track.name,
            qualifying=result,
            race=race,
            weather_log=tuple(self._log),
            practice_laps=self.practice_laps,
        )

    # -- the sessions --------------------------------------------------------

    def _practice(self) -> None:
        """Run the field for a while.

        Nothing is timed and nothing is reported.  The point is that the laps
        happened: rubber goes down, the weather moves on, and qualifying starts
        on the track practice left behind.
        """
        simulators = {
            entry.car_number: LapSimulator(
                self.track, entry.vehicle, entry.driver,
                rng=self.rng.spawn(f"practice.{entry.car_number}"),
                ambient=self.weather.state.ambient,
                conditions=self.conditions,
                config=self.config,
            )
            for entry in self.entries
        }
        for lap in range(1, self.practice_laps + 1):
            durations = []
            for entry in self.entries:
                water = self.evolution.mean_water_depth
                if entry.compounds:
                    entry.fit(compound_for_conditions(entry.compounds, water))
                result = simulators[entry.car_number].simulate(
                    lap=lap, fuel_mass=80.0, tyre_state=entry.tyres,
                    ers_state=entry.energy, effort=0.93, record_telemetry=False,
                )
                durations.append(result.lap_time)
            duration = sum(durations) / len(durations)
            state = self.weather.advance(duration)
            self.evolution.apply_weather(state, duration)
            self.evolution.run_laps(float(len(self.entries)))
            for simulator in simulators.values():
                simulator.set_conditions(
                    ambient=state.ambient, conditions=self.conditions
                )
            self._log.append(state)

    def _qualify(self) -> QualifyingResult:
        session = QualifyingSession(
            self.track,
            self.entries,
            segments=self.format,
            rng=self.rng.spawn("qualifying"),
            ambient=self.weather.state.ambient,
            conditions=self.conditions,
            config=self.config,
            weather=self.weather,
            evolution=self.evolution,
        )
        result = session.run()
        self._log.append(self.weather.state)
        return result

    def _race(self) -> RaceResult:
        water = self.evolution.mean_water_depth
        for entry in self.entries:
            if entry.compounds:
                entry.fit(compound_for_conditions(entry.compounds, water))
            if entry.strategy is not None:
                entry.strategy.compounds = entry.compounds
                entry.strategy.start_stint()
        session = RaceSession(
            self.track,
            self.entries,
            laps=self.laps,
            rng=self.rng.spawn("race"),
            ambient=self.weather.state.ambient,
            conditions=self.conditions,
            config=self.config,
            weather=self.weather,
            evolution=self.evolution,
            pit_lane=self.pit_lane,
            standing_start=True,
        )
        result = session.run()
        self._log.append(self.weather.state)
        return result

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"Weekend({self.track.name!r}, {len(self.entries)} cars, "
            f"{self.laps} laps)"
        )
