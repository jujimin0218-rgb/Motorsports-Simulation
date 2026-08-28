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


# -- corners that change radius ----------------------------------------------


def test_a_constant_radius_corner_is_unchanged_by_the_variable_radius_path():
    """``radius_end`` is opt-in: leaving it out must change nothing."""
    defaults = TrackDefaults()
    corner = CornerDefinition(radius=100.0, angle=90.0, direction=CornerDirection.RIGHT)
    pure = corner.pure_arc_length()
    entry, exit_ = corner.transitions(defaults)
    assert pure == pytest.approx(100.0 * math.radians(90.0))
    assert corner.constant_arc_length(defaults) == pytest.approx(
        pure - 0.5 * (entry + exit_)
    )
    assert corner.is_constant_radius


def test_a_corner_that_opens_out_still_turns_the_requested_angle():
    """The whole point: the arc is a ramp, and the total turn is unchanged.

    Curvature is linear everywhere in the corner, so each part turns the car by
    its mean curvature times its length.  If that arithmetic were wrong the
    circuit would not close.
    """
    defaults = TrackDefaults()
    corner = CornerDefinition(
        radius=100.0, angle=120.0, direction=CornerDirection.RIGHT, radius_end=250.0
    )
    entry, exit_ = corner.transitions(defaults)
    arc = corner.constant_arc_length(defaults)
    turned = (
        0.5 * entry / corner.radius
        + 0.5 * (1.0 / corner.radius + 1.0 / corner.exit_radius) * arc
        + 0.5 * exit_ / corner.exit_radius
    )
    assert turned == pytest.approx(math.radians(120.0))
    assert corner.tightest_radius == 100.0
    assert not corner.is_constant_radius


def test_a_corner_that_tightens_is_slower_than_its_entry_radius_suggests():
    """A decreasing-radius corner has to be braked for its exit."""
    defaults = TrackDefaults()
    opening = CornerDefinition(
        radius=80.0, angle=100.0, direction=CornerDirection.LEFT, radius_end=200.0
    )
    tightening = CornerDefinition(
        radius=200.0, angle=100.0, direction=CornerDirection.LEFT, radius_end=80.0
    )
    assert opening.tightest_radius == tightening.tightest_radius == 80.0
    # Same turn through the same pair of radii, so the same length of road.
    assert opening.pure_arc_length() == pytest.approx(tightening.pure_arc_length())


def test_a_radius_end_of_zero_is_rejected():
    with pytest.raises(TrackBuildError, match="radius_end"):
        CornerDefinition(radius=100.0, angle=90.0, radius_end=0.0)
