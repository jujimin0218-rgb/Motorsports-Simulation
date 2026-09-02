"""Walk a lap and print the track state -- the core query of the whole engine.

    python examples/02_track_state.py [--track NAME] [--step 50]

Project rule 5: a track is a mapping from distance to track state.  Everything
later -- the speed profile, the lap simulation, overtaking -- is built on this
one query.  Nothing here knows how finely the track was sampled.
"""

from __future__ import annotations

import argparse

from f1_race_engine.core.units import ms_to_kph, rad_to_deg
from f1_race_engine.track.curvature import nominal_corner_speed
from f1_race_engine.track.io import load_track
from f1_race_engine.track.surface import TrackConditions


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--track", default="synthetic_proving_ground")
    parser.add_argument("--step", type=float, default=50.0, help="sample spacing, m")
    parser.add_argument("--wet", action="store_true", help="put 3 mm of water down")
    args = parser.parse_args()

    track = load_track(args.track)
    conditions = TrackConditions(track.segments)
    if args.wet:
        for condition in (conditions[i] for i in range(len(conditions))):
            condition.water_depth = 0.003

    print(f"{track.name} -- {track.length:.0f} m, {len(track)} segments")
    print(f"{'dist':>8}{'R':>9}{'grad':>8}{'bank':>7}{'grip':>7}{'width':>7}"
          f"{'sec':>5}{'DRS':>5}  {'~km/h':>7}  where")
    print("-" * 88)

    distance = 0.0
    while distance < track.length:
        state = track.state_at(distance, conditions)
        radius = "straight" if state.radius == float("inf") else f"{abs(state.radius):.0f}"
        speed = nominal_corner_speed(abs(state.radius))
        speed_text = "  --  " if speed == float("inf") else f"{ms_to_kph(speed):.0f}"
        where = state.corner_name or state.kind.value
        print(
            f"{distance:>8.0f}{radius:>9}{state.gradient * 100:>7.1f}%"
            f"{rad_to_deg(state.banking):>7.1f}{state.grip:>7.3f}"
            f"{state.track_width:>7.1f}{state.sector:>5}"
            f"{'yes' if state.has_drs else '-':>5}  {speed_text:>7}  {where}"
        )
        distance += args.step

    print("-" * 88)
    print(
        "The nominal speed column is a radius-derived label for orientation only.\n"
        "Real cornering speed arrives in Phase 3, from the car's grip, downforce\n"
        "and mass -- never from a per-track number."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
