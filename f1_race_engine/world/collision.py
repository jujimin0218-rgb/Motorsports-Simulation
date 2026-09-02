"""What happens when two things want the same piece of road.

Three kinds of contact, and they are all the same question asked of different
shapes: car against car, car against the edge of the road, car against a wall.

Cars are rectangles that point somewhere, so car against car is the separating
axis test -- four axes, and if the projections overlap on all four they are
touching, with the shallowest overlap giving the direction to push them apart
and by how much.

Resolution is deliberately simple.  A real contact would need masses, inertia
and a restitution model; what a race needs to know is that the cars have been
moved apart, that both lost speed, that the one that was hit was turned, and
that somebody is now carrying damage.  Those are what come out.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from .body import CarBody
from .geometry import Vec2, closest_point_on_segment

__all__ = ["Contact", "overlap", "resolve", "separate", "against_wall", "ContactKind"]

#: How much speed a contact costs, as a fraction, per metre of overlap.
#:
#: A brush at the edge of the bodywork is a few centimetres and costs almost
#: nothing; a car put fully into the side of another is most of a car width and
#: costs both of them a lot of their speed.
SPEED_LOSS_PER_M = 0.22

#: Damage per metre of overlap, on the same reasoning.
DAMAGE_PER_M = 0.30

#: A wall takes more out of a car than another car does.
WALL_MULTIPLIER = 2.2

#: How much of the push a contact turns into a change of heading, rad per metre.
TURN_PER_M = 0.35


class ContactKind(str):
    CAR = "car"
    WALL = "wall"


@dataclass(frozen=True, slots=True)
class Contact:
    """Two things touching, and how to stop them touching."""

    normal: Vec2
    """Unit vector along which to separate, pointing away from the other thing."""

    depth: float
    """Metres of overlap."""

    point: Vec2
    """Roughly where they met."""

    kind: str = ContactKind.CAR


def overlap(a: CarBody, b: CarBody) -> Contact | None:
    """Whether two cars are touching, and how to part them.

    The separating axis theorem on two rectangles: if any of the four axes has
    a gap, they are apart, and there is nothing to do.  Otherwise the axis with
    the least overlap is the shortest way out.
    """
    axes = (*a.axes(), *b.axes())
    best_depth = float("inf")
    best_axis = axes[0]
    for axis in axes:
        a_low, a_high = a.project(axis)
        b_low, b_high = b.project(axis)
        if a_high <= b_low or b_high <= a_low:
            return None
        depth = min(a_high - b_low, b_high - a_low)
        if depth < best_depth:
            best_depth = depth
            best_axis = axis

    # Point the normal from b to a, so a is pushed away from b.
    between = a.position - b.position
    normal = best_axis if between.dot(best_axis) >= 0.0 else best_axis * -1.0
    return Contact(
        normal=normal.normalised(),
        depth=best_depth,
        point=(a.position + b.position) * 0.5,
        kind=ContactKind.CAR,
    )


def against_wall(
    car: CarBody,
    wall: tuple[Vec2, ...],
    candidates: Sequence[int] | None = None,
) -> Contact | None:
    """Whether a car has reached a wall.

    How far the car reaches towards the wall is taken along the direction the
    wall actually is, not as the radius of a circle around the car: a car
    running parallel to a wall reaches its half width towards it, and treating
    that as its diagonal has it scraping along a wall three metres away.
    """
    if len(wall) < 2:
        return None
    # Only the segments that could be nearest, when the caller has an index of
    # them.  A lap's wall is a thousand segments and this is asked of every car
    # on every pass; walking all of them is most of a step.
    if candidates is None:
        candidates = range(len(wall) - 1)
    best: Vec2 | None = None
    best_distance = float("inf")
    for index in candidates:
        candidate = closest_point_on_segment(car.position, wall[index], wall[index + 1])
        distance = (car.position - candidate).length_squared
        if distance < best_distance:
            best = candidate
            best_distance = distance
    if best is None:
        return None
    distance = math.sqrt(best_distance)
    away = car.position - best
    normal = away.normalised() if distance > 0.0 else car.forward.left
    reach = abs(car.forward.dot(normal)) * car.half_length + abs(
        car.forward.left.dot(normal)
    ) * car.half_width
    if distance >= reach:
        return None
    return Contact(
        normal=normal,
        depth=reach - distance,
        point=best,
        kind=ContactKind.WALL,
    )


def separate(a: CarBody, b: CarBody | None, contact: Contact) -> None:
    """Move them apart, and charge nobody.

    Split from :func:`resolve` because a step separates more than once -- a car
    turned by a contact is wider across than it was, so parting two cars can
    put them back together -- and paying for the same contact three times sends
    them into the scenery.
    """
    if b is None:
        a.position = a.position + contact.normal * contact.depth
    else:
        # Half each: two cars in a contact are equally in the way of each other.
        a.position = a.position + contact.normal * (contact.depth * 0.5)
        b.position = b.position - contact.normal * (contact.depth * 0.5)


def resolve(a: CarBody, b: CarBody | None, contact: Contact) -> None:
    """Part the two, and charge them for it.

    ``b`` is the other car, or ``None`` for a wall -- a wall does not move and
    does not care, so the whole of the separation and all of the cost land on
    the one car.
    """
    hardness = WALL_MULTIPLIER if b is None else 1.0
    depth = contact.depth
    separate(a, b, contact)

    # A contact along the car's own direction is a nudge; one across it is a
    # hit.  How square it is decides how much it costs.
    squareness = abs(contact.normal.dot(a.forward.left))
    loss = min(0.9, SPEED_LOSS_PER_M * depth * hardness * (0.35 + squareness))
    hurt = DAMAGE_PER_M * depth * hardness * (0.35 + squareness)

    a.speed = max(0.0, a.speed * (1.0 - loss))
    _deflect(a, contact.normal, TURN_PER_M * depth * hardness)
    a.hurt(hurt)

    if b is not None:
        b.speed = max(0.0, b.speed * (1.0 - loss))
        _deflect(b, contact.normal * -1.0, TURN_PER_M * depth)
        b.hurt(hurt)


def _deflect(car: CarBody, towards: Vec2, amount: float) -> None:
    """Turn a car towards a direction, by no more than ``amount``.

    A contact pushes a car away from what it hit, and the nose follows -- the
    sign has to come from which side of the car the direction is on, or the two
    cars in a contact turn into each other and touch again on the next step.
    """
    car.heading += math.copysign(amount, car.forward.cross(towards))
