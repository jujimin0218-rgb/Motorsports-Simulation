"""Turning a team's car rating into a car the physics can drive.

This is the whole of the integration, and the rule it follows is the one the
race engine itself follows: **nothing here is a lap-time bonus.**  Every rating
is spent on a physical property of the car, and the engine works out what that
is worth -- which is why a good aerodynamic department is worth more at
Silverstone than at Monza without anybody writing that down.

Each of the six areas buys exactly the thing it is named after:

``aero``
    Aerodynamic *efficiency*: more downforce area, and less induced drag for
    it.  A better wing is not a bigger wing.

``power_unit``
    Engine power and deployment, combined with what the supplier makes.  A
    customer of a strong manufacturer starts ahead of a works team with a
    weak one.

``chassis``
    Mass.  Everybody is chasing the same minimum weight and the good teams get
    closer to it; the engine already charges mass through the force balance, so
    a lighter car is quicker everywhere and quickest where it has to change
    direction.

``mechanical_grip``
    Centre-of-gravity height and track width -- which is not an analogy.  Those
    two numbers are what set lateral load transfer in the engine's grip model,
    and lateral load transfer is what mechanical grip *is*.

``tyre_management``
    How much wear the car does for the same work, through the tyre model's own
    reference wear energy.  A car that is kind to its tyres makes a one-stop
    possible where a harsh one has to stop twice.

``reliability``
    The per-distance failure rates in the engine's reliability model, together
    with the supplier's.  Not a chance of a DNF: a hazard rate, which is what
    makes a long race at a hot circuit genuinely riskier.

The spans below are calibrated, not chosen: ``backend/scripts/calibrate_spread.py``
runs the whole grid round three circuits and reports what they are worth.  A
Formula 1 field spans roughly two to three per cent of lap time between the
quickest car and the slowest, with a couple of tenths between the top two, and
the shipped grid comes out at

.. code-block:: text

    Monza        2.24 s   2.14%   top two split 0.31 s
    Silverstone  1.99 s   2.26%   top two split 0.22 s
    Monaco       1.82 s   2.40%   top two split 0.08 s

which is that.  Note that the *order* changes between them and nobody arranged
it: it falls out of what each circuit asks of a car meeting what each car is
good at.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from f1_race_engine.core.config import SimulationConfig, default_config
from f1_race_engine.vehicle import Vehicle, VehicleSetup, VehicleSpec
from f1_race_engine.vehicle.io import load_builtin_vehicle

from ..game.car import EngineSupplier
from ..game.team import Team

__all__ = ["BASE_VEHICLE", "build_config", "build_vehicle", "build_vehicle_spec"]

#: The car every team's is a variation of.  One base spec rather than one per
#: team keeps the physics honest: two teams differ by the numbers below and by
#: nothing hidden.
BASE_VEHICLE = "reference_2024"

#: The rating a base car corresponds to.  A team on this number gets the
#: engine's reference car unchanged, and the rest are scaled either side of it.
REFERENCE_RATING = 0.85

# -- how far each area moves the car ------------------------------------------
# All of these are "per unit of rating away from the reference", so a team 0.10
# above the reference gets a tenth of each span.

#: Downforce area, as a fraction.  A full unit of aero rating is worth 30% more
#: downforce -- which nobody has, since the field lives inside about 0.2.
AERO_AREA_SPAN = 0.53

#: Induced drag, as a fraction.  Negative because efficiency means *less* drag
#: for the same downforce; this is the half that makes aero worth having on a
#: power circuit as well as a downforce one.
AERO_EFFICIENCY_SPAN = 0.42

#: Engine power, as a fraction.
POWER_SPAN = 0.26

#: Chassis mass, in kg per unit of rating.  Negative direction: better is
#: lighter.  The regulations set a minimum weight everybody is chasing, so the
#: whole field is within a few tens of kilos of it.
CHASSIS_MASS_SPAN = 63.0

#: Centre of gravity, in metres per unit of rating.  Lower is better.
CG_HEIGHT_SPAN = 0.105

#: Track width, in metres per unit of rating.  Wider is better, and the
#: regulations cap it, so the span is small.
TRACK_WIDTH_SPAN = 0.21

#: Tyre wear energy, as a fraction.  Higher means the same work wears the tyre
#: less, which is what a car being kind to its tyres means.
TYRE_WEAR_SPAN = 0.45

#: Failure rates, as a fraction.  A full unit of reliability rating removes 70%
#: of the hazard.
RELIABILITY_SPAN = 0.70


def _delta(rating: float) -> float:
    """How far this rating is from the reference car."""
    return float(rating) - REFERENCE_RATING


def build_vehicle_spec(
    team: Team,
    supplier: EngineSupplier | None = None,
    *,
    base: VehicleSpec | None = None,
) -> VehicleSpec:
    """The car this team turns up with."""
    spec = base if base is not None else load_builtin_vehicle(BASE_VEHICLE)
    car = team.car

    # Aerodynamics: more area, and less drag per unit of it.
    aero_delta = _delta(car.aero)
    area_scale = 1.0 + AERO_AREA_SPAN * aero_delta
    drag_scale = 1.0 - AERO_EFFICIENCY_SPAN * aero_delta
    aero = replace(
        spec.aero,
        min_downforce_area=spec.aero.min_downforce_area * area_scale,
        max_downforce_area=spec.aero.max_downforce_area * area_scale,
        induced_drag_factor=spec.aero.induced_drag_factor * max(drag_scale, 0.4),
    )

    # Mass and geometry: a better chassis is lighter, and a car with more
    # mechanical grip carries its weight lower and wider.
    grip_delta = _delta(car.mechanical_grip)
    mass = replace(
        spec.mass,
        chassis_mass=spec.mass.chassis_mass - CHASSIS_MASS_SPAN * _delta(car.chassis),
        cg_height=max(0.15, spec.mass.cg_height - CG_HEIGHT_SPAN * grip_delta),
        track_width=spec.mass.track_width + TRACK_WIDTH_SPAN * grip_delta,
    )

    # Power: the team's own installation and the manufacturer's engine, which
    # is why a customer of a strong supplier can beat a works team of a weak
    # one.  The supplier's rating is measured against the same reference.
    power_delta = _delta(car.power_unit)
    if supplier is not None:
        power_delta += _delta(supplier.power_rating)
    power_unit = replace(
        spec.power_unit, max_power=spec.power_unit.max_power * (1.0 + POWER_SPAN * power_delta)
    )
    ers = spec.ers
    if supplier is not None:
        ers = replace(
            ers,
            max_deploy_power=ers.max_deploy_power
            * (1.0 + POWER_SPAN * _delta(supplier.kers_output)),
        )

    return replace(
        spec,
        name=f"{team.name} {BASE_VEHICLE}",
        team=team.name,
        aero=aero,
        mass=mass,
        power_unit=power_unit,
        ers=ers,
        metadata={**spec.metadata, "team_id": team.id},
    )


def build_config(
    team: Team,
    supplier: EngineSupplier | None = None,
    *,
    base: SimulationConfig | None = None,
) -> SimulationConfig:
    """The simulation settings this team's car runs under.

    Two of the six areas are properties of how the car *behaves over a race*
    rather than of its shape, and the engine already models both as
    configuration: how hard it works its tyres, and how often it breaks.  Each
    car therefore carries its own config rather than the shared default.
    """
    config = base if base is not None else default_config()

    wear = config.tyre_wear
    wear = replace(
        wear,
        reference_wear_energy=wear.reference_wear_energy
        * (1.0 + TYRE_WEAR_SPAN * _delta(team.car.tyre_management)),
    )

    # Reliability is the car's and the engine's together: a fragile power unit
    # ends a race as surely as a fragile gearbox.
    reliability_delta = _delta(team.car.reliability)
    engine_delta = _delta(supplier.reliability) if supplier is not None else 0.0
    car_factor = max(0.15, 1.0 - RELIABILITY_SPAN * reliability_delta)
    engine_factor = max(0.15, 1.0 - RELIABILITY_SPAN * engine_delta)
    rel = config.reliability
    rel = replace(
        rel,
        # The power unit answers to the manufacturer; everything else is the
        # team's own build.
        power_unit_rate=rel.power_unit_rate * engine_factor,
        cooling_rate=rel.cooling_rate * engine_factor,
        gearbox_rate=rel.gearbox_rate * car_factor,
        hydraulics_rate=rel.hydraulics_rate * car_factor,
        brake_rate=rel.brake_rate * car_factor,
        suspension_rate=rel.suspension_rate * car_factor,
    )
    return replace(config, tyre_wear=wear, reliability=rel)


def build_vehicle(
    team: Team,
    supplier: EngineSupplier | None = None,
    *,
    setup: VehicleSetup | None = None,
    base: VehicleSpec | None = None,
    base_config: SimulationConfig | None = None,
) -> Vehicle:
    """A car ready to be handed to the race engine."""
    return Vehicle(
        build_vehicle_spec(team, supplier, base=base),
        setup or VehicleSetup(),
        build_config(team, supplier, base=base_config),
    )


def describe(team: Team, supplier: EngineSupplier | None = None) -> dict[str, Any]:
    """What this team's ratings did to the car, for a debug screen."""
    spec = build_vehicle_spec(team, supplier)
    base = load_builtin_vehicle(BASE_VEHICLE)
    return {
        "team": team.id,
        "downforce_area": round(spec.aero.max_downforce_area, 4),
        "downforce_area_vs_base": round(
            spec.aero.max_downforce_area / base.aero.max_downforce_area, 4
        ),
        "induced_drag_vs_base": round(
            spec.aero.induced_drag_factor / base.aero.induced_drag_factor, 4
        ),
        "chassis_mass": round(spec.mass.chassis_mass, 2),
        "cg_height": round(spec.mass.cg_height, 4),
        "track_width": round(spec.mass.track_width, 4),
        "max_power_kw": round(spec.power_unit.max_power / 1000.0, 1),
        "max_power_vs_base": round(
            spec.power_unit.max_power / base.power_unit.max_power, 4
        ),
    }
