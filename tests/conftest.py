"""Shared fixtures.

The synthetic proving ground is the reference circuit for the whole suite: it
is the only shipped track that exercises every part of the model at once.
"""

from __future__ import annotations

import pytest

from f1_race_engine.core.config import SimulationConfig, default_config
from f1_race_engine.track.builder import build_track
from f1_race_engine.track.definitions import (
    CornerDefinition,
    CornerDirection,
    SectorDefinition,
    StraightDefinition,
    TrackDefinition,
)
from f1_race_engine.track.io import load_builtin_definition
from f1_race_engine.track.model import Track


@pytest.fixture(scope="session")
def config() -> SimulationConfig:
    return default_config()


@pytest.fixture(scope="session")
def proving_ground_definition() -> TrackDefinition:
    return load_builtin_definition("synthetic_proving_ground")


@pytest.fixture(scope="session")
def proving_ground(proving_ground_definition: TrackDefinition) -> Track:
    return build_track(proving_ground_definition)


@pytest.fixture(scope="session")
def square_definition() -> TrackDefinition:
    """A four-corner loop whose geometry is exact by symmetry.

    Every corner is the same, the straights pair up, and the whole thing closes
    analytically -- which makes it the right fixture for testing the builder
    itself rather than the data.
    """
    return TrackDefinition(
        name="Square Test Loop",
        layout=(
            StraightDefinition(500.0, "A"),
            CornerDefinition(80.0, 90.0, CornerDirection.LEFT, name="T1", corner_id=1),
            StraightDefinition(300.0, "B"),
            CornerDefinition(80.0, 90.0, CornerDirection.LEFT, name="T2", corner_id=2),
            StraightDefinition(500.0, "C"),
            CornerDefinition(80.0, 90.0, CornerDirection.LEFT, name="T3", corner_id=3),
            StraightDefinition(300.0, "D"),
            CornerDefinition(80.0, 90.0, CornerDirection.LEFT, name="T4", corner_id=4),
        ),
        sectors=SectorDefinition(boundaries=(700.0, 1500.0)),
    )


@pytest.fixture(scope="session")
def square_track(square_definition: TrackDefinition) -> Track:
    return build_track(square_definition)


@pytest.fixture(params=["synthetic_proving_ground", "synthetic_power_circuit",
                        "synthetic_street_circuit"])
def builtin_track(request) -> Track:
    return build_track(load_builtin_definition(request.param))
