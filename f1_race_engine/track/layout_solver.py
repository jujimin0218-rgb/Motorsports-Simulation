"""Solve straight lengths so a hand-authored layout closes.

Authoring a circuit means writing down corner radii and angles from published
data and guessing the straights in between.  The guesses never close: walking
the layout leaves a gap of tens or hundreds of metres between the end of the
lap and the start/finish line, and that gap is a real error -- the plan view is
wrong, and so is the lap length.

Straight lengths enter the closure displacement **linearly** and do not affect
any heading, so closing the loop is a small linear system rather than an
optimisation:

.. code-block:: text

    sum_i  delta_i * (cos theta_i, sin theta_i)  =  -(dx, dy)

Two equations, one unknown per straight.  The system is under-determined, which
is a gift: the minimum-norm solution changes the layout as little as possible,
and weighting by current length spreads the correction proportionally so a long
straight absorbs metres while a 25 m chicane link barely moves.  An optional
third equation pins the total lap length to a published figure.

Corner *angles* need the same treatment for a different reason.  A closed lap
turns through exactly 360 degrees, and straight lengths cannot help with that
because a straight turns the car through nothing at all.  So a set of angles
read off a track map has to be reconciled with that one constraint before the
straights can be solved -- and how far they have to move is a useful, honest
measure of how good the angles were.  :func:`solve_corner_angles` reports it.

This is a **design-time** tool.  Run it once when authoring a circuit and store
the solved lengths in the track's JSON; nothing calls it at simulation time.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Any

from ..core.errors import TrackBuildError
from .definitions import CornerDefinition, StraightDefinition, TrackDefinition

__all__ = [
    "AngleSolution",
    "ClosureSolution",
    "apply_corner_angles",
    "apply_straight_lengths",
    "solve_corner_angles",
    "solve_straight_lengths",
]


@dataclass(frozen=True, slots=True)
class ClosureSolution:
    """The outcome of a closure solve."""

    lengths: tuple[float, ...]
    """Solved length of every straight, in layout order."""

    original_lengths: tuple[float, ...]
    closure_error: float
    """Remaining plan-view gap, m."""

    lap_length: float
    initial_closure_error: float
    iterations: int
    pinned: tuple[int, ...] = ()
    """Indices of straights that hit the minimum length and were held there."""

    @property
    def adjustments(self) -> tuple[float, ...]:
        return tuple(
            new - old for new, old in zip(self.lengths, self.original_lengths)
        )

    @property
    def converged(self) -> bool:
        return self.closure_error <= 1e-3

    def to_dict(self) -> dict[str, Any]:
        return {
            "lengths": list(self.lengths),
            "adjustments": list(self.adjustments),
            "closure_error": self.closure_error,
            "initial_closure_error": self.initial_closure_error,
            "lap_length": self.lap_length,
            "iterations": self.iterations,
            "converged": self.converged,
        }


@dataclass(frozen=True, slots=True)
class AngleSolution:
    """The outcome of reconciling corner angles with a closed lap."""

    angles: tuple[float, ...]
    """Solved turn angle of every corner, degrees, in layout order."""

    original_angles: tuple[float, ...]
    turns: int
    """Whole laps of heading the layout makes; -1 clockwise, +1 anticlockwise."""

    residual_deg: float
    """Heading the authored angles were short of (or over) a closed lap."""

    @property
    def adjustments(self) -> tuple[float, ...]:
        """How far each angle moved, degrees."""
        return tuple(
            new - old for new, old in zip(self.angles, self.original_angles)
        )

    @property
    def worst_adjustment_fraction(self) -> float:
        """Largest relative change made to any one corner.

        The honest quality measure for a hand-authored layout.  A few percent
        means the angles were read carefully and the arithmetic just had to be
        tidied up.  Tens of percent means the layout is a guess wearing a real
        circuit's name, and it should not be shipped as one.
        """
        return max(
            (
                abs(new - old) / old
                for new, old in zip(self.angles, self.original_angles)
                if old > 0.0
            ),
            default=0.0,
        )


def _corner_indices(definition: TrackDefinition) -> list[int]:
    return [
        i
        for i, element in enumerate(definition.layout)
        if isinstance(element, CornerDefinition)
    ]


def apply_corner_angles(
    definition: TrackDefinition, angles: list[float] | tuple[float, ...]
) -> TrackDefinition:
    """Return a copy of ``definition`` with new corner angles, in degrees."""
    indices = _corner_indices(definition)
    if len(indices) != len(angles):
        raise TrackBuildError(
            f"expected {len(indices)} corner angle(s), got {len(angles)}"
        )
    layout = list(definition.layout)
    for position, angle in zip(indices, angles):
        element = layout[position]
        assert isinstance(element, CornerDefinition)
        layout[position] = replace(element, angle=float(angle))
    return replace(definition, layout=tuple(layout))


def solve_corner_angles(
    definition: TrackDefinition, *, turns: int | None = None
) -> AngleSolution:
    """Scale corner angles so the lap's heading closes exactly.

    A closed circuit turns through a whole number of full revolutions -- one,
    for every layout on the calendar.  Angles read off a track map never sum to
    it exactly, and the error has nowhere to go: straights do not turn the car,
    so unless the angles are reconciled first the plan view cannot close no
    matter what :func:`solve_straight_lengths` does with the straights.

    The correction is spread in proportion to each angle, which is the
    minimum-norm choice under the natural assumption that a big corner read off
    a map carries proportionally more error than a small one.  It also keeps
    the layout's character: every corner keeps its share of the lap's turning.

    :param turns: revolutions the layout makes, signed (-1 clockwise).
        Defaults to whichever whole number the authored angles are nearest to.
    """
    indices = _corner_indices(definition)
    if not indices:
        raise TrackBuildError("a layout with no corners cannot be closed")

    corners = [definition.layout[i] for i in indices]
    original = tuple(corner.angle for corner in corners)
    total = sum(
        corner.direction.sign * corner.angle for corner in corners
    )
    if turns is None:
        turns = round(total / 360.0)
        if turns == 0:
            raise TrackBuildError(
                f"the layout turns through only {total:.1f} degrees, which is not "
                f"close to a whole lap; check the corner directions"
            )
    target = 360.0 * turns
    if total == 0.0:
        raise TrackBuildError("the layout's corners cancel out entirely")

    scale = target / total
    if scale <= 0.0:
        raise TrackBuildError(
            f"the layout turns {total:.1f} degrees but was asked to close at "
            f"{target:.1f}; the corner directions do not match the requested turns"
        )
    angles = tuple(angle * scale for angle in original)
    return AngleSolution(
        angles=angles,
        original_angles=original,
        turns=turns,
        residual_deg=target - total,
    )


def _straight_headings(definition: TrackDefinition) -> list[float]:
    """Heading of each straight, in layout order, radians."""
    headings: list[float] = []
    heading = 0.0
    for element in definition.layout:
        if isinstance(element, StraightDefinition):
            headings.append(heading)
        elif isinstance(element, CornerDefinition):
            heading += element.turn_angle(definition.defaults)
    return headings


def _straight_indices(definition: TrackDefinition) -> list[int]:
    return [
        i
        for i, element in enumerate(definition.layout)
        if isinstance(element, StraightDefinition)
    ]


def _closure_residual(definition: TrackDefinition) -> tuple[float, float]:
    """Plan-view gap ``(dx, dy)`` from the end of the lap back to its start."""
    from .builder import build_track

    track = build_track(definition)
    centerline = track.centerline()
    first, last = centerline.points[0], centerline.points[-1]
    return last.x - first.x, last.y - first.y


def _solve_linear(matrix: list[list[float]], rhs: list[float]) -> list[float]:
    """Gaussian elimination with partial pivoting for a tiny dense system."""
    n = len(rhs)
    augmented = [row[:] + [rhs[i]] for i, row in enumerate(matrix)]
    for column in range(n):
        pivot = max(range(column, n), key=lambda r: abs(augmented[r][column]))
        if abs(augmented[pivot][column]) < 1e-12:
            raise TrackBuildError(
                "closure system is degenerate: the free straights do not span "
                "enough directions to close the lap"
            )
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        pivot_row = augmented[column]
        for row in range(n):
            if row == column:
                continue
            factor = augmented[row][column] / pivot_row[column]
            for k in range(column, n + 1):
                augmented[row][k] -= factor * pivot_row[k]
    return [augmented[i][n] / augmented[i][i] for i in range(n)]


def apply_straight_lengths(
    definition: TrackDefinition, lengths: list[float] | tuple[float, ...]
) -> TrackDefinition:
    """Return a copy of ``definition`` with new straight lengths."""
    indices = _straight_indices(definition)
    if len(indices) != len(lengths):
        raise TrackBuildError(
            f"expected {len(indices)} straight length(s), got {len(lengths)}"
        )
    layout = list(definition.layout)
    for position, length in zip(indices, lengths):
        element = layout[position]
        assert isinstance(element, StraightDefinition)
        layout[position] = replace(element, length=float(length))
    return replace(definition, layout=tuple(layout))


def solve_straight_lengths(
    definition: TrackDefinition,
    *,
    target_lap_length: float | None = None,
    min_straight_length: float = 20.0,
    tolerance: float = 1e-6,
    max_iterations: int = 24,
) -> ClosureSolution:
    """Adjust the straights of ``definition`` so the plan view closes.

    Parameters
    ----------
    target_lap_length:
        When given, a third constraint pins the lap to this length -- useful
        when the published figure for a real circuit is known.
    min_straight_length:
        Straights are never driven below this; one that would be is pinned
        here and the remaining straights take up the slack.

    Returns
    -------
    ClosureSolution
        Check :attr:`ClosureSolution.converged` before trusting the result: a
        layout whose straights all run in one or two directions may not be able
        to close at all.
    """
    indices = _straight_indices(definition)
    if not indices:
        raise TrackBuildError("layout has no straights to adjust")

    headings = _straight_headings(definition)
    original = tuple(
        definition.layout[i].length for i in indices  # type: ignore[union-attr]
    )
    lengths = list(original)
    pinned: set[int] = set()
    initial_error = math.hypot(*_closure_residual(definition))
    iterations = 0

    corner_length = math.fsum(
        element.arc_length(definition.defaults)
        for element in definition.layout
        if isinstance(element, CornerDefinition)
    )

    for iterations in range(1, max_iterations + 1):
        current = apply_straight_lengths(definition, lengths)
        dx, dy = _closure_residual(current)
        residual = [-dx, -dy]
        if target_lap_length is not None:
            target_straight_total = target_lap_length - corner_length
            residual.append(target_straight_total - math.fsum(lengths))

        if max(abs(r) for r in residual) <= tolerance:
            break

        free = [k for k in range(len(lengths)) if k not in pinned]
        if not free:
            break

        # Rows of the constraint matrix, one per equation.
        rows: list[list[float]] = [
            [math.cos(headings[k]) for k in free],
            [math.sin(headings[k]) for k in free],
        ]
        if target_lap_length is not None:
            rows.append([1.0] * len(free))

        weights = [max(lengths[k], min_straight_length) for k in free]
        size = len(rows)
        normal = [
            [
                math.fsum(
                    w * w * rows[a][c] * rows[b][c] for c, w in enumerate(weights)
                )
                for b in range(size)
            ]
            for a in range(size)
        ]
        try:
            multipliers = _solve_linear(normal, residual)
        except TrackBuildError:
            break

        candidate = list(lengths)
        for column, k in enumerate(free):
            delta = (
                weights[column]
                * weights[column]
                * math.fsum(multipliers[a] * rows[a][column] for a in range(size))
            )
            candidate[k] = lengths[k] + delta

        violated = [k for k in free if candidate[k] < min_straight_length]
        for k in violated:
            candidate[k] = min_straight_length
            pinned.add(k)
        lengths = candidate

    solved = apply_straight_lengths(definition, lengths)
    dx, dy = _closure_residual(solved)
    return ClosureSolution(
        lengths=tuple(lengths),
        original_lengths=original,
        closure_error=math.hypot(dx, dy),
        lap_length=solved.lap_length,
        initial_closure_error=initial_error,
        iterations=iterations,
        pinned=tuple(sorted(pinned)),
    )
