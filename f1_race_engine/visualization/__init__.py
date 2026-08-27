"""Debug visualisation (project rule 42).

Two independent renderers:

* :mod:`~f1_race_engine.visualization.svg` -- standalone SVG track maps using
  only the standard library.  This is also the format a web client wants.
* :mod:`~f1_race_engine.visualization.track_plots` -- matplotlib diagnostics
  for the circuit.
* :mod:`~f1_race_engine.visualization.vehicle_plots` -- matplotlib diagnostics
  for the car: force balance, g-g envelope, performance envelope, cornering.

matplotlib is an optional extra; the engine core never imports it.
"""

from __future__ import annotations

from .svg import SECTOR_COLOURS, centerline_path, track_to_svg

__all__ = ["SECTOR_COLOURS", "centerline_path", "track_to_svg"]


_PLOT_MODULES = ("track_plots", "vehicle_plots")


def __getattr__(name: str):
    """Expose the matplotlib plots lazily, so importing this package is cheap.

    Uses :func:`importlib.import_module` rather than ``from . import x``: the
    latter asks the package for the submodule as an attribute, which lands back
    in this function and recurses forever.
    """
    import importlib

    if name in _PLOT_MODULES:
        return importlib.import_module(f".{name}", __name__)
    for module_name in _PLOT_MODULES:
        module = importlib.import_module(f".{module_name}", __name__)
        if hasattr(module, name):
            return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
