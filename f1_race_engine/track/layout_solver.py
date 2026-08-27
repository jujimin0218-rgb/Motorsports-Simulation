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

This is a **design-time** tool.  Run it once when authoring a circuit and store
the solved lengths in the track's JSON; nothing calls it at simulation time.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Any

from ..core.errors import TrackBuildError
from .definitions import CornerDefinition, StraightDefinition, TrackDefinition

__all__ = ["ClosureSolution", "apply_straight_lengths", "solve_straight_lengths"]


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
