"""The line a car actually drives, and why it is not the centre of the road.

A circuit surveyed honestly is a **centreline**.  A car does not drive it: it
goes to the outside before a corner, cuts to the apex, and comes out wide
again, because a straighter path can be taken faster.  Everything downstream of
this module -- the cornering limit, the speed profile, the lap time -- reads a
curvature, and reading the *road's* curvature when the car is on a different
path makes every real circuit come out slow.  Measured, that error is seven
seconds at Monza.

So this finds the path.

**What is being solved.**  A line is a lateral offset ``n(s)`` from the
centreline, bounded by how much road there is: ``|n| <= h(s)``, where ``h`` is
half the track width less half the car.  The curvature of an offset path is

.. code-block:: text

    kappa_line = (kappa + n'') / (1 - n * kappa)

and the quickest line through a corner is the one that minimises the peak of
it -- which, since speed goes as the square root of the radius, is very nearly
the one that minimises the integral of its square.  So:

    minimise  sum (kappa + n'')^2      subject to  |n| <= h

That is a constrained quadratic problem, and the constraint is what makes it
well posed: without it the answer is ``n'' = -kappa``, a straight line, which
no amount of road allows.

It is solved through its **normal equations** rather than by relaxing
``n'' = kappa`` directly, and that distinction is the whole thing working.  A
lap is a loop that turns three hundred and sixty degrees, so ``n'' = -kappa``
has no periodic solution at all; relaxing it makes the line drift until every
point is pinned against one edge of the road, which is a car driving a whole
lap with two wheels on the grass and buys nothing -- measured, it was worth
eight per cent of a radius where the geometry says a hundred.
Differentiating the objective properly gives a fourth-order system, the
biharmonic ``n'''' = -kappa''``, which does have a periodic solution and whose
answer is the shape a driver would recognise: outside on the way in, across to
the apex, back out on the exit.

Solved by projected Gauss-Seidel -- sweep, relax each point, clamp it back
into the road, repeat -- wrapping at the start line, because that is an
arbitrary place to put a boundary.

And solved **coarse first**.  Relaxation is very good at removing short-
wavelength error and very bad at long-wavelength error, and a racing line is
almost entirely long wavelength: it varies over the length of a corner, not
over the two metres between samples.  Run on the fine grid alone it does not
converge in any practical number of sweeps -- the offset stays near zero and
the only thing that moves is a kink at each corner entry, which comes out
*tighter* than the road.  So the lap is solved at a coarse spacing first,
the answer is interpolated up, and each finer grid only has to clean up what
the coarser one could not see.

**Why "adaptive".**  Nothing here is per-corner.  The solve sees the whole lap
at once, so it gets for free the things a per-corner rule has to be told:

* a corner is straightened only as much as the road at *that* point allows, so
  a narrow circuit stays a narrow circuit;
* a sequence -- a chicane, an esse -- is compromised across its whole length
  rather than each half being optimised into the other's way;
* a corner with a short straight before it cannot use the full width, because
  the line has not had room to get across.

**What it does not model, and the one that matters.**  The objective is the
*integral* of squared curvature, which is the standard tractable proxy and is
not the same thing as the *peak*.  A lap time is made of peaks: the slowest
point of a corner sets the speed through it.  A line that eases the middle of a
corner while spiking at turn-in can have a lower integral and a higher peak, and
on a narrow circuit with short transitions that is what it does -- measured, the
line comes out 13% *tighter* than the road at Monza, where the road is 9.4 m
wide and the usable half-width is barely three metres.

So this is switched on per circuit (``TrackDefaults.geometry``) and off by
default, and the surveyed circuits do not use it yet.  On corners with the
transitions a real road has and room to move, it does what it should -- twenty
to ninety per cent of radius, which is the size a racing line is.  Closing the
gap on the tight narrow ones needs a min-max objective rather than a min-sum
one, which is a different and larger piece of work.

The line is also purely geometric: it is the quickest path, not the path a
driver takes to defend, to pass or to save a tyre, and it takes no account of
where the car is braking or on the throttle -- a real line is later-apexed out
of a slow corner onto a long straight, and this is not.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

__all__ = [
    "CAR_WIDTH",
    "RacingLine",
    "solve_racing_line",
]

#: A Formula 1 car is a little under two metres wide.  It is the part of the
#: road the car occupies and therefore cannot use to move about in.
CAR_WIDTH = 2.0

#: How much of the remaining width a driver will actually use.  Not all of it:
#: the last few centimetres either side are a white line, a kerb and a gravel
#: trap, and a lap that used them would be a lap that ended in the wall.
USABLE_FRACTION = 0.85

#: Sweeps of the relaxation.  The solve is a Poisson problem on a loop, which
#: converges slowly by relaxation -- but the *answer* stops moving long before
#: the residual does, because the constraint pins most of the line against one
#: edge or the other.  Measured: the lap time is settled by about 300 sweeps
#: and does not move after 600.
SWEEPS = 400

#: Over-relaxation.  Above one it converges faster; too far above and it
#: oscillates against the clamp.
OMEGA = 1.6


@dataclass(frozen=True, slots=True)
class RacingLine:
    """A line, and enough about it to see what it did."""

    offset: tuple[float, ...]
    """Lateral offset from the centreline, m.  Positive is to the left."""

    curvature: tuple[float, ...]
    """The curvature the car actually experiences, 1/m."""

    centreline_curvature: tuple[float, ...]
    half_width: tuple[float, ...]

    @property
    def peak_centreline(self) -> float:
        return max((abs(k) for k in self.centreline_curvature), default=0.0)

    @property
    def peak_line(self) -> float:
        return max((abs(k) for k in self.curvature), default=0.0)

    @property
    def tightest_centreline_radius(self) -> float:
        peak = self.peak_centreline
        return 1.0 / peak if peak > 0 else float("inf")

    @property
    def tightest_line_radius(self) -> float:
        peak = self.peak_line
        return 1.0 / peak if peak > 0 else float("inf")

    @property
    def width_used(self) -> float:
        """The largest fraction of the available road the line asked for."""
        pairs = [
            abs(n) / h for n, h in zip(self.offset, self.half_width) if h > 0
        ]
        return max(pairs, default=0.0)


def _relax(
    offset: list[float],
    curvature: Sequence[float],
    half: Sequence[float],
    step: float,
    sweeps: int,
    omega: float,
) -> None:
    """Projected Gauss-Seidel on the biharmonic, in place.

    The sign of the forcing is the part that has to be right and was not first
    time.  Offset a straight centreline and the path's curvature is ``+n''`` --
    a line that bends left is turning left -- so the quantity being minimised is
    ``kappa + n''`` and the forcing carries a minus.  With it the other way
    round the solve puts the apex on the *outside* of every corner, and the
    radius comes back at 0.91 of the centreline rather than above it.
    """
    count = len(offset)
    if count < 5:
        return
    step_squared = step * step
    forcing = [
        -(curvature[i - 1] - 2.0 * curvature[i] + curvature[(i + 1) % count])
        * step_squared
        for i in range(count)
    ]
    for _ in range(sweeps):
        for i in range(count):
            neighbours = 4.0 * (offset[i - 1] + offset[(i + 1) % count]) - (
                offset[i - 2] + offset[(i + 2) % count]
            )
            target = (neighbours + forcing[i]) / 6.0
            value = offset[i] + omega * (target - offset[i])
            limit = half[i]
            offset[i] = (
                -limit if value < -limit else (limit if value > limit else value)
            )


def _coarsen(values: Sequence[float], factor: int) -> list[float]:
    """Average down by a whole factor, wrapping."""
    count = len(values)
    coarse = []
    for start in range(0, count, factor):
        window = [values[(start + k) % count] for k in range(factor)]
        coarse.append(sum(window) / factor)
    return coarse


def _refine(coarse: Sequence[float], target: int) -> list[float]:
    """Linear interpolation back up to ``target`` samples, wrapping."""
    count = len(coarse)
    fine = []
    for i in range(target):
        position = i * count / target
        low = int(position) % count
        t = position - int(position)
        fine.append(coarse[low] * (1.0 - t) + coarse[(low + 1) % count] * t)
    return fine


def _cascade(
    curvature: Sequence[float],
    half: Sequence[float],
    step: float,
    *,
    sweeps: int,
    omega: float,
) -> list[float]:
    """Solve coarse, then refine -- see the module docstring for why."""
    count = len(curvature)
    offset: list[float] | None = None
    for factor in (16, 8, 4, 2, 1):
        if count // factor < 8:
            continue
        level_curvature = _coarsen(curvature, factor) if factor > 1 else list(curvature)
        level_half = _coarsen(half, factor) if factor > 1 else list(half)
        level_step = step * factor
        level_count = len(level_curvature)
        if offset is None:
            level_offset = [0.0] * level_count
        else:
            level_offset = _refine(offset, level_count)
            for i, limit in enumerate(level_half):
                level_offset[i] = max(-limit, min(limit, level_offset[i]))
        _relax(level_offset, level_curvature, level_half, level_step, sweeps, omega)
        offset = level_offset
    return offset if offset is not None else [0.0] * count


def solve_racing_line(
    curvature: Sequence[float],
    track_width: Sequence[float],
    step: float,
    *,
    car_width: float = CAR_WIDTH,
    usable_fraction: float = USABLE_FRACTION,
    sweeps: int = SWEEPS,
    omega: float = OMEGA,
) -> RacingLine:
    """Find the quickest line through a lap of centreline curvature.

    ``curvature`` and ``track_width`` are sampled at ``step`` metres round the
    lap, and the lap wraps.  The result is the curvature the car experiences,
    which is what everything downstream should be reading.
    """
    count = len(curvature)
    if count < 3 or step <= 0.0:
        return RacingLine(
            offset=tuple(0.0 for _ in curvature),
            curvature=tuple(curvature),
            centreline_curvature=tuple(curvature),
            half_width=tuple(0.0 for _ in curvature),
        )

    half = [
        max(0.0, (width - car_width) * 0.5 * usable_fraction)
        for width in track_width
    ]
    step_squared = step * step

    # The forcing: the second difference of the road's curvature.  Zero along a
    # constant-radius corner and along a straight, and non-zero only where one
    # becomes the other -- which is right, because a corner entry is exactly
    # where a line has to change shape.
    offset = _cascade(curvature, half, step, sweeps=sweeps, omega=omega)

    # The curvature of the offset path.  The denominator is what stops a line
    # that has moved toward the inside of a corner from being credited with the
    # centreline's radius: moving toward the centre of a bend tightens it.
    line: list[float] = []
    for i in range(count):
        second = (
            offset[i - 1] - 2.0 * offset[i] + offset[(i + 1) % count]
        ) / step_squared
        denominator = 1.0 - offset[i] * curvature[i]
        if abs(denominator) < 1e-6:
            denominator = 1e-6 if denominator >= 0 else -1e-6
        line.append((curvature[i] + second) / denominator)

    return RacingLine(
        offset=tuple(offset),
        curvature=tuple(line),
        centreline_curvature=tuple(curvature),
        half_width=tuple(half),
    )
