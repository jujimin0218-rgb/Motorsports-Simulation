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


# ---------------------------------------------------------------------------
# Phase 2: vehicles, tyres and conditions
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def ambient():
    from f1_race_engine.environment import AmbientConditions

    return AmbientConditions()


@pytest.fixture(scope="session")
def air_density(ambient) -> float:
    return ambient.air_density


@pytest.fixture(scope="session")
def compounds():
    from f1_race_engine.tyres.io import load_builtin_compounds

    return load_builtin_compounds()


@pytest.fixture(scope="session")
def reference_spec():
    from f1_race_engine.vehicle.io import load_builtin_vehicle

    return load_builtin_vehicle("reference_2024")


@pytest.fixture
def car(reference_spec):
    """The reference car in medium-downforce trim."""
    from f1_race_engine.vehicle import MEDIUM_DOWNFORCE, Vehicle

    return Vehicle(reference_spec, MEDIUM_DOWNFORCE)


@pytest.fixture(params=["reference_2024", "power_biased", "aero_biased"])
def builtin_car(request):
    from f1_race_engine.vehicle import MEDIUM_DOWNFORCE, Vehicle
    from f1_race_engine.vehicle.io import load_builtin_vehicle

    return Vehicle(load_builtin_vehicle(request.param), MEDIUM_DOWNFORCE)


# ---------------------------------------------------------------------------
# Phase 3: laps
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def coarse_build_config():
    """Coarse sampling, for tests that compute many laps.

    Lap time converges to within ~0.02% of the 1 m answer even here, so it is
    the right trade for a test suite that has to stay fast enough to actually
    be run (project rule 47).
    """
    from f1_race_engine.core.config import TrackBuildConfig

    return TrackBuildConfig(
        straight_segment_length=30.0, corner_segment_length=20.0,
        min_segment_length=5.0, max_segment_length=30.0,
        max_heading_change_per_segment_deg=8.0,
        max_curvature_change_per_segment=0.01,
    )


@pytest.fixture(scope="session")
def fast_track(proving_ground_definition, coarse_build_config) -> Track:
    """The reference circuit, coarsely sampled."""
    return build_track(proving_ground_definition, coarse_build_config)


@pytest.fixture(scope="session")
def session_build_config():
    """Coarser still, for tests that run whole race weekends.

    A session-level test is checking structure -- who is on the grid, who
    stopped, what the weather did -- and resolution independence means those
    answers do not need a finely sampled circuit.  Lap times off by a tenth are
    fine here and the suite stays runnable (project rule 47).
    """
    from f1_race_engine.core.config import TrackBuildConfig

    return TrackBuildConfig(
        straight_segment_length=70.0, corner_segment_length=45.0,
        min_segment_length=15.0, max_segment_length=70.0,
        max_heading_change_per_segment_deg=18.0,
        max_curvature_change_per_segment=0.03,
    )


@pytest.fixture(scope="session")
def session_track(proving_ground_definition, session_build_config) -> Track:
    """The reference circuit at session-test resolution."""
    return build_track(proving_ground_definition, session_build_config)


@pytest.fixture(scope="session")
def fast_lap(fast_track, reference_spec):
    from f1_race_engine.physics import compute_lap_time
    from f1_race_engine.vehicle import MEDIUM_DOWNFORCE, Vehicle

    return compute_lap_time(fast_track, Vehicle(reference_spec, MEDIUM_DOWNFORCE))


# ---------------------------------------------------------------------------
# Phase 4: drivers
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def perfect_driver():
    """A driver with no shortfall and no variation.

    Reproduces the Phase 3 limit lap exactly, which is the test that says the
    stepping is right.
    """
    from f1_race_engine.driver import Driver, DriverAttributes

    return Driver(
        name="Perfect Reference",
        abbreviation="REF",
        attributes=DriverAttributes(
            pace=1.0, qualifying=1.0, racecraft=1.0, consistency=1.0,
            tyre_management=1.0, braking=1.0, cornering=1.0,
            throttle_control=1.0, wet_skill=1.0, risk_management=1.0,
        ),
    )


@pytest.fixture(scope="session")
def lineup():
    from f1_race_engine.driver.io import load_driver_lineup

    return load_driver_lineup()


@pytest.fixture
def simulator(fast_track, car, perfect_driver):
    from f1_race_engine.core.rng import RngHub
    from f1_race_engine.simulation import LapSimulator

    return LapSimulator(fast_track, car, perfect_driver, rng=RngHub(20260812))


# ---------------------------------------------------------------------------
# Phase 6: a field of cars
# ---------------------------------------------------------------------------


@pytest.fixture
def make_entry(reference_spec):
    """Build a race entry, defaulting everything that does not matter."""
    from f1_race_engine.race import RaceEntry
    from f1_race_engine.vehicle import MEDIUM_DOWNFORCE, Vehicle

    def build(car_number, driver, *, spec=None, fuel_mass=50.0, team="", compound=None):
        entry = RaceEntry(
            car_number=car_number,
            driver=driver,
            vehicle=Vehicle(spec or reference_spec, MEDIUM_DOWNFORCE),
            team=team,
            fuel_mass=fuel_mass,
            grid_position=car_number,
        )
        if compound is not None:
            entry.fit(compound)
        return entry

    return build


@pytest.fixture
def small_field(make_entry, lineup):
    """Four cars, four different drivers, otherwise identical."""
    return [make_entry(index + 1, driver) for index, driver in enumerate(lineup[:4])]


@pytest.fixture(scope="session")
def street_track(session_build_config) -> Track:
    """A circuit with nowhere to overtake, at session-test resolution."""
    return build_track(
        load_builtin_definition("synthetic_street_circuit"), session_build_config
    )
