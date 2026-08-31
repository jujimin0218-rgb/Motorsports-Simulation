"""Where things are, so that finding them is not a search.

Two questions get asked constantly once a race is a place rather than a line:
which bit of road is this point on, and which cars are near this car.  Both are
answered by putting everything in a uniform grid of square cells and looking
only in the cells that could hold an answer.

A uniform grid rather than a tree: a circuit is a long thin thing spread over a
kilometre and the cells are the size of a few cars, which is exactly the case a
grid is good at and a tree is fiddly for.  Cells are visited in a fixed order,
so what comes out does not depend on how a dictionary happened to be laid out.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field

from .geometry import Vec2

__all__ = ["SampleGrid", "Grid"]


@dataclass(slots=True)
class Grid:
    """A uniform grid of square cells holding whatever is put in them."""

    cell: float
    _cells: dict[tuple[int, int], list[int]] = field(default_factory=dict)

    def key(self, point: Vec2) -> tuple[int, int]:
        return (int(point.x // self.cell), int(point.y // self.cell))

    def add(self, point: Vec2, value: int) -> None:
        self._cells.setdefault(self.key(point), []).append(value)

    def clear(self) -> None:
        self._cells.clear()

    def near(self, point: Vec2, rings: int = 1) -> Iterator[int]:
        """Everything in the cells around a point, in a fixed order.

        ``rings`` is how many cells out to look: one is the eight neighbours
        and the cell itself, which covers anything within a cell's width.
        """
        cx, cy = self.key(point)
        for dy in range(-rings, rings + 1):
            for dx in range(-rings, rings + 1):
                found = self._cells.get((cx + dx, cy + dy))
                if found is not None:
                    yield from found

    def pairs(self, rings: int = 1) -> Iterator[tuple[int, int]]:
        """Every pair of values that share a cell or neighbour one.

        Each pair once, lower value first, cells walked in sorted order -- so a
        broadphase over the same positions yields the same pairs in the same
        order every time it is run.
        """
        seen: set[tuple[int, int]] = set()
        for cell in sorted(self._cells):
            cx, cy = cell
            here = self._cells[cell]
            neighbours: list[int] = []
            for dy in range(-rings, rings + 1):
                for dx in range(-rings, rings + 1):
                    found = self._cells.get((cx + dx, cy + dy))
                    if found is not None:
                        neighbours.extend(found)
            for a in here:
                for b in neighbours:
                    if a == b:
                        continue
                    pair = (a, b) if a < b else (b, a)
                    if pair not in seen:
                        seen.add(pair)
                        yield pair


@dataclass(slots=True)
class SampleGrid:
    """The circuit's own samples, indexed by where they are.

    Built once when the world is, because the road does not move.
    """

    cell: float
    _grid: Grid = field(init=False)

    def __post_init__(self) -> None:
        self._grid = Grid(cell=self.cell)

    @classmethod
    def of(cls, points: Iterable[Vec2], *, cell: float) -> SampleGrid:
        grid = cls(cell=cell)
        for index, point in enumerate(points):
            grid._grid.add(point, index)
        return grid

    def near(self, point: Vec2, rings: int = 1) -> Iterator[int]:
        return self._grid.near(point, rings)
