"""Debug visualisation (project rule 42).

Two independent renderers:

* :mod:`~f1_race_engine.visualization.svg` -- standalone SVG track maps using
  only the standard library.  This is also the format a web client wants.
* :mod:`~f1_race_engine.visualization.track_plots` -- matplotlib diagnostic
  plots for development.  matplotlib is an optional extra; the engine core
  never imports it.
"""

from __future__ import annotations

from .svg import SECTOR_COLOURS, centerline_path, track_to_svg

__all__ = ["SECTOR_COLOURS", "centerline_path", "track_to_svg"]


def __getattr__(name: str):
    """Expose the matplotlib plots lazily, so importing this package is cheap."""
    from . import track_plots

    if hasattr(track_plots, name):
        return getattr(track_plots, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
