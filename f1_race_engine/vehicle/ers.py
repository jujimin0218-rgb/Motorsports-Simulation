"""Energy recovery (project rule 24).

    "ERS는 단순히 '랩타임 -0.5초' 방식으로 구현하지 않는다."

So it is not a lap-time bonus.  It is an energy store with a capacity, a
per-lap deployment budget and a harvest rate, and the reason it is interesting
is that it **runs out**.  A car that deploys everything down the first straight
has nothing left for the last one, and the lap time that comes out reflects
that on its own.

Three limits, all of them real regulations:

* the store holds a fixed amount of energy;
* only so much may be deployed per lap;
* only so much may be harvested per lap, and only under braking.

Phase 5 deploys greedily -- full power whenever the car is accelerating and
fast enough for the extra torque to reach the road.  Phase 8 replaces that
policy with a strategic one; the energy accounting underneath does not change.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..core.config import ErsConfig
from ..core.errors import ConfigError
from ..core.state import MutableState
from ..core.units import Joules, Seconds, Watts

__all__ = [
    "ErsProperties",
    "ErsState",
    "deploy_power",
    "harvest_power",
    "thermal_harvest_power",
]


@dataclass(frozen=True, slots=True)
class ErsProperties:
    """A car's energy recovery system."""

    max_deploy_power: Watts = 120_000.0
    """Peak electrical power to the wheels, W.  The MGU-K limit."""

    max_harvest_power: Watts = 120_000.0
    """Peak recovery power under braking, W."""

    capacity: Joules = 4.0e6
    """Usable energy store, J."""

    deployment_limit_per_lap: Joules = 4.0e6
    """Maximum electrical energy deployable in one lap, J."""

    harvest_limit_per_lap: Joules = 2.0e6
    """Maximum recoverable from the brakes in one lap, J."""

    max_thermal_harvest_power: Watts = 45_000.0
    """Peak recovery from exhaust energy, W.

    A second, quite different recovery path: it runs while the car is on the
    throttle rather than off it, and the regulations put no per-lap limit on it.
    That asymmetry is why a car can deploy more energy per lap than its brakes
    could ever recover, and why a circuit with long full-throttle sections
    recharges as well as one with heavy braking."""

    def __post_init__(self) -> None:
        for name in ("max_deploy_power", "max_harvest_power", "capacity"):
            if getattr(self, name) <= 0.0:
                raise ConfigError(f"ers {name} must be positive")
        if self.max_thermal_harvest_power < 0.0:
            raise ConfigError("ers max_thermal_harvest_power must be non-negative")
        if self.deployment_limit_per_lap <= 0.0:
            raise ConfigError("ers deployment_limit_per_lap must be positive")
        if self.harvest_limit_per_lap < 0.0:
            raise ConfigError("ers harvest_limit_per_lap must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_deploy_power": self.max_deploy_power,
            "max_harvest_power": self.max_harvest_power,
            "capacity": self.capacity,
            "deployment_limit_per_lap": self.deployment_limit_per_lap,
            "harvest_limit_per_lap": self.harvest_limit_per_lap,
            "max_thermal_harvest_power": self.max_thermal_harvest_power,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ErsProperties:
        unknown = set(data) - set(cls.__slots__)
        if unknown:
            raise ConfigError(f"unknown ers key(s): {', '.join(sorted(unknown))}")
        return cls(**data)


@dataclass
class ErsState(MutableState):
    """How much energy is in the store and what has been used this lap."""

    energy_remaining: Joules = 4.0e6
    deployed_this_lap: Joules = 0.0
    harvested_this_lap: Joules = 0.0
    """Recovered from the brakes this lap, J.  This is the budgeted one."""

    thermal_this_lap: Joules = 0.0
    """Recovered from the exhaust this lap, J.  Not budgeted."""

    recovered_last_lap: Joules = 0.0
    """Everything recovered on the previous lap, J.

    Kept because it is the honest answer to "how much can be spent this lap":
    over a stint a car can only deploy what it recovers."""

    deployed_total: Joules = 0.0
    harvested_total: Joules = 0.0
    thermal_total: Joules = 0.0

    @property
    def recovered_this_lap(self) -> Joules:
        return self.harvested_this_lap + self.thermal_this_lap

    @property
    def recovered_total(self) -> Joules:
        return self.harvested_total + self.thermal_total

    def start_lap(self) -> None:
        """Reset the per-lap budgets.  The store itself carries over."""
        self.recovered_last_lap = self.recovered_this_lap
        self.deployed_this_lap = 0.0
        self.harvested_this_lap = 0.0
        self.thermal_this_lap = 0.0

    def snapshot(self) -> dict[str, Any]:
        return {
            "energy_remaining": self.energy_remaining,
            "deployed_this_lap": self.deployed_this_lap,
            "harvested_this_lap": self.harvested_this_lap,
            "thermal_this_lap": self.thermal_this_lap,
            "recovered_last_lap": self.recovered_last_lap,
            "deployed_total": self.deployed_total,
            "harvested_total": self.harvested_total,
            "thermal_total": self.thermal_total,
        }

    def state_of_charge(self, properties: ErsProperties) -> float:
        return self.energy_remaining / properties.capacity

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"ErsState({self.energy_remaining / 1e6:.2f} MJ, "
            f"deployed {self.deployed_this_lap / 1e6:.2f} MJ this lap)"
        )


def deploy_power(
    state: ErsState,
    properties: ErsProperties,
    *,
    speed: float,
    dt: Seconds,
    request: float = 1.0,
    config: ErsConfig | None = None,
) -> Watts:
    """Electrical power available to the wheels right now, W.

    Mutates ``state``: whatever is returned has been debited from the store and
    from the lap's budget.  Returns zero once either runs out, which is what
    makes deployment a decision with a consequence.
    """
    cfg = config or ErsConfig()
    if dt <= 0.0 or request <= 0.0 or speed < cfg.minimum_deploy_speed:
        return 0.0

    lap_remaining = properties.deployment_limit_per_lap - state.deployed_this_lap
    available = min(state.energy_remaining, max(lap_remaining, 0.0))
    if available <= 0.0:
        return 0.0

    power = properties.max_deploy_power * min(request, 1.0)
    energy = min(power * dt, available)
    state.energy_remaining -= energy
    state.deployed_this_lap += energy
    state.deployed_total += energy
    return energy * cfg.deployment_efficiency / dt


def harvest_power(
    state: ErsState,
    properties: ErsProperties,
    *,
    braking_power: Watts,
    dt: Seconds,
    config: ErsConfig | None = None,
) -> Watts:
    """Recover energy from braking, W.

    Mutates ``state``.  Capped by the harvest power limit, the lap's harvest
    budget and the space left in the store -- a full battery cannot recover, and
    that is a real constraint at circuits with heavy braking.
    """
    cfg = config or ErsConfig()
    if dt <= 0.0 or braking_power <= 0.0:
        return 0.0

    lap_remaining = properties.harvest_limit_per_lap - state.harvested_this_lap
    space = properties.capacity - state.energy_remaining
    room = min(max(lap_remaining, 0.0), max(space, 0.0))
    if room <= 0.0:
        return 0.0

    power = min(braking_power, properties.max_harvest_power)
    energy = min(power * dt * cfg.harvest_efficiency, room)
    state.energy_remaining += energy
    state.harvested_this_lap += energy
    state.harvested_total += energy
    return energy / dt


def thermal_harvest_power(
    state: ErsState,
    properties: ErsProperties,
    *,
    engine_power: Watts,
    dt: Seconds,
    config: ErsConfig | None = None,
) -> Watts:
    """Recover exhaust energy while the engine is working, W.

    Mutates ``state``.  The share of engine power that reaches the store is a
    property of the turbine, and unlike braking recovery the regulations set no
    per-lap ceiling on it -- so this is what actually keeps a car deploying lap
    after lap.  Only the store's own capacity stops it.
    """
    cfg = config or ErsConfig()
    if dt <= 0.0 or engine_power <= 0.0 or properties.max_thermal_harvest_power <= 0.0:
        return 0.0

    space = properties.capacity - state.energy_remaining
    if space <= 0.0:
        return 0.0

    power = min(
        engine_power * cfg.thermal_recovery_fraction,
        properties.max_thermal_harvest_power,
    )
    energy = min(power * dt, space)
    state.energy_remaining += energy
    state.thermal_this_lap += energy
    state.thermal_total += energy
    return energy / dt
