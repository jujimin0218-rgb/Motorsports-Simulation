"""Configuration must round-trip, merge deeply and reject bad data loudly."""

from __future__ import annotations

import json

import pytest

from f1_race_engine.core.config import (
    PhysicsConfig,
    SimulationConfig,
    TrackBuildConfig,
    config_from_overrides,
    default_config,
    load_config,
    save_config,
)
from f1_race_engine.core.errors import ConfigError


def test_defaults_are_valid():
    config = default_config()
    assert config.physics.gravity == pytest.approx(9.80665)
    assert config.track_build.min_segment_length <= config.track_build.max_segment_length


def test_round_trip_through_plain_data():
    config = default_config()
    assert SimulationConfig.from_dict(config.to_dict()) == config


def test_round_trip_through_json_file(tmp_path):
    config = default_config().merged({"randomness": {"seed": 4242}})
    path = tmp_path / "config.json"
    save_config(config, path)
    assert load_config(path) == config
    assert json.loads(path.read_text())["randomness"]["seed"] == 4242


def test_merge_is_deep_and_leaves_the_original_untouched():
    base = default_config()
    merged = base.merged(
        {"track_build": {"straight_segment_length": 10.0}, "randomness": {"seed": 42}}
    )
    assert merged.track_build.straight_segment_length == 10.0
    assert merged.randomness.seed == 42
    # Untouched fields survive the merge...
    assert merged.track_build.corner_segment_length == base.track_build.corner_segment_length
    # ...and the original is unchanged.
    assert base.track_build.straight_segment_length == 25.0
    assert base.randomness.seed == 20260812


def test_merge_accepts_a_ready_made_section():
    merged = default_config().merged({"physics": PhysicsConfig(gravity=3.71)})
    assert merged.physics.gravity == pytest.approx(3.71)


def test_config_is_frozen():
    with pytest.raises(Exception):
        default_config().physics.gravity = 1.0  # type: ignore[misc]


@pytest.mark.parametrize(
    "overrides",
    [
        {"track_buildd": {}},
        {"track_build": {"straight_segment_lenght": 5.0}},
        {"physics": {"gravity": -1.0}},
        {"physics": {"epsilon": 0.0}},
        {"randomness": {"seed": "nope"}},
        {"randomness": {"seed": -5}},
        {"track_build": {"min_segment_length": 50.0}},
        {"track_build": {"geometry_quadrature_intervals": 3}},
        {"track_validation": {"min_corner_radius": 100.0}},
        {"track_conditions": {"marble_grip_penalty": 2.0}},
    ],
)
def test_invalid_configuration_is_rejected(overrides):
    """A typo must fail loudly: silently ignoring it looks like a parameter
    that has no effect, which is far worse to debug during calibration."""
    with pytest.raises(ConfigError):
        default_config().merged(overrides)


def test_unknown_key_error_names_the_offender():
    with pytest.raises(ConfigError, match="straight_segment_lenght"):
        TrackBuildConfig.from_dict({"straight_segment_lenght": 5.0})


def test_config_from_overrides():
    assert config_from_overrides() == default_config()
    assert config_from_overrides({"randomness": {"seed": 5}}).randomness.seed == 5


def test_missing_file_raises_config_error(tmp_path):
    with pytest.raises(ConfigError):
        load_config(tmp_path / "nope.json")


def test_malformed_json_raises_config_error(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not json")
    with pytest.raises(ConfigError):
        load_config(path)


def test_partial_config_file_uses_defaults_for_the_rest(tmp_path):
    path = tmp_path / "partial.json"
    path.write_text(json.dumps({"randomness": {"seed": 7}}))
    config = load_config(path)
    assert config.randomness.seed == 7
    assert config.physics.gravity == pytest.approx(9.80665)


def test_describe_renders_flat_keys():
    text = default_config().describe()
    assert "physics.gravity = 9.80665" in text
    assert "track_build.straight_segment_length" in text


def test_heading_criterion_converts_to_radians():
    config = TrackBuildConfig(max_heading_change_per_segment_deg=180.0)
    assert config.max_heading_change_per_segment == pytest.approx(3.141592653589793)
