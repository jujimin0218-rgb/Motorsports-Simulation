"""A car as something that takes up room.

The distance model treats a car as a point that is so far round the lap.  On
the plane it is a rectangle five and a half metres long and two wide, pointing
somewhere, and two of those cannot be in the same place.  That is the whole of
what this adds.

Deliberately not a vehicle dynamics model.  Where the car goes is still decided
by the engine's own physics; this carries where that put it, which way it is
facing, and how fast it is going, so that a contact can be worked out and paid
for.  Steering is here because a heading that changes needs a rate, not because
anything solves a bicycle model with it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from .geometry import Vec2

__all__ = ["CarBody", "CAR_LENGTH", "CAR_WIDTH"]

#: A modern Formula 1 car, m.  The same numbers the race's own overtaking model
#: uses for a car length and a car width, so "alongside" means one thing.
CAR_LENGTH = 5.6
CAR_WIDTH = 2.0


@dataclass(slots=True)
class CarBody:
    """One car, on the plane."""

    car_number: int
    position: Vec2
    heading: float
    """Radians, measured the way the circuit's own heading is."""

    speed: float = 0.0
    """Along the heading, m/s.  The engine decides it; this carries it."""

    steering: float = 0.0
    """Radians per second of heading change being asked for."""

    damage: float = 0.0
    """0 is a clean car, 1 is one that is not going anywhere.

    Accumulated from contacts, and never healed: a race is not long enough."""

    length: float = CAR_LENGTH
    width: float = CAR_WIDTH
    on_track: bool = True
    _contacts: int = field(default=0, repr=False)

    @property
    def half_length(self) -> float:
        return self.length * 0.5

    @property
    def half_width(self) -> float:
        return self.width * 0.5

    @property
    def forward(self) -> Vec2:
        return Vec2(math.cos(self.heading), math.sin(self.heading))

    @property
    def velocity(self) -> Vec2:
        return self.forward * self.speed

    @property
    def contacts(self) -> int:
        """How many times this car has hit something."""
        return self._contacts

    def corners(self) -> tuple[Vec2, Vec2, Vec2, Vec2]:
        """The four corners of the car, anticlockwise from the front left.

        This is the collision shape.  A rectangle rather than a polygon of the
        real bodywork: the difference is centimetres and the cost is every
        contact test in the race.
        """
        along = self.forward * self.half_length
        across = self.forward.left * self.half_width
        return (
            self.position + along + across,
            self.position - along + across,
            self.position - along - across,
            self.position + along - across,
        )

    def axes(self) -> tuple[Vec2, Vec2]:
        """The two directions a rectangle can be separated along."""
        return (self.forward, self.forward.left)

    def project(self, axis: Vec2) -> tuple[float, float]:
        """How far this car reaches along an axis, as ``(low, high)``."""
        centre = self.position.dot(axis)
        reach = abs(self.forward.dot(axis)) * self.half_length + abs(
            self.forward.left.dot(axis)
        ) * self.half_width
        return centre - reach, centre + reach

    def hurt(self, amount: float) -> None:
        """Take damage from a contact, and count it."""
        self.damage = min(1.0, self.damage + amount)
        self._contacts += 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "car_number": self.car_number,
            "x": round(self.position.x, 2),
            "y": round(self.position.y, 2),
            "heading": round(self.heading, 4),
            "speed": round(self.speed, 2),
            "damage": round(self.damage, 3),
            "contacts": self._contacts,
            "on_track": self.on_track,
        }
