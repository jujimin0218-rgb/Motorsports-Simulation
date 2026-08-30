"""Racing: more than one car on the circuit at the same time.

A weekend: practice, a knockout qualifying session and a race, sharing one sky
and one track surface.  Positions and gaps come from real distance and time
(rule 28), the grid comes from qualifying and is covered from a standstill
(rule 27), stops are priced from the pit lane's own geometry (rule 32), and
strategy is computed from measured degradation rather than written down
(rule 31).

The cars still do not interact -- overtaking, defence and dirty air are
Phase 9.
"""

from __future__ import annotations

from .entry import PitStop, RaceEntry
from .session import Classification, LapCompleted, RaceResult, RaceSession
from .grid import GridSlot, Launch, launch_from_rest, reaction_time, starting_grid
from .pitlane import PitLane, PitLoss, pit_loss
from .planning import measure_degradation, measure_pit_loss, plan_race
from .qualifying import (
    DEFAULT_FORMAT,
    QualifyingLap,
    QualifyingResult,
    QualifyingSegment,
    QualifyingSession,
)
from .strategy import (
    RaceStrategy,
    StrategyPlan,
    Stint,
    compound_for_conditions,
    degradation_curve,
    plan_strategy,
)
from .timing import Gap, LapRecord, Position, TimingTower
from .weekend import Weekend, WeekendResult

__all__ = [
    "DEFAULT_FORMAT", "Classification", "Gap", "GridSlot", "LapCompleted",
    "LapRecord", "Launch", "PitLane", "PitLoss", "PitStop", "Position",
    "QualifyingLap", "QualifyingResult", "QualifyingSegment",
    "QualifyingSession", "RaceEntry", "RaceResult", "RaceSession",
    "RaceStrategy", "Stint", "StrategyPlan", "TimingTower", "Weekend",
    "WeekendResult", "compound_for_conditions", "degradation_curve",
    "launch_from_rest", "measure_degradation", "measure_pit_loss", "pit_loss",
    "plan_race", "plan_strategy", "reaction_time", "starting_grid",
]
