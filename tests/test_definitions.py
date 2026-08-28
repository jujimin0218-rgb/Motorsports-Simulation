"""Corner geometry: transitions must preserve the requested turn angle."""

from __future__ import annotations

import math

import pytest

from f1_race_engine.core.errors import TrackBuildError
from f1_race_engine.track.definitions import (
    CornerDefinition,
    CornerDirection,
    SectorDefinition,
    StraightDefinition,
    TrackDefaults,
    TrackDefinition,
)


@pytest.fixture
def defaults() -> TrackDefaults:
    return TrackDefaults()


def test_direction_sign_matches_the_curvature_convention():
    assert CornerDirection.LEFT.sign == 1
    assert CornerDirection.RIGHT.sign == -1


def test_left_corner_has_positive_curvature():
    assert CornerDefinition(50.0, 90.0, CornerDirection.LEFT).curvature > 0
    assert CornerDefinition(50.0, 90.0, CornerDirection.RIGHT).curvature < 0


def test_transitions_preserve_the_turn_angle(defaults):
    """The transitions turn the car too, so the arc is shortened to compensate.

    This is the identity the whole builder rests on: k * (La + (Le+Lx)/2) = angle.
    """
    for radius, angle in ((25.0, 90.0), (400.0, 60.0), (90.0, 180.0), (600.0, 5.0)):
        corner = CornerDefinition(radius, angle, CornerDirection.LEFT)
        entry, exit_ = corner.transitions(defaults)
        arc = corner.constant_arc_length(defaults)
        turned = abs(corner.curvature) * (arc + 0.5 * (entry + exit_))
        assert math.degrees(turned) == pytest.approx(angle, abs=1e-9)


def test_corner_always_keeps_a_constant_radius_section(defaults):
    for radius, angle in ((10.0, 5.0), (700.0, 3.0), (25.0, 180.0)):
        corner = CornerDefinition(radius, angle, CornerDirection.LEFT)
        assert corner.constant_arc_length(defaults) > 0.0


def test_total_length_exceeds_the_pure_arc(defaults):
    corner = CornerDefinition(100.0, 90.0, CornerDirection.LEFT)
    assert corner.arc_length(defaults) > corner.pure_arc_length()


def test_explicit_transitions_are_honoured_but_capped(defaults):
    corner = CornerDefinition(100.0, 90.0, CornerDirection.LEFT, entry_transition=10.0)
    entry, _ = corner.transitions(defaults)
    assert entry == pytest.approx(10.0)

    huge = CornerDefinition(100.0, 90.0, CornerDirection.LEFT, entry_transition=10_000.0)
    entry, _ = huge.transitions(defaults)
    assert entry <= defaults.max_transition_fraction * huge.pure_arc_length() + 1e-9


def test_zero_transition_gives_a_pure_arc(defaults):
    corner = CornerDefinition(
        100.0, 90.0, CornerDirection.LEFT, entry_transition=0.0, exit_transition=0.0
    )
    assert corner.arc_length(defaults) == pytest.approx(corner.pure_arc_length())


def test_lap_length_does_not_depend_on_build_configuration():
    """Geometry belongs to the definition, sampling to the config."""
    definition = TrackDefinition(
        name="x",
        layout=(
            StraightDefinition(1000.0),
            CornerDefinition(80.0, 90.0, CornerDirection.LEFT, corner_id=1),
        ),
    )
    assert definition.lap_length == pytest.approx(
        1000.0 + definition.layout[1].arc_length(definition.defaults)
    )


def test_total_turn_angle_is_signed():
    definition = TrackDefinition(
        name="x",
        layout=(
            StraightDefinition(100.0),
            CornerDefinition(80.0, 90.0, CornerDirection.LEFT, corner_id=1),
            StraightDefinition(100.0),
            CornerDefinition(80.0, 30.0, CornerDirection.RIGHT, corner_id=2),
        ),
    )
    assert math.degrees(definition.total_turn_angle) == pytest.approx(60.0)


def test_element_distances_tile_the_lap():
    definition = TrackDefinition(
        name="x",
        layout=(
            StraightDefinition(100.0),
            CornerDefinition(80.0, 90.0, CornerDirection.LEFT, corner_id=1),
            StraightDefinition(200.0),
        ),
    )
    spans = definition.element_distances()
    assert spans[0][0] == 0.0
    assert spans[-1][1] == pytest.approx(definition.lap_length)
    for (_, end, _), (start, _, _) in zip(spans, spans[1:]):
        assert end == pytest.approx(start)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"radius": 0.0, "angle": 90.0},
        {"radius": -50.0, "angle": 90.0},
        {"radius": 50.0, "angle": 0.0},
        {"radius": 50.0, "angle": 400.0},
        {"radius": 50.0, "angle": 90.0, "entry_transition": -1.0},
    ],
)
def test_impossible_corners_are_rejected(kwargs):
    with pytest.raises(TrackBuildError):
        CornerDefinition(**kwargs)


def test_non_positive_straight_is_rejected():
    with pytest.raises(TrackBuildError):
        StraightDefinition(0.0)


def test_empty_layout_is_rejected():
    with pytest.raises(TrackBuildError):
        TrackDefinition(name="x", layout=())


def test_sector_lookup():
    sectors = SectorDefinition(boundaries=(1000.0, 2000.0))
    assert sectors.sector_count == 3
    assert sectors.sector_of(0.0) == 1
    assert sectors.sector_of(999.9) == 1
    assert sectors.sector_of(1000.0) == 2
    assert sectors.sector_of(2500.0) == 3


def test_invalid_defaults_are_rejected():
    with pytest.raises(TrackBuildError):
        TrackDefaults(track_width=0.0)
    with pytest.raises(TrackBuildError):
        TrackDefaults(roughness=1.5)
    with pytest.raises(TrackBuildError):
        TrackDefaults(max_transition_fraction=0.9)
