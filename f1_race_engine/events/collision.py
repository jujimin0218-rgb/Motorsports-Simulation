"""Contact, and what it costs.

Contact is a hazard **per lap spent fighting somebody**, not per lap.  A car in
clean air does not hit anybody, so exposure is time spent within fighting
distance -- which means a race where nobody can pass produces contact and a
processional one does not, without either being written down.

Two things scale it, and both are real:

* **The first lap.**  Twenty cars arriving at the first corner together is
  where a disproportionate share of a season's contact happens.  No amount of
  per-lap averaging reproduces that, so it is a term.
* **Who is fighting.**  Racecraft and risk management, from both cars.  A
  driver who is good at this makes contact less likely for *both* of them, and
  a driver who is not raises it for both.

What contact costs is drawn separately from whether it happened, because they
are separate questions: most contact is a broken front wing, some of it ends a
race, and some of it leaves something on the circuit that has to be recovered.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..core.config import IncidentConfig
from ..core.interpolation import clamp
from ..core.rng import RandomStream
from ..core.units import Metres
from .incident import Incident, IncidentKind, IncidentSeverity

__all__ = ["ContactRisk", "contact_probability", "sample_contact"]


@dataclass(frozen=True, slots=True)
class ContactRisk:
    """Everything that decides how likely contact is for one car on one lap."""

    laps_in_combat: float = 0.0
    """Laps, or fraction of one, spent within fighting distance."""

    first_lap: bool = False
    attacker_skill: float = 0.9
    """Racecraft and risk management of the car at risk, 0 to 1."""

    rival_skill: float = 0.9
    """The same for whoever it is fighting.  Contact takes two."""

    track_width: Metres = 13.0
    """Usable width where the fighting is happening, m.  A narrow circuit
    leaves nowhere to go, which is why street races have more contact."""

    reference_width: Metres = 13.0


def contact_probability(
    risk: ContactRisk, config: IncidentConfig | None = None
) -> float:
    """Chance of contact over the exposure described by ``risk``."""
    cfg = config or IncidentConfig()
    if risk.laps_in_combat <= 0.0:
        return 0.0

    # Both drivers matter, so the pair is what scales the risk.
    skill = 0.5 * (clamp(risk.attacker_skill, 0.0, 1.0) + clamp(risk.rival_skill, 0.0, 1.0))
    skill_factor = 1.0 - cfg.racecraft_range * skill

    width = max(risk.track_width, 1.0)
    width_factor = clamp(risk.reference_width / width, 0.5, 2.5)

    rate = cfg.combat_contact_rate * skill_factor * width_factor
    if risk.first_lap:
        rate *= cfg.first_lap_multiplier
    return clamp(rate * risk.laps_in_combat, 0.0, 1.0)


def sample_contact(
    stream: RandomStream,
    risk: ContactRisk,
    *,
    car_number: int,
    lap: int,
    rival: int | None = None,
    distance: Metres = 0.0,
    config: IncidentConfig | None = None,
) -> Incident | None:
    """Draw whether this car made contact, and how badly."""
    cfg = config or IncidentConfig()
    probability = contact_probability(risk, cfg)
    if probability <= 0.0 or not stream.derive("contact").chance(probability):
        return None

    roll = stream.derive("outcome").random()
    if roll < cfg.blocking_share:
        severity = IncidentSeverity.BLOCKING
        damage = 1.0
        description = "contact, car stopped on the circuit"
    elif roll < cfg.blocking_share + cfg.retirement_share:
        severity = IncidentSeverity.RETIREMENT
        damage = 1.0
        description = "contact, retired"
    else:
        severity = IncidentSeverity.DAMAGE
        damage = stream.derive("damage").uniform(0.25, 1.0)
        description = "contact, damage"

    # A car that drives away from contact often leaves part of itself behind,
    # and that has to be picked up whether or not anybody retired.  It is the
    # most common reason a modern race is neutralised.
    debris = severity is not IncidentSeverity.MINOR and stream.derive("debris").chance(
        cfg.debris_share if severity is IncidentSeverity.DAMAGE else 1.0
    )

    return Incident(
        kind=IncidentKind.COLLISION,
        severity=severity,
        car_number=car_number,
        lap=lap,
        distance=distance,
        involved=() if rival is None else (rival,),
        damage=damage,
        debris=debris,
        description=description,
    )


def sample_spin(
    stream: RandomStream,
    *,
    car_number: int,
    lap: int,
    mistakes: int,
    risk_management: float = 0.9,
    distance: Metres = 0.0,
    time_lost: float = 0.0,
    config: IncidentConfig | None = None,
) -> Incident | None:
    """Draw whether a driver's mistake became a spin or an excursion.

    The mistakes themselves come from the driver model, which already knows how
    often this driver has one.  What is decided here is only whether a given
    one went far enough to matter to the race rather than just to the lap --
    and how likely that is depends on what the driver does when it starts to go
    wrong, which is what risk management is.
    """
    cfg = config or IncidentConfig()
    if mistakes <= 0:
        return None
    per_mistake = cfg.spin_rate * (1.0 - 0.6 * clamp(risk_management, 0.0, 1.0))
    chance = 1.0 - (1.0 - clamp(per_mistake, 0.0, 1.0)) ** mistakes
    if not stream.derive("spin").chance(chance):
        return None

    roll = stream.derive("spin_outcome").random()
    if roll < 0.10:
        severity = IncidentSeverity.BLOCKING
        description = "spun and beached"
        lost = 0.0
    elif roll < 0.16:
        severity = IncidentSeverity.RETIREMENT
        description = "off, into the barrier"
        lost = 0.0
    else:
        severity = IncidentSeverity.MINOR
        description = "a spin"
        lost = max(time_lost, stream.derive("spin_time").uniform(4.0, 14.0))
    return Incident(
        kind=IncidentKind.DRIVER_ERROR,
        severity=severity,
        car_number=car_number,
        lap=lap,
        distance=distance,
        time_lost=lost,
        description=description,
    )
