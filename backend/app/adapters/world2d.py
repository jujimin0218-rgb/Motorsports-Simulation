"""The 2D world, as something a browser can draw.

The engine builds the circuit as a place -- road, kerb, run-off, grass, gravel,
barriers, pit lane -- and this hands it over in metres.  The client scales it;
how big the drawing is is the drawing's business, which is the same rule the
plan-view adapter beside this one follows.

Built once per circuit and cached, because a circuit does not change during a
race and laying one out is sixty milliseconds of work.
"""

from __future__ import annotations

from typing import Any

from f1_race_engine.track.model import Track
from f1_race_engine.world import TrackWorld, world_for as _engine_world

__all__ = ["world_for", "world_payload"]

def world_for(track: Track) -> TrackWorld:
    """The laid-out circuit, built once per track.

    Deferred to the engine's own cache rather than kept here as well: the race
    running on the server needs the same world this hands to the browser, and
    laying one out solves three lines over a few thousand samples.  Two caches
    would mean doing that twice and, worse, being able to disagree about where
    the racing line is.
    """
    return _engine_world(track)


def world_payload(track: Track) -> dict[str, Any]:
    """Everything a renderer needs to draw the circuit, and nothing else.

    The surfaces come as filled rings in draw order -- what is furthest from
    the road first -- so a client can paint them in the order they arrive
    without knowing what any of them mean.
    """
    world = world_for(track)
    payload = world.to_dict()
    payload["bands"] = sorted(
        payload["bands"], key=lambda band: _DRAW_ORDER.get(band["surface"], 0)
    )
    return payload


#: What sits under what.  Grass and gravel are the ground the circuit is built
#: on, the run-off is laid over it, and the kerb is painted on the edge of the
#: road itself.
_DRAW_ORDER = {
    "grass": 0,
    "gravel": 1,
    "runoff": 2,
    "kerb": 3,
    "track": 4,
    "pit": 5,
}
