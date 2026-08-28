"""Static surface properties versus evolving session condition."""

from __future__ import annotations

import pytest

from f1_race_engine.core.config import TrackConditionsConfig
from f1_race_engine.core.errors import TrackBuildError
from f1_race_engine.track.segment import KerbType, SurfaceType
from f1_race_engine.track.surface import (
    KerbMap,
    SurfaceMap,
    SurfaceRegion,
    TrackConditions,
)


def test_surface_map_falls_back_to_defaults():
    surface = SurfaceMap(
        [SurfaceRegion(100.0, 200.0, SurfaceType.CONCRETE, 0.92, 0.8, "pit exit")],
        default_grip=1.0,
        default_roughness=0.5,
    )
    assert surface.at(150.0) == (SurfaceType.CONCRETE, 0.92, 0.8)
    assert surface.at(50.0) == (SurfaceType.ASPHALT, 1.0, 0.5)
    assert surface.at(200.0) == (SurfaceType.ASPHALT, 1.0, 0.5)


def test_invalid_surface_regions_are_rejected():
    with pytest.raises(TrackBuildError):
        SurfaceRegion(200.0, 100.0)
    with pytest.raises(TrackBuildError):
        SurfaceRegion(0.0, 100.0, grip=0.0)


def test_kerb_map():
    kerbs = KerbMap([(100.0, 200.0, KerbType.HIGH)], default=KerbType.NONE)
    assert kerbs.at(150.0) is KerbType.HIGH
    assert kerbs.at(250.0) is KerbType.NONE
    assert kerbs.to_dict()["regions"][0]["kerb"] == "high"


def test_conditions_are_neutral_when_green(proving_ground):
    """A freshly built track must behave exactly like its static definition."""
    conditions = TrackConditions(proving_ground.segments)
    for index in range(0, len(proving_ground), 37):
        assert conditions.grip_multiplier(index) == pytest.approx(1.0)
        assert conditions.effective_grip(index) == pytest.approx(
            proving_ground.segments[index].surface_grip
        )


def test_rubber_raises_grip_on_the_line_and_marbles_lower_it_off_it(proving_ground):
    """Rubber goes down where the cars run; marbles collect beside it.  So a
    session makes the racing line quicker and everywhere else slower, and a car
    only pays for the marbles when it leaves the line."""
    config = TrackConditionsConfig()
    conditions = TrackConditions(proving_ground.segments, config)
    conditions[0].rubber = 1.0
    assert conditions.grip_multiplier(0) == pytest.approx(1.0 + config.rubber_grip_gain)

    conditions[0].rubber = 0.0
    conditions[0].marbles = 1.0
    assert conditions.grip_multiplier(0) == pytest.approx(1.0)
    assert conditions.grip_multiplier(0, off_line=True) == pytest.approx(
        1.0 - config.marble_grip_penalty
    )
    assert conditions.effective_grip(0, off_line=True) < conditions.effective_grip(0)


def test_a_wet_surface_costs_grip_and_then_stops_getting_worse(proving_ground):
    """The surface term is the asphalt, not the tyre: wet asphalt has a lower
    friction coefficient than dry asphalt however deep the water is, and a
    damp track already has nearly all of that penalty.  What deeper water does
    is lift a tyre off the road, which depends on the tread and is answered in
    :mod:`f1_race_engine.tyres.wet` instead."""
    config = TrackConditionsConfig()
    conditions = TrackConditions(proving_ground.segments, config)
    conditions[0].water_depth = 0.00005
    damp = conditions.grip_multiplier(0)
    conditions[0].water_depth = 0.002
    wet = conditions.grip_multiplier(0)
    conditions[0].water_depth = 0.02
    flooded = conditions.grip_multiplier(0)
    assert wet < damp < 1.0
    assert flooded == pytest.approx(wet)
    assert wet == pytest.approx(1.0 - config.wet_surface_penalty)
    assert conditions.is_wet(0) and conditions.any_wet


def test_conditions_reset_and_summarise(proving_ground):
    conditions = TrackConditions(proving_ground.segments)
    conditions[0].rubber = 1.0
    assert conditions.mean_rubber > 0.0
    conditions.reset()
    assert conditions.mean_rubber == 0.0
    assert not conditions.any_wet
    assert len(conditions.to_dict()["segments"]) == len(proving_ground)
