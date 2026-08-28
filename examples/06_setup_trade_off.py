"""Show the downforce/drag trade-off that makes circuits want different cars.

    python examples/06_setup_trade_off.py

Project rule 2.3 forbids per-track corrections.  Monza must favour a low-drag
car because of its long straights, and Monaco a high-downforce one because of
its slow corners -- and that has to *emerge*, not be written down.

The mechanism is induced drag.  Drag has a term proportional to the square of
the downforce being generated, so each extra unit of wing costs more than the
last.  There is no setting that is best everywhere, which is exactly the point.
"""

from __future__ import annotations

from f1_race_engine.core.units import ms_to_kph
from f1_race_engine.environment import AmbientConditions
from f1_race_engine.physics import corner_speed_limit
from f1_race_engine.physics.benchmark import benchmark_vehicle
from f1_race_engine.vehicle import Vehicle, VehicleSetup
from f1_race_engine.vehicle.io import load_builtin_vehicle

WING_LEVELS = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)
RADII = (25, 60, 120, 250)


def main() -> int:
    ambient = AmbientConditions()
    spec = load_builtin_vehicle("reference_2024")

    print(f"{spec.name} -- air density {ambient.air_density:.4f} kg/m^3\n")
    header = (
        f"{'wing':>6}{'ClA':>7}{'CdA':>8}{'L/D':>7}{'Vmax':>9}{'0-300 s':>10}"
        + "".join(f"{'R' + str(r) + ' m':>10}" for r in RADII)
    )
    print(header)
    print("-" * len(header))

    rows = []
    for wing in WING_LEVELS:
        car = Vehicle(spec, VehicleSetup(wing_level=wing))
        result = benchmark_vehicle(car, ambient, corner_radii=())
        corners = [
            corner_speed_limit(
                car, 1.0 / r, ambient.air_density, max_speed=result.top_speed
            )
            for r in RADII
        ]
        rows.append((wing, result, corners))
        time_300 = result.acceleration_times.get(300, float("inf"))
        cells = []
        for corner in corners:
            flat = corner >= result.top_speed - 1e-6
            cells.append(f"{ms_to_kph(corner):>9.1f}" + ("*" if flat else " "))
        print(
            f"{wing:>6.1f}{car.downforce_area():>7.2f}{car.drag_area():>8.3f}"
            f"{car.aero_efficiency:>7.2f}{ms_to_kph(result.top_speed):>9.1f}"
            f"{time_300:>10.2f}" + "".join(cells)
        )

    print("-" * len(header))
    print("  * flat out: the tyres are not the limit there, the engine is.")
    low, high = rows[0], rows[-1]
    print(
        f"\nFrom minimum to maximum wing:"
        f"\n  top speed        {ms_to_kph(high[1].top_speed - low[1].top_speed):+8.1f} km/h"
    )
    for index, radius in enumerate(RADII):
        delta = ms_to_kph(high[2][index] - low[2][index])
        print(f"  through R {radius:>3} m  {delta:+8.1f} km/h")

    print(
        "\nThree different regimes, all from one mechanism:\n"
        "  - the slowest corner barely moves, because at that speed there is\n"
        "    almost no downforce to add and only mechanical grip counts;\n"
        "  - the medium-fast corner gains most, because downforce is decisive\n"
        "    there and the tyres are still the limit;\n"
        "  - the fastest corner is taken flat at every setting, so extra wing\n"
        "    buys nothing and costs the whole top-speed deficit.\n"
        "\nA circuit made of long straights and slow corners therefore wants a\n"
        "different car from one made of fast sweepers -- with no per-track\n"
        "number anywhere in the engine."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
