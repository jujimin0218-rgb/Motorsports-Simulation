"""Debug visualisation (project rule 42).

The engine core must never depend on matplotlib, so the SVG renderer is tested
unconditionally and the matplotlib plots are skipped when it is absent.
"""

from __future__ import annotations

import xml.etree.ElementTree as ElementTree

import pytest

from f1_race_engine.visualization import track_to_svg
from f1_race_engine.visualization.svg import centerline_path


def test_svg_is_well_formed_xml(builtin_track):
    root = ElementTree.fromstring(track_to_svg(builtin_track))
    assert root.tag.endswith("svg")
    assert root.get("viewBox") == "0 0 900 620"


def test_svg_contains_the_track_identity(proving_ground):
    svg = track_to_svg(proving_ground)
    assert proving_ground.name in svg
    assert f"{proving_ground.length:.0f} m" in svg
    assert "corners" in svg


def test_svg_marks_sectors_drs_and_corners(proving_ground):
    svg = track_to_svg(proving_ground)
    assert "Sector 1" in svg and "Sector 3" in svg
    assert "DRS zone 0" in svg
    assert "Start/finish" in svg


def test_svg_options_can_be_switched_off(proving_ground):
    svg = track_to_svg(
        proving_ground,
        colour_by_sector=False,
        show_drs=False,
        show_corners=False,
        show_start=False,
        background=None,
    )
    ElementTree.fromstring(svg)
    assert "DRS zone" not in svg
    assert "Sector 1" not in svg


def test_svg_escapes_special_characters(square_definition):
    from dataclasses import replace

    from f1_race_engine.track.builder import build_track

    track = build_track(replace(square_definition, name='Ampersand & "quotes" <tag>'))
    svg = track_to_svg(track)
    ElementTree.fromstring(svg)  # would raise if the name were not escaped
    assert "&amp;" in svg


def test_centerline_path_formatting():
    assert centerline_path([(0.0, 0.0), (10.0, 5.0)], close=False) == "M 0.00 0.00 L 10.00 5.00"
    assert centerline_path([(0.0, 0.0), (10.0, 5.0)]).endswith("Z")
    assert centerline_path([]) == ""


def test_engine_core_does_not_import_matplotlib():
    """A headless race simulation must carry no plotting dependency."""
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import f1_race_engine; import f1_race_engine.track; "
            "assert 'matplotlib' not in sys.modules, sorted(sys.modules)[:5]; "
            "print('clean')",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "clean" in result.stdout


matplotlib = pytest.importorskip("matplotlib", reason="optional plotting extra")


@pytest.fixture(autouse=True, scope="module")
def _headless_backend():
    matplotlib.use("Agg")


def test_track_overview_renders(proving_ground, tmp_path):
    from f1_race_engine.visualization.track_plots import save_track_overview

    path = save_track_overview(proving_ground, str(tmp_path / "overview.png"))
    assert (tmp_path / "overview.png").stat().st_size > 10_000


def test_individual_plots_render(square_track):
    import matplotlib.pyplot as plt

    from f1_race_engine.visualization import track_plots

    for plot in (
        track_plots.plot_curvature,
        track_plots.plot_radius,
        track_plots.plot_elevation,
        track_plots.plot_banking,
        track_plots.plot_width,
        track_plots.plot_map,
    ):
        axes = plot(square_track)
        assert axes is not None
        plt.close("all")


def test_plots_are_reachable_from_the_package(proving_ground):
    from f1_race_engine import visualization

    assert callable(visualization.plot_map)
    with pytest.raises(AttributeError):
        visualization.definitely_not_a_plot


def test_vehicle_overview_renders(car, tmp_path):
    from f1_race_engine.visualization.vehicle_plots import save_vehicle_overview

    save_vehicle_overview(car, str(tmp_path / "vehicle.png"))
    assert (tmp_path / "vehicle.png").stat().st_size > 10_000


def test_individual_vehicle_plots_render(car):
    import matplotlib.pyplot as plt

    from f1_race_engine.visualization import vehicle_plots

    for plot in (
        vehicle_plots.plot_force_balance,
        vehicle_plots.plot_gg_diagram,
        vehicle_plots.plot_performance_envelope,
        vehicle_plots.plot_cornering,
    ):
        assert plot(car) is not None
        plt.close("all")


def test_vehicle_plots_are_reachable_from_the_package():
    from f1_race_engine import visualization

    assert callable(visualization.plot_gg_diagram)
