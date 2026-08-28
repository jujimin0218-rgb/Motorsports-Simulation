"""Racing: more than one car on the circuit at the same time.

Phase 6 runs a field side by side without interaction -- overtaking, defence
and dirty air are Phase 9.  What it establishes is the bookkeeping racing needs:
independent per-car state, per-car randomness that cannot leak, and positions
and gaps computed from real distance and time (project rule 28).
"""

from __future__ import annotations

from .entry import RaceEntry
from .session import Classification, LapCompleted, RaceResult, RaceSession
from .timing import Gap, LapRecord, Position, TimingTower

__all__ = [
    "Classification", "Gap", "LapCompleted", "LapRecord", "Position",
    "RaceEntry", "RaceResult", "RaceSession", "TimingTower",
]
