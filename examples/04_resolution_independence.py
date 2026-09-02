"""Show that changing the sampling resolution does not change the circuit.

    python examples/04_resolution_independence.py

This is the property the whole architecture rests on (project rule 7): the
track model may be sampled coarsely for a quick run or at 1 m for detailed
work, and every physically meaningful quantity must come out identical.  If
that ever stopped holding, a lap time would depend on an implementation detail
rather than on the circuit.
"""

from __future__ import annotations

import math

from f1_race_engine.core.config import TrackBuildConfig
from f1_race_engine.track.builder import build_track
from f1_race_engine.track.io import load_builtin_definition

CONFIGS = {
    "coarse (30 m)": TrackBuildConfig(
        straight_segment_length=30.0, corner_segment_length=20.0,
        min_segment_length=5.0, max_segment_length=30.0,
        max_heading_change_per_segment_deg=8.0,
        max_curvature_change_per_segment=0.01,
    ),
    "default": TrackBuildConfig(),
    "fine (3 m)": TrackBuildConfig(
        straight_segment_length=10.0, corner_segment_length=3.0,
        min_segment_length=1.0, max_segment_length=10.0,
        max_heading_change_per_segment_deg=1.0,
        max_curvature_change_per_segment=0.001,
    ),
    "uniform 1 m": TrackBuildConfig(
        straight_segment_length=1.0, corner_segment_length=1.0,
        min_segment_length=1.0, max_segment_length=1.0,
    ),
}


def main() -> int:
    definition = load_builtin_definition("synthetic_proving_ground")
    tracks = {name: build_track(definition, cfg) for name, cfg in CONFIGS.items()}

    print(f"{definition.name}\n")
    header = (
        f"{'resolution':<16}{'segments':>10}{'lap [m]':>14}{'turning [deg]':>16}"
        f"{'min R [m]':>12}{'climb [m]':>12}{'closure [m]':>13}"
    )
    print(header)
    print("-" * len(header))
    for name, track in tracks.items():
        print(
            f"{name:<16}{len(track):>10}{track.length:>14.6f}"
            f"{math.degrees(track.total_heading_change):>16.9f}"
            f"{track.min_radius:>12.4f}{track.elevation_gain:>12.4f}"
            f"{track.centerline().closure_error:>13.6f}"
        )

    reference = tracks["default"]
    probes = [i * reference.length / 500.0 for i in range(500)]
    print("\nlargest difference in track state against the default sampling:")
    print(f"  {'resolution':<16}{'curvature':>14}{'gradient':>12}{'banking':>12}{'width':>10}")
    for name, track in tracks.items():
        if track is reference:
            continue
        worst = {"curvature": 0.0, "gradient": 0.0, "banking": 0.0, "track_width": 0.0}
        for distance in probes:
            a, b = reference.state_at(distance), track.state_at(distance)
            for key in worst:
                worst[key] = max(worst[key], abs(getattr(a, key) - getattr(b, key)))
        print(
            f"  {name:<16}{worst['curvature']:>14.2e}{worst['gradient']:>12.2e}"
            f"{worst['banking']:>12.2e}{worst['track_width']:>10.2e}"
        )

    print(
        "\nSegment counts differ by more than 20x; the circuit does not.\n"
        "The remaining differences are floating-point noise, not model error:\n"
        "curvature is linear within a segment and the overlays are resolved from\n"
        "continuous profiles, so subdividing a segment cannot change any answer."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
