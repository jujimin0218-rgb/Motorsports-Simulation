"""Driver mistakes.

A mistake must cost time the way a real one does: by the car going more slowly
through a corner, not by seconds being added to a result.  So a mistake here
reduces the apex speed the driver achieves at one corner on one lap, and the
speed profile then propagates the consequences on its own -- a slower apex means
a slower exit, which means a slower run down the following straight.

Probability comes from ``risk_management`` and ``consistency`` together: a
driver who is both erratic and reckless makes mistakes often, one who is
disciplined almost never.  Severity is drawn separately, so most mistakes are
small and a few are expensive, which is the real distribution.

Phase 11 promotes the larger end of this into race events -- a spin, a run
through the gravel, damage.  The event layer will subscribe to these rather
than replace them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..core.config import DriverConfig
from ..core.rng import RngHub
from .model import DriverAttributes

__all__ = ["DriverMistake", "sample_mistakes"]


@dataclass(frozen=True, slots=True)
class DriverMistake:
    """One error, at one corner, on one lap."""

    corner_id: int
    corner_name: str | None
    lap: int
    severity: float
    """0 to 1.  The fraction of the mistake model's full severity."""

    speed_penalty: float
    """Fraction of apex speed lost, applied to the cornering limit there."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "corner_id": self.corner_id,
            "corner_name": self.corner_name,
            "lap": self.lap,
            "severity": self.severity,
            "speed_penalty": self.speed_penalty,
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        label = self.corner_name or f"corner {self.corner_id}"
        return f"DriverMistake(lap {self.lap}, {label}, -{self.speed_penalty:.1%} apex)"


def sample_mistakes(
    attributes: DriverAttributes,
    rng: RngHub,
    *,
    driver: str,
    lap: int,
    corners: dict[int, str | None],
    config: DriverConfig | None = None,
) -> tuple[DriverMistake, ...]:
    """Draw the mistakes ``driver`` makes on this lap."""
    cfg = config or DriverConfig()
    if cfg.mistake_rate <= 0.0 or not corners:
        return ()

    # Both abilities protect against mistakes, and they compound: the product
    # means a driver has to be weak on both to be genuinely error-prone.
    exposure = (1.0 - attributes.risk_management) * (1.0 - attributes.consistency)
    probability = cfg.mistake_rate * exposure
    if probability <= 0.0:
        return ()

    mistakes: list[DriverMistake] = []
    for corner_id, corner_name in sorted(corners.items()):
        stream = rng.stream(
            "driver.mistakes", driver=driver, lap=lap, corner=corner_id
        )
        if not stream.chance(probability):
            continue
        # Most mistakes are small; the square makes the tail the rare part.
        severity = stream.random() ** 2
        mistakes.append(
            DriverMistake(
                corner_id=corner_id,
                corner_name=corner_name,
                lap=lap,
                severity=severity,
                speed_penalty=severity * cfg.mistake_severity,
            )
        )
    return tuple(mistakes)
