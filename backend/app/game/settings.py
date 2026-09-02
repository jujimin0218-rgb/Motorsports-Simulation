"""The knobs a player sets when they start a game.

Two of them, and both exist for a reason the measurements forced.

**Race distance.**  The engine simulates every car on every lap of every race,
which is what makes its results worth having and also what makes them
expensive: a full 57-lap grand prix with twenty cars is about ten minutes of
work, and a full season is the better part of five hours.  So a season can be
run at a fraction of the distance, the way every game in this genre offers.  It
is not an approximation -- a 25% race is fourteen laps genuinely simulated, with
real fuel, real tyre wear and real pit stops.  It is a shorter race.

**Difficulty.**  What the AI teams know and how well they spend, and nothing
else.  The AI runs the same simulation on the same information the player has;
raising the difficulty makes it decide better, never makes its cars faster
(project rule 27).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from .errors import UnknownEntity

__all__ = ["Difficulty", "GameSettings", "RACE_DISTANCES"]

#: The fractions a season can be run at, and the minimum number of laps a race
#: is allowed to be whatever the fraction says.  Five laps is where a pit stop
#: and a tyre change still mean something.
RACE_DISTANCES: tuple[float, ...] = (0.25, 0.35, 0.50, 0.75, 1.00)
MINIMUM_LAPS = 5


class Difficulty(str, Enum):
    EASY = "easy"
    NORMAL = "normal"
    HARD = "hard"

    @property
    def ai_quality(self) -> float:
        """How well the AI spends what it has, 0 to 1.

        Never a bonus to its cars.  An AI on easy invests badly and reacts
        late; on hard it does what a good team would do with the same money.
        """
        return {"easy": 0.55, "normal": 0.80, "hard": 1.00}[self.value]


@dataclass(slots=True)
class GameSettings:
    """How this game is being played."""

    race_distance: float = 0.50
    difficulty: Difficulty = Difficulty.NORMAL
    hazards: bool = True
    """Whether failures, contact and safety cars happen.  On, normally; off is
    for testing a strategy against a clean race."""

    def __post_init__(self) -> None:
        if not 0.0 < self.race_distance <= 1.0:
            raise UnknownEntity(
                f"race distance must be a fraction of a full grand prix, "
                f"got {self.race_distance}"
            )

    def laps_for(self, full_distance_laps: int) -> int:
        """How many laps a race is actually run over."""
        return max(MINIMUM_LAPS, round(full_distance_laps * self.race_distance))

    def to_dict(self) -> dict[str, Any]:
        return {
            "race_distance": self.race_distance,
            "difficulty": self.difficulty.value,
            "hazards": self.hazards,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GameSettings:
        return cls(
            race_distance=float(data.get("race_distance", 0.50)),
            difficulty=Difficulty(data.get("difficulty", "normal")),
            hazards=bool(data.get("hazards", True)),
        )
