"""Shared numeric helpers: clamping, interpolation and smooth profiles.

Track elevation, banking, width and (later) surface grip are all defined as
sparse control points that must be turned into a value **and a derivative** at
any distance along the lap.  Doing that with straight linear interpolation
gives a discontinuous gradient, which shows up in the physics as impulsive
longitudinal load changes at every control point.

:class:`PiecewiseProfile` therefore supports monotone cubic (Fritsch-Carlson
PCHIP) interpolation, which is C1 continuous and -- unlike a natural cubic
spline -- never overshoots the control points, so a hill cannot invent a dip
that was not in the data.  Profiles can be *periodic*, which matters for a
closed circuit: the elevation at the start/finish line must join smoothly to
the elevation arriving at the end of the lap.
"""

from __future__ import annotations

import bisect
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

from .errors import ConfigError

InterpolationMethod = Literal["linear", "monotone_cubic", "step"]


def clamp(value: float, lower: float, upper: float) -> float:
    """Clamp ``value`` into ``[lower, upper]``."""
    if lower > upper:
        raise ValueError(f"invalid clamp bounds: [{lower}, {upper}]")
    if value < lower:
        return lower
    if value > upper:
        return upper
    return value


def lerp(a: float, b: float, t: float) -> float:
    """Linear interpolation between ``a`` and ``b`` for ``t`` in ``[0, 1]``."""
    return a + (b - a) * t


def inverse_lerp(a: float, b: float, value: float) -> float:
    """Return ``t`` such that ``lerp(a, b, t) == value``; 0 when ``a == b``."""
    if a == b:
        return 0.0
    return (value - a) / (b - a)


def smoothstep(edge0: float, edge1: float, value: float) -> float:
    """Classic Hermite smoothstep, clamped to ``[0, 1]``."""
    t = clamp(inverse_lerp(edge0, edge1, value), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


@dataclass(frozen=True, slots=True)
class ControlPoint:
    """A single ``(x, y)`` control point of a :class:`PiecewiseProfile`."""

    x: float
    y: float


class PiecewiseProfile:
    """A 1-D profile ``y(x)`` defined by control points.

    Parameters
    ----------
    points:
        Iterable of ``(x, y)`` pairs.  Order does not matter; duplicates in
        ``x`` are rejected.
    method:
        ``"monotone_cubic"`` (default) for a C1, overshoot-free curve,
        ``"linear"`` for straight segments, ``"step"`` to hold each value
        until the next control point.
    period:
        When given, the profile wraps: ``value(x) == value(x + period)`` and
        the derivative is continuous across the seam.  Used for closed
        circuits, where ``period`` is the lap length.
    """

    __slots__ = (
        "_xs",
        "_ys",
        "_slopes",
        "_method",
        "_period",
        "_origin",
        "_closure_mismatch",
    )

    def __init__(
        self,
        points: Iterable[tuple[float, float]],
        *,
        method: InterpolationMethod = "monotone_cubic",
        period: float | None = None,
    ) -> None:
        pts = sorted((float(x), float(y)) for x, y in points)
        if not pts:
            raise ConfigError("a profile needs at least one control point")
        for left, right in zip(pts, pts[1:]):
            if left[0] == right[0]:
                raise ConfigError(f"duplicate control point at x={left[0]}")
        self._closure_mismatch = 0.0
        if period is not None and len(pts) > 1:
            if period <= 0.0:
                raise ConfigError("profile period must be positive")
            span = pts[-1][0] - pts[0][0]
            tol = 1e-9 * max(1.0, period)
            if span > period + tol:
                raise ConfigError(
                    f"control points span {span} which exceeds the period {period}"
                )
            if abs(span - period) <= tol:
                # The caller supplied both ends of the loop.  Under wrapping
                # they are the same x, so the trailing point is redundant; keep
                # the difference so validation can report a lap that does not
                # return to its starting value.
                self._closure_mismatch = pts[-1][1] - pts[0][1]
                pts = pts[:-1]
        elif period is not None and period <= 0.0:
            raise ConfigError("profile period must be positive")
        self._method: InterpolationMethod = method
        self._period = period
        self._origin = pts[0][0]

        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]

        n = len(pts)
        padded = period is not None and n > 1
        if padded:
            # Wrap one point in from each end so slopes at the seam see their
            # true neighbours.  A closed lap is expected to return to its
            # starting value; if it does not, the seam simply interpolates the
            # mismatch (validation reports it separately).
            xs = [xs[-1] - period] + xs + [xs[0] + period]
            ys = [ys[-1]] + ys + [ys[0]]

        self._xs = xs
        self._ys = ys
        slopes = self._compute_slopes(xs, ys, method)
        if padded:
            # The two padding points are copies of real interior points, so
            # they must carry the interior slope rather than the one-sided end
            # slope -- otherwise the derivative jumps across the seam.
            slopes[0] = slopes[n]
            slopes[n + 1] = slopes[1]
        self._slopes = slopes

    # -- construction helpers ------------------------------------------------

    @staticmethod
    def _compute_slopes(
        xs: Sequence[float], ys: Sequence[float], method: InterpolationMethod
    ) -> list[float]:
        n = len(xs)
        if n < 2 or method != "monotone_cubic":
            return [0.0] * n

        h = [xs[i + 1] - xs[i] for i in range(n - 1)]
        secants = [(ys[i + 1] - ys[i]) / h[i] for i in range(n - 1)]

        slopes = [0.0] * n
        slopes[0] = secants[0]
        slopes[-1] = secants[-1]
        for i in range(1, n - 1):
            if secants[i - 1] * secants[i] <= 0.0:
                # Local extremum: flatten to guarantee no overshoot.
                slopes[i] = 0.0
            else:
                w1 = 2.0 * h[i] + h[i - 1]
                w2 = h[i] + 2.0 * h[i - 1]
                slopes[i] = (w1 + w2) / (w1 / secants[i - 1] + w2 / secants[i])

        # Fritsch-Carlson limiter on the end slopes so the ends cannot
        # overshoot either.
        for end, nbr in ((0, 0), (n - 1, n - 2)):
            if secants[nbr] == 0.0:
                slopes[end] = 0.0
            elif slopes[end] / secants[nbr] > 3.0:
                slopes[end] = 3.0 * secants[nbr]
            elif slopes[end] / secants[nbr] < 0.0:
                slopes[end] = 0.0
        return slopes

    # -- evaluation ----------------------------------------------------------

    def _wrap(self, x: float) -> float:
        if self._period is None:
            return x
        return self._origin + (x - self._origin) % self._period

    def _locate(self, x: float) -> int:
        """Return the index ``i`` with ``xs[i] <= x <= xs[i+1]`` (clamped)."""
        xs = self._xs
        i = bisect.bisect_right(xs, x) - 1
        if i < 0:
            return 0
        if i > len(xs) - 2:
            return len(xs) - 2
        return i

    def value(self, x: float) -> float:
        """Return ``y(x)``."""
        xs, ys = self._xs, self._ys
        if len(xs) == 1:
            return ys[0]
        x = self._wrap(x)
        if self._period is None:
            if x <= xs[0]:
                return ys[0]
            if x >= xs[-1]:
                return ys[-1]
        i = self._locate(x)
        h = xs[i + 1] - xs[i]
        t = (x - xs[i]) / h
        if self._method == "step":
            return ys[i]
        if self._method == "linear":
            return lerp(ys[i], ys[i + 1], t)
        # Cubic Hermite basis.
        m0, m1 = self._slopes[i], self._slopes[i + 1]
        t2 = t * t
        t3 = t2 * t
        h00 = 2.0 * t3 - 3.0 * t2 + 1.0
        h10 = t3 - 2.0 * t2 + t
        h01 = -2.0 * t3 + 3.0 * t2
        h11 = t3 - t2
        return h00 * ys[i] + h10 * h * m0 + h01 * ys[i + 1] + h11 * h * m1

    def derivative(self, x: float) -> float:
        """Return ``dy/dx`` at ``x``."""
        xs, ys = self._xs, self._ys
        if len(xs) == 1 or self._method == "step":
            return 0.0
        x = self._wrap(x)
        if self._period is None and (x <= xs[0] or x >= xs[-1]):
            return 0.0
        i = self._locate(x)
        h = xs[i + 1] - xs[i]
        t = (x - xs[i]) / h
        if self._method == "linear":
            return (ys[i + 1] - ys[i]) / h
        m0, m1 = self._slopes[i], self._slopes[i + 1]
        t2 = t * t
        dh00 = 6.0 * t2 - 6.0 * t
        dh10 = 3.0 * t2 - 4.0 * t + 1.0
        dh01 = -6.0 * t2 + 6.0 * t
        dh11 = 3.0 * t2 - 2.0 * t
        return (dh00 * ys[i] + dh01 * ys[i + 1]) / h + dh10 * m0 + dh11 * m1

    # -- introspection -------------------------------------------------------

    @property
    def method(self) -> InterpolationMethod:
        return self._method

    @property
    def period(self) -> float | None:
        return self._period

    @property
    def closure_mismatch(self) -> float:
        """Difference between the supplied end and start values of a loop.

        Non-zero only when the caller gave control points at both ``x0`` and
        ``x0 + period`` with different values -- i.e. a lap whose elevation (or
        banking, or width) does not return to where it started.  Track
        validation surfaces this rather than silently smoothing it away.
        """
        return self._closure_mismatch

    @property
    def control_points(self) -> tuple[ControlPoint, ...]:
        """The original control points (without the periodic wrap padding)."""
        if self._period is not None and len(self._xs) > 3:
            xs, ys = self._xs[1:-1], self._ys[1:-1]
        else:
            xs, ys = self._xs, self._ys
        return tuple(ControlPoint(x, y) for x, y in zip(xs, ys))

    @property
    def x_range(self) -> tuple[float, float]:
        pts = self.control_points
        return pts[0].x, pts[-1].x

    def __len__(self) -> int:
        return len(self.control_points)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        lo, hi = self.x_range
        return (
            f"PiecewiseProfile(n={len(self)}, x=[{lo:.1f}, {hi:.1f}], "
            f"method={self._method!r}, period={self._period})"
        )


class ConstantProfile(PiecewiseProfile):
    """A profile that returns the same value everywhere."""

    def __init__(self, value: float) -> None:
        super().__init__([(0.0, float(value))], method="linear")
