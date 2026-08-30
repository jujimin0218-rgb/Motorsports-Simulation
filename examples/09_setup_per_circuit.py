"""Let each circuit choose its own setup (project rule 2.3).

    python examples/09_setup_per_circuit.py

There are no per-track corrections in this engine.  What there is instead is
induced drag: ``CdA = CdA0 + k*ClA^2``, so every extra unit of wing costs more
than the last.  Sweep the wing level on each circuit and the optimum lands
somewhere different every time -- minimum wing where the straights dominate,
maximum where the corners do, and somewhere in between when the circuit is
genuinely balanced.
"""

from __future__ import annotations

from f1_race_engine.core.units import ms_to_kph
from f1_race_engine.physics.setup_search import wing_level_sweep
from f1_race_engine.track.io import builtin_track_names, load_track
from f1_race_engine.vehicle import Vehicle
from f1_race_engine.vehicle.io import load_builtin_vehicle

LEVELS = tuple(i / 10.0 for i in range(11))


def main() -> int:
    spec = load_builtin_vehicle("reference_2024")
    sweeps = {}

    for name in builtin_track_names():
        track = load_track(name)
        sweeps[name] = wing_level_sweep(track, Vehicle(spec), levels=LEVELS)

    label = f"{'wing':>6}"
    header = label + "".join(
        f"{n.replace('synthetic_', ''):>20}" for n in sweeps
    )
    print(f"Lap time by wing level -- {spec.name}\n")
    print(header)
    print("-" * len(header))
    for index, level in enumerate(LEVELS):
        cells = ""
        for sweep in sweeps.values():
            point = sweep.points[index]
            marker = " *" if point is sweep.best else "  "
            cells += f"{point.lap_time:>18.3f}{marker}"
        print(f"{level:>6.1f}{cells}")
    print("-" * len(header))

    print("\nWhat each circuit wants:")
    for name, sweep in sweeps.items():
        interior = " (interior optimum)" if sweep.is_interior_optimum else ""
        print(
            f"  {name.replace('synthetic_', ''):<20} wing {sweep.best.wing_level:.1f}"
            f"   worst setting costs {sweep.spread:+.3f} s"
            f"   top speed {ms_to_kph(sweep.best.top_speed):.0f} km/h{interior}"
        )

    print(
        "\nThe optimum spans the whole range, and the balanced circuit has a\n"
        "genuine interior optimum -- it wants some downforce but not all of it.\n"
        "No part of the engine knows any of these circuits by name."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
