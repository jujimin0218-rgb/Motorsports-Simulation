"""Every shipped real circuit has to be the circuit it claims to be.

The geometry checks in ``test_tracks.py`` prove a layout is *consistent*: it
closes, its lengths agree, its curvature is drivable.  A layout can pass all of
that and still be the wrong shape -- a plausible circuit rather than this one.

What notices is the lap time.  These circuits were recovered from surveyed
centrelines by ``tools/extract_circuits.py``, and the recovery had no access to
any lap time; it solved the straights against the published lap length and
stopped.  So the computed lap landing near a real pole lap is an independent
agreement between the road's shape and the physics, and it is the check that
decides what ships.  ``REFERENCE.json`` records what each is measured against.

Circuits recovered cleanly but with no comparable pole lap do not ship.  See
``_not_shipped`` in that file: unverified is not the same as correct.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from f1_race_engine.physics import compute_lap_time
from f1_race_engine.physics.setup_search import optimal_wing_level
from f1_race_engine.track.io import builtin_track_names, load_track
from f1_race_engine.vehicle import Vehicle, VehicleSetup
from f1_race_engine.vehicle.io import load_builtin_vehicle


# Deliberately *outside* the tracks directory: anything with a .json in there
# is a track, and a manifest that gets loaded as one is a confusing failure.
REFERENCE_FILE = (
    pathlib.Path(__file__).resolve().parent.parent
    / "f1_race_engine"
    / "data"
    / "circuit_reference.json"
)


def _reference() -> dict:
    with REFERENCE_FILE.open(encoding="utf-8") as handle:
        return json.load(handle)


REFERENCE = _reference()
CIRCUITS = REFERENCE["circuits"]
TOLERANCE = REFERENCE["tolerance_s"]


#: Qualifying fuel.  A pole lap is set on fumes, and the reference times these
#: are checked against are pole laps.
QUALIFYING_FUEL_KG = 20.0


@pytest.fixture(scope="module")
def reference_spec():
    return load_builtin_vehicle("reference_2024")


def _pole_lap(track, spec) -> float:
    """The best lap this car can do here, under a pole lap's conditions.

    Three of those conditions are not defaults and all three matter: the wing
    is set up for this circuit rather than left where it was, the tank has
    qualifying fuel in it, and the ERS is deployed.  Comparing a default setup
    on race fuel against a pole time would measure the setup, not the circuit.
    """
    base = Vehicle(spec, VehicleSetup())
    car = Vehicle(spec, VehicleSetup(wing_level=optimal_wing_level(track, base)))
    return compute_lap_time(
        track,
        car,
        mass=car.total_mass(QUALIFYING_FUEL_KG),
        ers_power=spec.ers.max_deploy_power,
    ).lap_time


@pytest.mark.parametrize("slug", sorted(CIRCUITS))
def test_lap_length_is_the_published_one(slug):
    """The recovery solved for this, so it is exact rather than close."""
    track = load_track(slug)
    assert round(track.length) == CIRCUITS[slug]["length_m"]


@pytest.mark.parametrize("slug", sorted(CIRCUITS))
def test_lap_time_agrees_with_a_real_pole_lap(slug, reference_spec):
    """The gate.  Nothing in the recovery saw this number."""
    entry = CIRCUITS[slug]
    lap = _pole_lap(load_track(slug), reference_spec)
    delta = lap - entry["pole_s"]
    assert abs(delta) <= TOLERANCE, (
        f"{slug} computes {lap:.3f} s against {entry['pole']} pole "
        f"{entry['pole_s']:.3f} s -- {delta:+.2f} s, outside the "
        f"{TOLERANCE:.1f} s gate"
    )


def test_every_real_circuit_shipped_has_a_reference():
    """No circuit ships without something independent to check it against.

    This is the rule the file exists to enforce, so it is asserted rather than
    trusted: anything in the tracks directory that is not synthetic must appear
    in ``REFERENCE.json``, and everything referenced must actually be there.
    """
    shipped = {n for n in builtin_track_names() if not n.startswith("synthetic_")}
    assert shipped == set(CIRCUITS), (
        f"shipped without a reference: {sorted(shipped - set(CIRCUITS))}; "
        f"referenced but missing: {sorted(set(CIRCUITS) - shipped)}"
    )


def test_held_back_circuits_are_not_shipped():
    """A circuit held back stays held back, with its reason on the record."""
    held = {k: v for k, v in REFERENCE["_not_shipped"].items() if not k.startswith("_")}
    assert held, "the held-back list is documentation and must not be emptied"
    shipped = set(builtin_track_names())
    for slug, reason in held.items():
        assert slug not in shipped, f"{slug} ships but is held back: {reason}"
        assert len(reason) > 20, f"{slug} is held back without a stated reason"
