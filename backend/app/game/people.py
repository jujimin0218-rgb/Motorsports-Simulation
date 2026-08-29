"""Drivers, and the contracts that hold them.

The race engine already has a driver model, with ten attributes it uses to turn
ability into lap time.  This does not replace it and does not shadow it.  A
:class:`DriverProfile` is the *career* around one of those drivers: an age, a
contract, a reputation, a run of form, and how much better they might still
get.  :meth:`DriverProfile.to_engine_driver` builds the engine's own
:class:`~f1_race_engine.driver.Driver` when a session needs one, so there is
exactly one driver model in the project and it is the engine's.

Six of the eleven ratings here carry the same names as the engine's attributes
and are handed straight across.  The other five exist because the engine has
nowhere to put them:

``overtaking`` / ``defending``
    The engine settles a fight with one ``racecraft`` number for both roles.  A
    manager game wants to tell a driver who never loses a place from one who
    never takes one, so the two are stored apart and folded back into the
    engine's single number according to which side of the fight the driver is
    on.

``starts``
    The engine models a standing start from grid position and reaction time.
    This is what a driver is worth in that first hundred metres.

``feedback``
    Nothing to do with driving: how much a driver's debrief is worth to the
    factory.  It pays off in development, not on Sunday.

``mentality``
    How a driver holds up when the season is going badly, and what happens to
    their form after a bad weekend.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from f1_race_engine.driver import Driver, DriverAttributes

from .errors import InvalidDriver

__all__ = [
    "Contract",
    "DriverProfile",
    "ENGINE_SKILLS",
    "GAME_SKILLS",
    "SKILL_NAMES",
]

#: Handed to the race engine unchanged.
ENGINE_SKILLS: tuple[str, ...] = (
    "pace",
    "qualifying",
    "racecraft",
    "consistency",
    "tyre_management",
    "wet_skill",
)

#: The management layer's own.  See the module docstring for why each exists.
GAME_SKILLS: tuple[str, ...] = (
    "overtaking",
    "defending",
    "starts",
    "feedback",
    "mentality",
)

SKILL_NAMES: tuple[str, ...] = ENGINE_SKILLS + GAME_SKILLS


def _blend(*values: float) -> float:
    return sum(values) / len(values)


@dataclass(slots=True)
class Contract:
    """What a driver is paid, and what it would take to get them out of it.

    All money is in millions.
    """

    salary: float = 5.0
    seasons_remaining: int = 1
    signing_bonus: float = 0.0
    performance_bonus: float = 0.0
    """Paid per points-scoring finish, so a cheap driver who scores is not
    free."""

    release_clause: float = 0.0
    """What another team must pay to take them mid-contract.  Zero means the
    driver cannot be bought out at all."""

    @property
    def expires_this_season(self) -> bool:
        return self.seasons_remaining <= 1

    def advance_season(self) -> None:
        self.seasons_remaining = max(0, self.seasons_remaining - 1)

    def to_dict(self) -> dict[str, Any]:
        return {
            "salary": self.salary,
            "seasons_remaining": self.seasons_remaining,
            "signing_bonus": self.signing_bonus,
            "performance_bonus": self.performance_bonus,
            "release_clause": self.release_clause,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Contract:
        return cls(
            salary=float(data.get("salary", 5.0)),
            seasons_remaining=int(data.get("seasons_remaining", 1)),
            signing_bonus=float(data.get("signing_bonus", 0.0)),
            performance_bonus=float(data.get("performance_bonus", 0.0)),
            release_clause=float(data.get("release_clause", 0.0)),
        )


@dataclass(slots=True)
class DriverProfile:
    """One driver's career."""

    id: str
    name: str
    abbreviation: str = "DRV"
    nationality: str = ""
    age: int = 25
    skills: dict[str, float] = field(default_factory=dict)
    potential: float = 0.85
    """The ceiling.  A young driver below it improves; nobody passes it."""

    experience: float = 0.5
    reputation: float = 0.5
    form: float = 0.0
    """Recent results, -1 to +1.

    A short-run modifier on pace and qualifying, not a permanent change.  It
    moves slowly on purpose: a season in which one bad Sunday costs a driver
    half a second for the rest of the year is not a season anybody enjoys."""

    team: str | None = None
    contract: Contract | None = None
    retired: bool = False

    def __post_init__(self) -> None:
        if not self.id:
            raise InvalidDriver("a driver needs an id")
        for name in SKILL_NAMES:
            self.skills.setdefault(name, 0.75)

    # -- identity ------------------------------------------------------------

    @property
    def is_free_agent(self) -> bool:
        return self.team is None and not self.retired

    def skill(self, name: str) -> float:
        if name not in SKILL_NAMES:
            raise InvalidDriver(f"unknown skill {name!r}")
        return float(self.skills[name])

    @property
    def overall(self) -> float:
        """A single number, for sorting a list of drivers and nothing else."""
        return sum(self.skill(name) for name in SKILL_NAMES) / len(SKILL_NAMES)

    @property
    def market_value(self) -> float:
        """Roughly what this driver is worth a season, in millions.

        Steeply convex in ability, because the market is: the difference
        between a good driver and a great one is worth far more than the
        difference between an average one and a good one.
        """
        base = 0.55 * self.overall + 0.30 * self.reputation + 0.15 * self.potential
        return round(2.0 + 40.0 * base**6, 2)

    # -- the bridge to the race engine ---------------------------------------

    def to_engine_driver(self, *, attacking: bool = True) -> Driver:
        """Build the engine's own driver object.

        ``attacking`` decides which side of ``racecraft`` this driver is shown
        as: the engine settles a fight with one number, so an attacker is rated
        on their overtaking and a defender on their defending, with the stored
        ``racecraft`` as the base either way.

        Form moves pace, qualifying and consistency and nothing else.  It is a
        run of results, not a change to the driver.
        """
        pace = self._with_form("pace")
        consistency = self._with_form("consistency")
        edge = self.skill("overtaking") if attacking else self.skill("defending")
        racecraft = _blend(self.skill("racecraft"), edge)
        return Driver(
            name=self.name,
            abbreviation=self.abbreviation,
            team=self.team or "",
            attributes=DriverAttributes(
                pace=pace,
                qualifying=self._with_form("qualifying"),
                racecraft=racecraft,
                consistency=consistency,
                tyre_management=self.skill("tyre_management"),
                wet_skill=self.skill("wet_skill"),
                # The engine's remaining four are facets of what is stored
                # here rather than separate ratings: a driver good enough to
                # brake late is good enough on pace, and one who looks after a
                # tyre is smooth on the throttle.  Deriving them keeps one
                # source of truth per ability.
                braking=_blend(pace, self.skill("overtaking")),
                cornering=_blend(pace, consistency),
                throttle_control=_blend(consistency, self.skill("tyre_management")),
                risk_management=_blend(self.skill("mentality"), consistency),
            ),
            metadata={"driver_id": self.id, "nationality": self.nationality},
        )

    def _with_form(self, name: str) -> float:
        """One skill, nudged by form.

        Capped at 4% either way.  In equal machinery the whole Formula 1 field
        lives inside about 1% of lap time, so a form swing worth more than that
        would drown out the drivers themselves.
        """
        return min(0.99, max(0.30, self.skill(name) + 0.04 * self.form))

    # -- persistence ---------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "abbreviation": self.abbreviation,
            "nationality": self.nationality,
            "age": self.age,
            "skills": {name: round(self.skill(name), 6) for name in SKILL_NAMES},
            "potential": self.potential,
            "experience": self.experience,
            "reputation": self.reputation,
            "form": self.form,
            "team": self.team,
            "contract": None if self.contract is None else self.contract.to_dict(),
            "retired": self.retired,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DriverProfile:
        contract = data.get("contract")
        return cls(
            id=str(data["id"]),
            name=str(data.get("name", data["id"])),
            abbreviation=str(data.get("abbreviation", "DRV")),
            nationality=str(data.get("nationality", "")),
            age=int(data.get("age", 25)),
            skills={
                name: float(data.get("skills", {}).get(name, 0.75))
                for name in SKILL_NAMES
            },
            potential=float(data.get("potential", 0.85)),
            experience=float(data.get("experience", 0.5)),
            reputation=float(data.get("reputation", 0.5)),
            form=float(data.get("form", 0.0)),
            team=data.get("team"),
            contract=None if contract is None else Contract.from_dict(contract),
            retired=bool(data.get("retired", False)),
        )
