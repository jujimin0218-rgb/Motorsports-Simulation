"""Render debug plots and SVG maps for the shipped circuits (project rule 42).

    python examples/03_visualise.py [--out build/] [--no-plots]

The SVG export needs nothing but the standard library.  The matplotlib
overview is optional: install it with ``pip install 'f1-race-engine[viz]'``.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from f1_race_engine.track.io import builtin_track_names, load_track
from f1_race_engine.visualization.svg import track_to_svg


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("build/track_plots"))
    parser.add_argument("--no-plots", action="store_true", help="SVG only")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    for name in builtin_track_names():
        track = load_track(name)

        svg_path = args.out / f"{name}.svg"
        svg_path.write_text(track_to_svg(track), encoding="utf-8")
        print(f"{svg_path}")

        if args.no_plots:
            continue
        try:
            from f1_race_engine.visualization.track_plots import save_track_overview
        except ImportError as exc:
            print(f"  (skipping plots: {exc})")
            args.no_plots = True
            continue
        print(f"{save_track_overview(track, str(args.out / f'{name}.png'))}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
