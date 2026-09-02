"""Track data must survive a round trip through JSON."""

from __future__ import annotations

import json

import pytest

from f1_race_engine.core.errors import TrackDataError, TrackValidationError
from f1_race_engine.track.builder import build_track
from f1_race_engine.track.io import (
    builtin_track_names,
    definition_from_dict,
    definition_to_dict,
    load_builtin_definition,
    load_track,
    load_track_definition,
    save_track_definition,
    track_to_json,
)


def test_definition_round_trips_through_plain_data(proving_ground_definition):
    payload = definition_to_dict(proving_ground_definition)
    restored = definition_from_dict(json.loads(json.dumps(payload)))
    assert restored.name == proving_ground_definition.name
    assert restored.lap_length == pytest.approx(proving_ground_definition.lap_length)
    assert restored.corner_count == proving_ground_definition.corner_count
    assert definition_to_dict(restored) == payload


def test_round_trip_rebuilds_an_identical_track(proving_ground_definition, tmp_path):
    path = tmp_path / "track.json"
    save_track_definition(proving_ground_definition, path)
    restored = load_track_definition(path)
    original = build_track(proving_ground_definition)
    rebuilt = build_track(restored)
    assert [s.to_dict() for s in original.segments] == [s.to_dict() for s in rebuilt.segments]


def test_every_builtin_track_loads_and_validates():
    names = builtin_track_names()
    assert names, "no circuits are shipped with the engine"
    for name in names:
        track = load_track(name)  # validate=True by default
        assert track.length > 0


def test_load_track_by_path(tmp_path, proving_ground_definition):
    path = tmp_path / "circuit.json"
    save_track_definition(proving_ground_definition, path)
    assert load_track(path).name == proving_ground_definition.name


def test_load_track_validates_by_default(tmp_path, square_definition):
    """A circuit that fails validation must not reach the physics silently."""
    from dataclasses import replace

    from f1_race_engine.track.definitions import SectorDefinition

    broken = replace(square_definition, sectors=SectorDefinition(boundaries=()))
    path = tmp_path / "broken.json"
    save_track_definition(broken, path)
    with pytest.raises(TrackValidationError):
        load_track(path)
    assert load_track(path, validate=False).length > 0


def test_unknown_builtin_name_lists_what_is_available():
    with pytest.raises(TrackDataError, match="available"):
        load_builtin_definition("nurburgring_nordschleife")


def test_missing_file_is_reported_clearly(tmp_path):
    with pytest.raises(TrackDataError, match="not found"):
        load_track_definition(tmp_path / "absent.json")


def test_malformed_json_is_reported_clearly(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{oops")
    with pytest.raises(TrackDataError, match="valid JSON"):
        load_track_definition(path)


@pytest.mark.parametrize(
    "payload",
    [
        {"layout": []},
        {"name": "x"},
        {"name": "x", "layout": []},
        {"name": "x", "layout": [{"type": "spiral", "length": 10.0}]},
    ],
)
def test_malformed_definitions_are_rejected(payload):
    with pytest.raises(TrackDataError):
        definition_from_dict(payload)


def test_track_export_is_json_serialisable(proving_ground):
    payload = json.loads(track_to_json(proving_ground))
    assert payload["name"] == proving_ground.name
    assert payload["length"] == pytest.approx(proving_ground.length)
    assert "segments" not in payload

    with_segments = json.loads(track_to_json(proving_ground, include_segments=True))
    assert len(with_segments["segments"]) == len(proving_ground.segments)


def test_shipped_files_are_definitions_not_segments():
    """Storing built segments would freeze one resolution into the data."""
    from f1_race_engine.track.io import BUILTIN_TRACK_DIR

    for path in BUILTIN_TRACK_DIR.glob("*.json"):
        payload = json.loads(path.read_text())
        assert "layout" in payload
        assert "segments" not in payload
