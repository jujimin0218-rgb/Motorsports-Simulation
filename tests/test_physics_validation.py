"""The automatic physics sanity suite (project rules 39 and 40).

Two halves, as with the track checks.  The suite must pass on every shipped car
*and* must actually fire when a car is broken -- a check that cannot fail is
not a check.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from f1_race_engine.core.config import PhysicsValidationConfig
from f1_race_engine.core.errors import PhysicsValidationError
from f1_race_engine.core.validation import Severity
from f1_race_engine.environment import AmbientConditions
from f1_race_engine.physics.validation import (
    PHYSICS_CHECKS,
    check_downforce_rises_with_speed,
    check_mass_reduces_acceleration,
    check_performance_envelope,
    check_radius_reduces_corner_speed,
    check_wing_trade_off,
    validate_vehicle,
)
from f1_race_engine.vehicle import Vehicle


def _codes(report, severity=None) -> set[str]:
    issues = report.issues if severity is None else report.of_severity(severity)
    return {issue.check for issue in issues}


# -- the good case -----------------------------------------------------------


def test_every_shipped_car_passes(builtin_car):
    report = validate_vehicle(builtin_car)
    assert report.clean, report.format()


def test_every_wing_level_passes(car):
    """A car must be physically sane across its whole setup range, not just at
    the one setting that happened to be calibrated."""
    for wing in (0.0, 0.25, 0.5, 0.75, 1.0):
        report = validate_vehicle(car.with_wing(wing))
        assert report.ok, f"wing {wing}:\n{report.format()}"


def test_passes_in_hot_and_cold_conditions(car):
    for conditions in (
        AmbientConditions(air_temperature=5.0, relative_humidity=0.1),
        AmbientConditions(air_temperature=40.0, relative_humidity=0.8),
    ):
        report = validate_vehicle(car, conditions)
        assert report.ok, report.format()


def test_suite_reports_measured_numbers(car):
    """The report is useful even when nothing is wrong."""
    report = validate_vehicle(car)
    assert report.infos
    assert "performance_envelope" in _codes(report, Severity.INFO)


def test_every_registered_check_runs(car, ambient):
    config = PhysicsValidationConfig()
    for check in PHYSICS_CHECKS:
        check(car, ambient, config)  # must not raise


# -- broken cars -------------------------------------------------------------


def test_inverted_aero_is_caught(car, ambient):
    """A car whose downforce falls with speed must be rejected."""

    class Inverted:
        def downforce(self, speed, rho, wing, drs_open=False):
            return 20_000.0 / max(speed, 1.0)

    broken = car.with_wing(0.5)
    broken.aero = Inverted()  # type: ignore[assignment]
    issues = check_downforce_rises_with_speed(broken, ambient, PhysicsValidationConfig())
    assert any(i.severity is Severity.ERROR for i in issues)


def test_mass_check_fires_when_mass_stops_mattering(car, ambient, monkeypatch):
    """If mass ever stopped reducing acceleration, a term has been dropped from
    the force balance -- the check must notice."""
    import f1_race_engine.physics.validation as validation

    monkeypatch.setattr(validation, "max_acceleration", lambda *a, **k: 9.0)
    issues = check_mass_reduces_acceleration(car, ambient, PhysicsValidationConfig())
    assert any(i.severity is Severity.ERROR for i in issues)
    assert any("did not reduce acceleration" in i.message for i in issues)


def test_downforce_is_not_free(car, ambient):
    """Tripling downforce area triples induced drag, and the car chokes.

    Worth asserting because it is the mechanism that stops "more wing" from
    being a free win, and therefore the reason circuits want different setups.
    """
    monster = car.with_spec(
        replace(
            car.spec,
            aero=replace(
                car.spec.aero, min_downforce_area=11.0, max_downforce_area=19.0
            ),
        )
    )
    errors = [
        i
        for i in check_performance_envelope(monster, ambient, PhysicsValidationConfig())
        if i.severity is Severity.ERROR
    ]
    assert any("top speed" in i.message for i in errors)


def test_absurdly_grippy_car_fails_the_envelope(car, ambient):
    """Self-consistent but unreal: a car cornering at 9 g must be caught.

    Downforce is tripled *and* the induced drag it would cause is removed, so
    the model is perfectly happy -- only comparison against a real car's
    envelope catches it.
    """
    monster = car.with_spec(
        replace(
            car.spec,
            aero=replace(
                car.spec.aero,
                min_downforce_area=11.0,
                max_downforce_area=19.0,
                induced_drag_factor=0.0005,
            ),
        )
    )
    errors = [
        i
        for i in check_performance_envelope(monster, ambient, PhysicsValidationConfig())
        if i.severity is Severity.ERROR
    ]
    assert any("lateral" in i.message for i in errors)


def test_a_dragless_car_is_caught(car, ambient):
    """A car with almost no drag must not validate.

    It is no longer the *top speed* envelope that catches it, and that is the
    rev limit doing its job: a real car runs out of gear long before it runs
    out of drag, so removing the drag no longer sends the top speed anywhere
    absurd.  What gives it away instead is the relationships -- adding power
    stops buying top speed once the engine is on the limiter, and wing stops
    costing any.
    """
    slippery = car.with_spec(
        replace(
            car.spec,
            aero=replace(
                car.spec.aero, zero_lift_drag_area=0.05, induced_drag_factor=0.0001
            ),
        )
    )
    report = validate_vehicle(slippery, ambient)
    codes = _codes(report, Severity.ERROR)
    assert codes, "a car with no drag validated cleanly"
    assert {"power_top_speed", "wing_trade_off"} & codes


def test_wing_with_no_drag_cost_is_caught(car, ambient):
    """If wing were free, every circuit would want maximum downforce and the
    setup trade-off -- the mechanism behind project rule 2.3 -- would vanish."""
    free_wing = car.with_spec(
        replace(car.spec, aero=replace(car.spec.aero, induced_drag_factor=0.0))
    )
    issues = check_wing_trade_off(free_wing, ambient, PhysicsValidationConfig())
    assert any(i.severity is Severity.ERROR for i in issues)


def test_corner_radius_check_fires_on_a_broken_solver(car, ambient, monkeypatch):
    import f1_race_engine.physics.validation as validation

    monkeypatch.setattr(validation, "corner_speed_limit", lambda *a, **k: 50.0)
    issues = check_radius_reduces_corner_speed(car, ambient, PhysicsValidationConfig())
    assert any(i.severity is Severity.ERROR for i in issues)


# -- the report --------------------------------------------------------------


def test_report_raises_the_physics_error(car):
    report = validate_vehicle(car)
    assert report.raise_for_errors() is report

    feeble = car.with_spec(
        replace(
            car.spec,
            power_unit=replace(
                car.spec.power_unit, max_power=90_000.0, peak_wheel_torque=1200.0
            ),
        )
    )
    with pytest.raises(PhysicsValidationError):
        validate_vehicle(feeble).raise_for_errors()


def test_report_header_names_the_car(car):
    text = validate_vehicle(car).format()
    assert "Physics validation" in text
    assert car.name in text


def test_report_export_is_json_serialisable(car):
    import json

    json.dumps(validate_vehicle(car).to_dict())


def test_custom_check_list_is_honoured(car):
    report = validate_vehicle(car, checks=[check_radius_reduces_corner_speed])
    assert _codes(report) <= {"corner_radius"}


def test_config_thresholds_are_respected(car):
    """Tightening the envelope must make a previously passing car fail."""
    strict = PhysicsValidationConfig(min_peak_lateral_g=6.9, max_peak_lateral_g=7.0)
    assert not validate_vehicle(car, config=strict).ok
