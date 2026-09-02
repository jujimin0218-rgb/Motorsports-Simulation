"""Teams, cars, drivers -- and the seam where they meet the race engine."""

from __future__ import annotations

import pytest

from app.game.car import AREA_NAMES, CarPerformance, EngineSupplier, Facilities
from app.game.errors import InsufficientBudget, InvalidDriver, UnknownEntity
from app.game.people import ENGINE_SKILLS, GAME_SKILLS, Contract, DriverProfile
from app.game.team import Team


# -- the car -----------------------------------------------------------------


def test_a_car_is_not_one_number():
    """The whole reason performance is kept per area: the same car has to be
    good at one circuit and poor at another without anybody writing down a
    per-circuit correction."""
    car = CarPerformance(aero=0.95, power_unit=0.60, mechanical_grip=0.95)
    at_monza = car.rating_for({"power_unit": 0.95, "aero": 0.20, "mechanical_grip": 0.05})
    at_monaco = car.rating_for({"power_unit": 0.20, "aero": 0.95, "mechanical_grip": 0.80})
    assert at_monaco > at_monza
    # And a car strong everywhere is not troubled by the difference.
    even = CarPerformance(**{name: 0.85 for name in AREA_NAMES})
    assert even.rating_for({"power_unit": 1.0}) == pytest.approx(
        even.rating_for({"aero": 1.0})
    )


def test_car_areas_are_bounded():
    car = CarPerformance()
    car.improve("aero", 5.0)
    assert car.area("aero") == 1.0
    car.improve("aero", -5.0)
    assert car.area("aero") == 0.0


def test_an_unknown_area_is_refused_rather_than_created():
    with pytest.raises(UnknownEntity):
        CarPerformance().area("engine_mode")


# -- facilities --------------------------------------------------------------


def test_facilities_cap_out():
    facilities = Facilities(simulator=5)
    with pytest.raises(UnknownEntity):
        facilities.upgrade("simulator")


def test_a_facility_changes_development_rate_not_car_speed():
    """A factory is an advantage that compounds, not one that applies."""
    strong = Team(id="a", name="A", facilities=Facilities(aerodynamics=5))
    weak = Team(id="b", name="B", facilities=Facilities(aerodynamics=1))
    assert strong.development_rate("aero") > 1.0 > weak.development_rate("aero")
    # Level 3 is the reference, so an average team is neither helped nor taxed.
    assert Team(id="c", name="C").development_rate("aero") == pytest.approx(1.0)
    # And the two departments that buy nothing on the car say so.
    assert strong.development_rate("tyre_management") == strong.development_rate(
        "chassis"
    )


# -- money -------------------------------------------------------------------


def test_a_team_refuses_to_spend_what_it_does_not_have():
    team = Team(id="a", name="Alpha", budget=10.0)
    team.spend(4.0)
    assert team.budget == pytest.approx(6.0)
    with pytest.raises(InsufficientBudget):
        team.spend(6.01)
    assert team.budget == pytest.approx(6.0), "a refused spend must not deduct"


def test_spending_a_negative_amount_is_not_a_way_to_earn():
    with pytest.raises(InsufficientBudget):
        Team(id="a", name="Alpha", budget=10.0).spend(-50.0)


# -- the engine supplier -----------------------------------------------------


def test_a_works_team_pays_nothing_and_a_customer_pays():
    supplier = EngineSupplier(
        id="e", name="E", cost_per_season=18.0, works_team="factory"
    )
    assert supplier.cost_for("factory") == 0.0
    assert supplier.cost_for("customer") == 18.0


# -- drivers -----------------------------------------------------------------


def test_the_engine_gets_all_ten_of_its_own_attributes():
    """The game stores eleven ratings and the engine wants ten different ones.
    Every one of the engine's has to arrive filled in, or a driver reaches the
    physics with a default in place of an ability."""
    profile = DriverProfile(id="x", name="X")
    attributes = profile.to_engine_driver().attributes.to_dict()
    assert len(attributes) == 10
    assert all(0.0 < value <= 1.0 for value in attributes.values())


def test_the_shared_skills_are_handed_across_unchanged():
    """No mapping, no scaling: the engine's driver model is the driver model.

    ``racecraft`` is the one exception and it is deliberate -- it is folded
    together with attack or defence depending on which side of a fight the
    driver is on, which the next test covers.  ``pace``, ``qualifying`` and
    ``consistency`` are shown here with form flat, since form is a separate
    modifier on those three.
    """
    profile = DriverProfile(
        id="x", name="X",
        skills={name: 0.5 + i * 0.05 for i, name in enumerate(ENGINE_SKILLS)},
    )
    assert profile.form == 0.0
    attributes = profile.to_engine_driver().attributes
    for name in ENGINE_SKILLS:
        if name == "racecraft":
            continue
        assert getattr(attributes, name) == pytest.approx(profile.skill(name))


def test_attack_and_defence_are_stored_apart_and_folded_back_together():
    """The engine settles a fight with one racecraft number.  A manager game
    wants to tell an attacker from a defender, so the two are kept apart here
    and shown to the engine according to which side the driver is on."""
    profile = DriverProfile(
        id="x", name="X", skills={"racecraft": 0.80, "overtaking": 0.95, "defending": 0.60}
    )
    attacking = profile.to_engine_driver(attacking=True).attributes.racecraft
    defending = profile.to_engine_driver(attacking=False).attributes.racecraft
    assert attacking > 0.80 > defending


def test_form_moves_pace_but_not_by_much():
    """A season where one bad Sunday costs half a second for the rest of the
    year is not a season anybody enjoys.  In equal machinery the whole field
    lives inside about one per cent of lap time, so form has to be smaller
    than the drivers are."""
    profile = DriverProfile(id="x", name="X", skills={"pace": 0.80})
    flat = profile.to_engine_driver().attributes.pace
    profile.form = 1.0
    peak = profile.to_engine_driver().attributes.pace
    profile.form = -1.0
    trough = profile.to_engine_driver().attributes.pace
    assert trough < flat < peak
    assert peak - trough < 0.10


def test_form_does_not_touch_what_it_should_not():
    """Form is a run of results, not a change to the driver.  It has no
    business altering how well somebody looks after a tyre."""
    profile = DriverProfile(id="x", name="X", skills={"tyre_management": 0.80})
    flat = profile.to_engine_driver().attributes.tyre_management
    profile.form = -1.0
    assert profile.to_engine_driver().attributes.tyre_management == pytest.approx(flat)


def test_the_game_skills_do_not_shadow_the_engine_ones():
    """Project rule: do not reimplement what the engine already has."""
    assert not set(ENGINE_SKILLS) & set(GAME_SKILLS)


def test_market_value_is_steeply_convex_in_ability():
    """The gap between a good driver and a great one is worth far more than
    the gap between an average one and a good one, which is what makes the top
    of the market a real decision."""
    def value(rating: float) -> float:
        return DriverProfile(
            id="x", name="X", skills={n: rating for n in ENGINE_SKILLS + GAME_SKILLS},
            reputation=rating, potential=rating,
        ).market_value

    step_low = value(0.75) - value(0.65)
    step_high = value(0.95) - value(0.85)
    assert step_high > 3.0 * step_low


def test_an_unknown_skill_is_refused():
    with pytest.raises(InvalidDriver):
        DriverProfile(id="x", name="X").skill("telepathy")


def test_a_contract_counts_down():
    contract = Contract(seasons_remaining=2)
    assert not contract.expires_this_season
    contract.advance_season()
    assert contract.expires_this_season
    contract.advance_season()
    assert contract.seasons_remaining == 0


# -- persistence -------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        CarPerformance(aero=0.91),
        Facilities(simulator=5, chassis=1),
        Team(id="t", name="T", budget=12.25, drivers=["a", "b"]),
        DriverProfile(id="d", name="D", contract=Contract(salary=9.5)),
        EngineSupplier(id="e", name="E"),
    ],
)
def test_everything_round_trips(value):
    restored = type(value).from_dict(value.to_dict())
    assert restored.to_dict() == value.to_dict()
