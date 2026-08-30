"""The seam where a team's ratings become a car the physics can drive.

The rule this layer lives or dies by: a rating buys a *physical property*, and
the engine decides what that is worth.  If any of these tests could pass with a
lap-time bonus instead, the test is the wrong test.
"""

from __future__ import annotations

import pytest

from f1_race_engine.physics import compute_lap_time
from f1_race_engine.track.io import load_track
from f1_race_engine.vehicle import VehicleSetup
from f1_race_engine.vehicle.io import load_builtin_vehicle

from app.adapters.car_builder import (
    BASE_VEHICLE,
    REFERENCE_RATING,
    build_config,
    build_vehicle,
    build_vehicle_spec,
)
from app.game.car import CarPerformance, EngineSupplier
from app.game.team import Team


def team_with(**areas: float) -> Team:
    return Team(id="t", name="T", car=CarPerformance(**{
        **{name: REFERENCE_RATING for name in CarPerformance().to_dict()},
        **areas,
    }))


def test_a_team_on_the_reference_rating_gets_the_reference_car():
    """The base car is the anchor: a team rated at the reference number gets it
    unchanged, so every difference in the field is one of the spans below and
    nothing hidden."""
    base = load_builtin_vehicle(BASE_VEHICLE)
    spec = build_vehicle_spec(team_with())
    assert spec.aero.max_downforce_area == pytest.approx(base.aero.max_downforce_area)
    assert spec.mass.chassis_mass == pytest.approx(base.mass.chassis_mass)
    assert spec.power_unit.max_power == pytest.approx(base.power_unit.max_power)
    assert spec.mass.cg_height == pytest.approx(base.mass.cg_height)


def test_aero_buys_efficiency_not_just_area():
    """A better wing is not a bigger wing.  More downforce *and* less induced
    drag for it is what an aerodynamic department actually produces, and it is
    why aero is worth having on a power circuit too."""
    good = build_vehicle_spec(team_with(aero=0.95)).aero
    poor = build_vehicle_spec(team_with(aero=0.70)).aero
    assert good.max_downforce_area > poor.max_downforce_area
    assert good.induced_drag_factor < poor.induced_drag_factor


def test_chassis_buys_lightness():
    assert (
        build_vehicle_spec(team_with(chassis=0.95)).mass.chassis_mass
        < build_vehicle_spec(team_with(chassis=0.70)).mass.chassis_mass
    )


def test_mechanical_grip_buys_the_two_numbers_that_set_load_transfer():
    """Not an analogy.  Centre-of-gravity height and track width are what the
    engine's grip model uses to compute lateral load transfer, and lateral load
    transfer is what mechanical grip is."""
    good = build_vehicle_spec(team_with(mechanical_grip=0.95)).mass
    poor = build_vehicle_spec(team_with(mechanical_grip=0.70)).mass
    assert good.cg_height < poor.cg_height
    assert good.track_width > poor.track_width


def test_power_comes_from_the_team_and_the_manufacturer_together():
    """A customer of a strong supplier can beat a works team of a weak one,
    which is the trade the midfield actually makes."""
    strong = EngineSupplier(id="s", name="S", ice_output=0.98, kers_output=0.98)
    weak = EngineSupplier(id="w", name="W", ice_output=0.72, kers_output=0.72)
    good_car_weak_engine = build_vehicle_spec(team_with(power_unit=0.92), weak)
    poor_car_strong_engine = build_vehicle_spec(team_with(power_unit=0.78), strong)
    assert (
        poor_car_strong_engine.power_unit.max_power
        > good_car_weak_engine.power_unit.max_power
    )


def test_tyre_management_and_reliability_go_into_the_config_not_the_shape():
    """Both are things a car does over a race rather than properties of its
    shape, and the engine already models both as configuration."""
    from f1_race_engine.core.config import default_config

    base = default_config()
    kind = build_config(team_with(tyre_management=0.95))
    harsh = build_config(team_with(tyre_management=0.70))
    assert (
        kind.tyre_wear.reference_wear_energy
        > base.tyre_wear.reference_wear_energy
        > harsh.tyre_wear.reference_wear_energy
    )

    solid = build_config(team_with(reliability=0.95))
    fragile = build_config(team_with(reliability=0.70))
    assert solid.reliability.gearbox_rate < fragile.reliability.gearbox_rate


def test_the_engine_supplier_owns_the_power_unit_failures():
    """A fragile engine is the manufacturer's, a fragile gearbox is the
    team's -- which is what makes an engine deal a real decision."""
    good_engine = EngineSupplier(id="a", name="A", reliability=0.97)
    bad_engine = EngineSupplier(id="b", name="B", reliability=0.72)
    solid = build_config(team_with(reliability=0.90), good_engine).reliability
    fragile = build_config(team_with(reliability=0.90), bad_engine).reliability
    assert solid.power_unit_rate < fragile.power_unit_rate
    # The team's own build is identical in both, so the gearbox is not affected.
    assert solid.gearbox_rate == pytest.approx(fragile.gearbox_rate)


# -- what it is worth on the road --------------------------------------------


def test_a_better_car_is_actually_quicker():
    """The whole chain, end to end: ratings -> physical car -> a lap time the
    engine computed from a force balance."""
    track = load_track("synthetic_proving_ground")
    setup = VehicleSetup(wing_level=0.65)

    def lap(rating: float) -> float:
        team = Team(id="t", name="T", car=CarPerformance(
            **{name: rating for name in CarPerformance().to_dict()}
        ))
        car = build_vehicle(team, setup=setup)
        return compute_lap_time(track, car, mass=car.total_mass(35.0)).lap_time

    quick, slow = lap(0.93), lap(0.74)
    assert quick < slow


def test_the_field_spread_is_the_one_a_real_field_has():
    """Two to three per cent front to back is what Formula 1 runs at.  Much
    less and the championship is a coin toss; much more and the midfield is
    scenery."""
    from app.game.newgame import new_game

    game = new_game(player_team="harrow", seed=1)
    track = load_track("synthetic_proving_ground")
    setup = VehicleSetup(wing_level=0.65)
    times = []
    for team in game.teams.values():
        car = build_vehicle(team, game.engine_for(team.id), setup=setup)
        times.append(compute_lap_time(track, car, mass=car.total_mass(35.0)).lap_time)
    times.sort()
    spread = (times[-1] / times[0]) - 1.0
    assert 0.015 < spread < 0.035, f"field spread {100 * spread:.2f}%"
    # And the top two are close, as they are in a real season.
    assert (times[1] / times[0]) - 1.0 < 0.006


def test_a_circuit_rewards_the_car_that_suits_it():
    """The point of keeping performance per area: a circuit that asks for power
    has to reward the car that has it, and one that asks for downforce must not.

    An ordering flip is the visible version of this, and it used to be what this
    test asserted -- but it is a brittle thing to assert.  Whether two cars swap
    depends on how close they happened to be, not on whether the circuit
    discriminates, and when Monza stopped being a synthetic caricature and
    became the real measured circuit the flip went away while the
    discrimination did not: real Monza has two tight chicanes and asks rather
    more of a car than a track designed to be nothing but straights.

    So this measures the discrimination itself.  Take the field's two
    best-matched opposites -- Apex, which is strong in aero and weak in power,
    against Scuderia Lucente, which is the reverse at nearly the same overall
    level -- and watch the gap between them across circuits.  It is normalised
    by the field's spread at each circuit, because a longer lap spreads every
    gap and that would otherwise be read as circuit character.
    """
    from app.game.newgame import new_game

    game = new_game(player_team="harrow", seed=1)

    def normalised_gap(circuit_id: str, wing: float) -> float:
        track = load_track(game.calendar.circuit(circuit_id).physics_track)
        times = {}
        for team in game.teams.values():
            car = build_vehicle(
                team, game.engine_for(team.id), setup=VehicleSetup(wing_level=wing)
            )
            times[team.id] = compute_lap_time(
                track, car, mass=car.total_mass(35.0)
            ).lap_time
        spread = max(times.values()) - min(times.values())
        return (times["scuderia_lucente"] - times["apex_gp"]) / spread

    # Monza is the calendar's least downforce-dependent circuit and the
    # Hungaroring its most, so the power car should give away least at the one
    # and most at the other.
    at_monza = normalised_gap("autodromo_nazionale_monza", 0.30)
    at_hungaroring = normalised_gap("hungaroring", 0.95)

    assert at_monza < at_hungaroring, (
        f"the power-biased car gave away {at_monza:.3f} of the field at Monza "
        f"and {at_hungaroring:.3f} at the Hungaroring; a circuit that rewards "
        f"power has to reward it"
    )
    # And by an amount worth having: the swing is most of a tenth of the field
    # at each circuit, not a rounding difference.
    assert at_hungaroring - at_monza > 0.05
