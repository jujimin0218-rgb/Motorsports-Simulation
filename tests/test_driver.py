"""The driver model (project rules 18 and 19)."""

from __future__ import annotations

import statistics

import pytest

from f1_race_engine.core.config import DriverConfig
from f1_race_engine.core.errors import ConfigError
from f1_race_engine.core.rng import RngHub
from f1_race_engine.driver import (
    Driver,
    DriverAttributes,
    DriverInput,
    commitment_for,
    control_input,
    sample_lap_variation,
    sample_mistakes,
)
from f1_race_engine.driver.io import (
    builtin_driver_names,
    load_builtin_driver,
    load_driver,
    save_driver,
)


# -- attributes --------------------------------------------------------------


def test_attributes_default_to_a_mid_field_driver():
    attributes = DriverAttributes()
    assert 0.8 <= attributes.overall <= 0.9


def test_every_ability_is_separate():
    """Project rule 18: a driver is not one rating."""
    attributes = DriverAttributes(braking=0.99, throttle_control=0.70)
    assert attributes.braking != attributes.throttle_control
    assert len(attributes.to_dict()) == 10


def test_attributes_round_trip():
    attributes = DriverAttributes(braking=0.93, wet_skill=0.71)
    assert DriverAttributes.from_dict(attributes.to_dict()) == attributes


@pytest.mark.parametrize("kwargs", [{"pace": 1.5}, {"braking": -0.1}])
def test_impossible_attributes_are_rejected(kwargs):
    with pytest.raises(ConfigError):
        DriverAttributes(**kwargs)


def test_unknown_attribute_is_rejected():
    with pytest.raises(ConfigError, match="unknown"):
        DriverAttributes.from_dict({"bravery": 0.9})
    with pytest.raises(ConfigError):
        DriverAttributes().with_attribute("bravery", 0.9)


def test_driver_validation():
    with pytest.raises(ConfigError):
        Driver(name="")
    with pytest.raises(ConfigError):
        Driver(name="X", number=0)


# -- ability becomes physics -------------------------------------------------


def test_a_better_driver_uses_more_grip():
    config = DriverConfig()
    weak = commitment_for(DriverAttributes(cornering=0.70, pace=0.70), config)
    strong = commitment_for(DriverAttributes(cornering=1.0, pace=1.0), config)
    assert strong.cornering > weak.cornering
    assert strong.cornering == pytest.approx(1.0)


def test_each_ability_moves_only_its_own_axis():
    """The whole point of ten attributes: they must not collapse into one."""
    config = DriverConfig()
    base = DriverAttributes(braking=0.85, cornering=0.85, throttle_control=0.85)
    braker = commitment_for(base.with_attribute("braking", 0.99), config)
    reference = commitment_for(base, config)
    assert braker.braking > reference.braking
    assert braker.cornering == pytest.approx(reference.cornering)
    assert braker.traction == pytest.approx(reference.traction)


def test_pace_lifts_every_axis():
    config = DriverConfig()
    slow = commitment_for(DriverAttributes(pace=0.70), config)
    quick = commitment_for(DriverAttributes(pace=1.0), config)
    assert quick.cornering > slow.cornering
    assert quick.braking > slow.braking
    assert quick.traction > slow.traction


def test_commitment_never_exceeds_the_car():
    """A driver can fall short of the limit, never beat it."""
    config = DriverConfig()
    for attributes in (
        DriverAttributes(pace=1.0, cornering=1.0, braking=1.0, throttle_control=1.0),
        DriverAttributes(pace=1.0, qualifying=1.0, cornering=1.0),
    ):
        commitment = commitment_for(attributes, config, qualifying=True)
        assert commitment.cornering <= 1.0
        assert commitment.braking <= 1.0
        assert commitment.traction <= 1.0


def test_commitment_has_a_floor():
    config = DriverConfig()
    commitment = commitment_for(DriverAttributes(pace=0.0, cornering=0.0), config, bias=-5.0)
    assert commitment.cornering >= config.min_commitment


def test_a_one_lap_specialist_gains_more_in_qualifying():
    config = DriverConfig()
    specialist = DriverAttributes(pace=0.90, qualifying=0.99, cornering=0.90)
    journeyman = DriverAttributes(pace=0.90, qualifying=0.80, cornering=0.90)
    gain = lambda a: (
        commitment_for(a, config, qualifying=True).cornering
        - commitment_for(a, config).cornering
    )
    assert gain(specialist) > gain(journeyman)


def test_pace_is_blended_not_added():
    """An additive pace bonus saturates the strongest drivers at 100%
    commitment, leaving them nothing to find on a qualifying lap."""
    config = DriverConfig()
    elite = DriverAttributes(pace=0.98, qualifying=0.97, cornering=0.98)
    race = commitment_for(elite, config).cornering
    assert race < 1.0
    assert commitment_for(elite, config, qualifying=True).cornering > race


# -- consistency -------------------------------------------------------------


def test_a_perfectly_consistent_driver_never_varies():
    variation = sample_lap_variation(
        DriverAttributes(consistency=1.0), RngHub(1),
        driver="X", lap=1, corner_ids=(1, 2, 3),
    )
    assert variation.is_perfect
    assert variation.bias_for_corner(1) == 0.0


def test_variation_is_one_sided():
    """A driver can only fall short of the limit."""
    attributes = DriverAttributes(consistency=0.6)
    hub = RngHub(42)
    for lap in range(1, 30):
        variation = sample_lap_variation(
            attributes, hub, driver="X", lap=lap, corner_ids=(1, 2, 3)
        )
        assert variation.lap_bias <= 0.0
        assert all(bias <= 0.0 for bias in variation.corner_bias.values())


def test_a_less_consistent_driver_varies_more():
    hub = RngHub(5)
    spreads = {}
    for consistency in (0.99, 0.85, 0.70):
        biases = [
            sample_lap_variation(
                DriverAttributes(consistency=consistency), hub,
                driver=f"C{consistency}", lap=lap, corner_ids=(1, 2, 3),
            ).lap_bias
            for lap in range(1, 60)
        ]
        spreads[consistency] = statistics.pstdev(biases)
    assert spreads[0.70] > spreads[0.85] > spreads[0.99]


def test_variation_is_reproducible():
    a = sample_lap_variation(
        DriverAttributes(consistency=0.8), RngHub(9), driver="X", lap=3,
        corner_ids=(1, 2),
    )
    b = sample_lap_variation(
        DriverAttributes(consistency=0.8), RngHub(9), driver="X", lap=3,
        corner_ids=(1, 2),
    )
    assert a.lap_bias == b.lap_bias
    assert a.corner_bias == b.corner_bias


def test_different_laps_and_drivers_get_different_variation():
    hub = RngHub(11)
    attributes = DriverAttributes(consistency=0.8)
    first = sample_lap_variation(attributes, hub, driver="A", lap=1).lap_bias
    later = sample_lap_variation(attributes, hub, driver="A", lap=2).lap_bias
    other = sample_lap_variation(attributes, hub, driver="B", lap=1).lap_bias
    assert first != later
    assert first != other


# -- mistakes ----------------------------------------------------------------


def test_a_disciplined_driver_makes_no_mistakes():
    mistakes = sample_mistakes(
        DriverAttributes(risk_management=1.0, consistency=1.0), RngHub(1),
        driver="X", lap=1, corners={1: "T1", 2: "T2"},
    )
    assert mistakes == ()


def test_an_erratic_driver_makes_mistakes():
    hub = RngHub(3)
    attributes = DriverAttributes(risk_management=0.5, consistency=0.5)
    total = sum(
        len(sample_mistakes(attributes, hub, driver="X", lap=lap,
                            corners={i: f"T{i}" for i in range(1, 8)}))
        for lap in range(1, 40)
    )
    assert total > 0


def test_mistakes_are_rarer_for_better_drivers():
    corners = {i: f"T{i}" for i in range(1, 8)}
    counts = {}
    for quality in (0.95, 0.80, 0.60):
        hub = RngHub(7)
        attributes = DriverAttributes(risk_management=quality, consistency=quality)
        counts[quality] = sum(
            len(sample_mistakes(attributes, hub, driver="X", lap=lap, corners=corners))
            for lap in range(1, 120)
        )
    assert counts[0.60] > counts[0.80] >= counts[0.95]


def test_mistake_severity_is_mostly_small():
    hub = RngHub(13)
    attributes = DriverAttributes(risk_management=0.3, consistency=0.3)
    severities = []
    for lap in range(1, 200):
        severities.extend(
            m.severity
            for m in sample_mistakes(attributes, hub, driver="X", lap=lap,
                                     corners={1: "T1", 2: "T2", 3: "T3"})
        )
    assert severities
    assert statistics.median(severities) < 0.35


def test_mistakes_carry_a_speed_penalty():
    hub = RngHub(3)
    for lap in range(1, 60):
        for mistake in sample_mistakes(
            DriverAttributes(risk_management=0.4, consistency=0.4), hub,
            driver="X", lap=lap, corners={1: "Turn 1"},
        ):
            assert 0.0 < mistake.speed_penalty <= DriverConfig().mistake_severity
            assert mistake.corner_name == "Turn 1"


# -- inputs ------------------------------------------------------------------


def test_input_asks_for_throttle_when_speeding_up():
    command = control_input(
        speed=50.0, target_speed=55.0, distance_step=20.0, mass=900.0,
        coast_acceleration=-1.0, powertrain_force=10_000.0,
        brake_system_force=60_000.0, curvature=0.0, max_curvature=0.04,
    )
    assert command.throttle > 0.0
    assert command.brake == 0.0


def test_input_asks_for_brake_when_slowing_down():
    command = control_input(
        speed=80.0, target_speed=50.0, distance_step=20.0, mass=900.0,
        coast_acceleration=-2.0, powertrain_force=10_000.0,
        brake_system_force=60_000.0, curvature=0.0, max_curvature=0.04,
    )
    assert command.brake > 0.0
    assert command.throttle == 0.0
    assert command.is_braking


def test_input_solves_in_force_space():
    """Throttle scales drive force, so drag must be subtracted first.

    Dividing a required *acceleration* by the net acceleration ignores that,
    and a perfect driver ends up a second a lap off the car's own limit.
    """
    mass, step = 900.0, 25.0
    coast = -3.0  # heavy drag
    required = 1.0
    target = (50.0**2 + 2.0 * required * step) ** 0.5
    command = control_input(
        speed=50.0, target_speed=target, distance_step=step, mass=mass,
        coast_acceleration=coast, powertrain_force=10_000.0,
        brake_system_force=60_000.0, curvature=0.0, max_curvature=0.04,
    )
    expected = mass * (required - coast) / 10_000.0
    assert command.throttle == pytest.approx(expected, rel=1e-9)


def test_input_saturates_rather_than_exceeding_one():
    command = control_input(
        speed=10.0, target_speed=90.0, distance_step=5.0, mass=900.0,
        coast_acceleration=-1.0, powertrain_force=8_000.0,
        brake_system_force=60_000.0, curvature=0.0, max_curvature=0.04,
    )
    assert command.throttle == 1.0


def test_steering_follows_curvature():
    left = control_input(
        speed=50.0, target_speed=50.0, distance_step=20.0, mass=900.0,
        coast_acceleration=0.0, powertrain_force=10_000.0,
        brake_system_force=60_000.0, curvature=0.04, max_curvature=0.04,
    )
    right = control_input(
        speed=50.0, target_speed=50.0, distance_step=20.0, mass=900.0,
        coast_acceleration=0.0, powertrain_force=10_000.0,
        brake_system_force=60_000.0, curvature=-0.04, max_curvature=0.04,
    )
    assert left.steering == pytest.approx(1.0)
    assert right.steering == pytest.approx(-1.0)


def test_gear_and_ers_are_present_but_unset():
    """Project rule 19 wants the abstraction now; the models fill it later."""
    command = DriverInput()
    assert command.gear is None
    assert command.ers_deployment == 0.0
    assert "gear" in command.to_dict()


# -- shipped drivers ---------------------------------------------------------


def test_shipped_drivers_load():
    names = builtin_driver_names()
    assert len(names) >= 6
    for name in names:
        driver = load_builtin_driver(name)
        assert driver.name and driver.abbreviation


def test_shipped_drivers_span_a_range(lineup):
    overalls = [driver.attributes.overall for driver in lineup]
    assert max(overalls) - min(overalls) > 0.10


def test_shipped_drivers_have_distinct_shapes(lineup):
    """Not just better and worse -- differently good."""
    braker = max(lineup, key=lambda d: d.attributes.braking)
    smooth = max(lineup, key=lambda d: d.attributes.throttle_control)
    assert braker is not smooth
    assert braker.attributes.throttle_control < smooth.attributes.throttle_control


def test_driver_round_trip(tmp_path, lineup):
    path = tmp_path / "driver.json"
    save_driver(lineup[0], path)
    assert load_driver(path) == lineup[0]


def test_unknown_driver_lists_what_is_available():
    with pytest.raises(ConfigError, match="available"):
        load_builtin_driver("nobody")
