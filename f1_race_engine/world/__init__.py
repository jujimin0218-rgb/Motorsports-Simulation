"""A race as a place: the plane the cars are actually on.

The engine's physics is a distance model and stays one.  This package is a
layer on top of it: the circuit laid out on the plane with everything either
side of the white line, cars as bodies with a size and a heading, and the
collisions that follow from two of them wanting the same piece of road.

Nothing here changes a lap time.  What it produces is where things are and
what touched what, which is the half of a race the distance model has never
had an opinion about.
"""

from .geometry import Vec2
from .track import Barrier, Surface, SurfaceBand, TrackWorld, build_world

__all__ = ["Barrier", "Surface", "SurfaceBand", "TrackWorld", "Vec2", "build_world"]
