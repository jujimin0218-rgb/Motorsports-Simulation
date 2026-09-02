"""The world, one step at a time.

What this owns: where every car is on the plane, what it is touching, and what
that cost.  What it does **not** own is how fast anybody is going round the
lap -- that is the engine's distance model, and it stays there.  A step is
handed each car's distance, its place across the road and its speed, and works
out the rest.

Two properties this has to have.

**Deterministic.**  The same inputs give the same world, down to the last
contact, because the game's whole claim is that a seed replays a race.  So
nothing here iterates a dictionary's own order or a set: cars are walked in car
number order and candidate pairs come out of the grid sorted.

**Iterative.**  Parting two cars and then turning them can put them back
together -- a car at an angle takes up more room across than one that is
straight.  So contacts are resolved a few times per step rather than once,
which is what stops two cars that touched staying welded together.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .body import CarBody
from .collision import Contact, ContactKind, against_wall, overlap, resolve, separate
from .space import Grid
from .track import Surface, TrackWorld

__all__ = ["ContactEvent", "World"]

#: How many times contacts are resolved within one step.
#:
#: Once is not enough: separating two cars turns them, and a turned car is
#: wider across than a straight one, so a single pass can leave them touching.
#: Three settles the ordinary case and is cheap.
ITERATIONS = 3

#: Cells for the broadphase, m.  A few car lengths: big enough that two cars
#: racing are in the same cell, small enough that most of the grid is empty.
CELL_M = 16.0


@dataclass(frozen=True, slots=True)
class ContactEvent:
    """Something touched something, and what it cost."""

    car: int
    other: int | None
    """The other car, or ``None`` for a wall."""

    kind: str
    depth: float
    speed_lost: float
    damage: float
    at: tuple[float, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "car": self.car,
            "other": self.other,
            "kind": self.kind,
            "depth": round(self.depth, 3),
            "speed_lost": round(self.speed_lost, 2),
            "damage": round(self.damage, 4),
            "x": round(self.at[0], 2),
            "y": round(self.at[1], 2),
        }


@dataclass(slots=True)
class World:
    """Every car on the circuit, and what happens between them."""

    track: TrackWorld
    bodies: dict[int, CarBody] = field(default_factory=dict)
    events: list[ContactEvent] = field(default_factory=list)
    _grid: Grid = field(init=False)

    def __post_init__(self) -> None:
        self._grid = Grid(cell=CELL_M)

    # -- putting cars in it ---------------------------------------------------

    def enter(self, car_number: int, distance: float, offset: float = 0.0) -> CarBody:
        """Put a car on the circuit at a lap distance and a place across it."""
        position, heading = self.track.place(distance, offset)
        body = CarBody(car_number=car_number, position=position, heading=heading)
        self.bodies[car_number] = body
        return body

    def drive(
        self, car_number: int, distance: float, offset: float, speed: float
    ) -> CarBody:
        """Move a car to where the race says it is.

        The one door between the distance model and the plane.  Where the car
        is comes from the race; what it then runs into is this layer's business,
        and a contact may leave it somewhere other than where it was put.
        """
        body = self.bodies.get(car_number)
        position, heading = self.track.place(distance, offset)
        if body is None:
            body = CarBody(car_number=car_number, position=position, heading=heading)
            self.bodies[car_number] = body
        else:
            body.position = position
            body.heading = heading
        body.speed = speed
        return body

    # -- moving it on ---------------------------------------------------------

    def step(self, dt: float) -> list[ContactEvent]:
        """Advance the world by ``dt`` seconds and return what happened.

        Cars are already where the race put them; this turns any steering into
        heading, finds what is touching what, parts them, and reports the cost.
        """
        self.events = []
        numbers = sorted(self.bodies)

        for number in numbers:
            body = self.bodies[number]
            if body.steering:
                body.heading += body.steering * dt

        # Charged once: a contact costs what it costs, however many passes it
        # takes to get the cars out of each other.
        self._resolve_cars(numbers)
        self._resolve_walls(numbers)
        for _ in range(ITERATIONS - 1):
            self._separate(numbers)

        for number in numbers:
            body = self.bodies[number]
            body.on_track = self.track.surface_at(body.position) in (
                Surface.TRACK,
                Surface.KERB,
                Surface.PIT,
            )

        return self.events

    def surface_under(self, car_number: int) -> Surface:
        """What the car is on, which is what it can use of its grip."""
        return self.track.surface_at(self.bodies[car_number].position)

    # -- the two kinds of contact ---------------------------------------------

    def _resolve_cars(self, numbers: list[int]) -> None:
        self._index(numbers)
        for first, second in self._grid.pairs():
            a = self.bodies[first]
            b = self.bodies[second]
            contact = overlap(a, b)
            if contact is None:
                continue
            self._charge(a, b, contact)

    def _resolve_walls(self, numbers: list[int]) -> None:
        for number in numbers:
            body = self.bodies[number]
            for wall in self.track.barriers:
                contact = against_wall(
                    body, wall.points, wall.segments_near(body.position)
                )
                if contact is not None:
                    self._charge(body, None, contact)

    def _separate(self, numbers: list[int]) -> None:
        """Push anything still touching apart, without charging for it again."""
        self._index(numbers)
        for first, second in self._grid.pairs():
            contact = overlap(self.bodies[first], self.bodies[second])
            if contact is not None:
                separate(self.bodies[first], self.bodies[second], contact)
        for number in numbers:
            body = self.bodies[number]
            for wall in self.track.barriers:
                contact = against_wall(
                    body, wall.points, wall.segments_near(body.position)
                )
                if contact is not None:
                    separate(body, None, contact)

    def _index(self, numbers: list[int]) -> None:
        self._grid.clear()
        for number in numbers:
            self._grid.add(self.bodies[number].position, number)

    def _charge(self, a: CarBody, b: CarBody | None, contact: Contact) -> None:
        """Resolve one contact and write down what it cost."""
        before_a = a.speed
        before_damage = a.damage
        resolve(a, b, contact)
        self.events.append(
            ContactEvent(
                car=a.car_number,
                other=None if b is None else b.car_number,
                kind=ContactKind.WALL if b is None else ContactKind.CAR,
                depth=contact.depth,
                speed_lost=before_a - a.speed,
                damage=a.damage - before_damage,
                at=contact.point.to_tuple(),
            )
        )

    # -- looking at it --------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "bodies": [self.bodies[n].to_dict() for n in sorted(self.bodies)],
            "events": [event.to_dict() for event in self.events],
        }

    def debug_shapes(self) -> dict[str, Any]:
        """Every collision shape as it actually is, for drawing over the map.

        The point of it: a contact that looks wrong on screen is either the
        physics or the picture, and being able to see the rectangles the solver
        is actually using tells you which.
        """
        return {
            "cars": [
                {
                    "car_number": n,
                    "corners": [
                        [round(p.x, 2), round(p.y, 2)]
                        for p in self.bodies[n].corners()
                    ],
                    "on_track": self.bodies[n].on_track,
                    "damage": round(self.bodies[n].damage, 3),
                }
                for n in sorted(self.bodies)
            ],
            "contacts": [event.to_dict() for event in self.events],
        }
