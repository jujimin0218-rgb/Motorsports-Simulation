"""Watch a session get rained on.

    python examples/16_wet_weather.py [--minutes 90] [--rain 0.6]

Nothing here schedules a shower.  The weather is a process -- an
Ornstein-Uhlenbeck walk for temperature, a Poisson pair for showers arriving
and passing -- driven by the seeded RNG, so the same seed gives the same
afternoon and a different one gives a different afternoon (project rule 30).

Everything the rain does downstream follows from two quantities: how deep the
water on the road is, and how much of it the tread on the car can get out of
the way at the speed it is going.  The right tyre for each moment is not looked
up; it is whichever compound the physics says has the most grip.
"""

from __future__ import annotations

import argparse

from f1_race_engine.core.rng import RngHub
from f1_race_engine.environment import Forecast, TrackEvolution, WeatherModel
from f1_race_engine.race import compound_for_conditions
from f1_race_engine.track.io import load_track
from f1_race_engine.track.surface import TrackConditions
from f1_race_engine.tyres.io import load_builtin_compounds
from f1_race_engine.tyres.wet import aquaplaning_speed, wet_grip_factor

#: Speed the wet-grip column is quoted at, m/s (about 200 km/h).
REFERENCE_SPEED = 55.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--minutes", type=int, default=90)
    parser.add_argument("--track", default="synthetic_proving_ground")
    parser.add_argument("--rain", type=float, default=0.6)
    parser.add_argument("--cars", type=int, default=20)
    parser.add_argument("--seed", type=int, default=11)
    args = parser.parse_args()

    track = load_track(args.track)
    compounds = load_builtin_compounds()
    conditions = TrackConditions(track.segments)
    evolution = TrackEvolution(conditions)
    weather = WeatherModel(
        Forecast(air_temperature=22.0, cloud_cover=0.45, rain_probability=args.rain),
        RngHub(args.seed),
    )

    print(f"{track.name} -- {args.minutes} minutes, {args.cars} cars running")
    print(f"forecast: {args.rain:.0%} chance of rain, seed {args.seed}\n")
    header = (
        f"{'min':>4}{'air':>7}{'track':>8}{'rain':>7}{'water':>9}"
        f"{'wet':>6}{'rubber':>8}{'grip':>7}  tyre   tyre grip  aquaplanes above"
    )
    print(header)
    print("-" * len(header))

    step = 300.0
    car_laps = args.cars * step / 90.0
    for minute in range(0, args.minutes + 1, 5):
        if minute:
            state = weather.advance(step)
            evolution.apply_weather(state, step)
            evolution.run_laps(car_laps)
        else:
            state = weather.state

        water = evolution.mean_water_depth
        tyre = compound_for_conditions(compounds.compounds, water)
        tyre_grip = wet_grip_factor(tyre, water, REFERENCE_SPEED)
        limit = aquaplaning_speed(tyre, water)
        if tyre.peak_water_depth <= 0.0:
            limit_text = "no tread" if water > 0.0 else "--"
        elif limit == float("inf"):
            limit_text = "--"
        else:
            limit_text = f"{limit * 3.6:.0f} km/h"
        print(
            f"{minute:4d}{state.air_temperature:7.1f}{state.track_temperature:8.1f}"
            f"{state.rain_intensity:7.2f}{water * 1000:8.2f}mm"
            f"{evolution.wet_fraction:6.0%}{conditions.mean_rubber:8.2f}"
            f"{conditions.grip_multiplier(0):7.3f}  {tyre.code:<4}"
            f"{tyre_grip:11.3f}  {limit_text}"
        )

    print(
        "\nrubber   what the cars put down, and what the rain washed off again"
        "\nwet      share of the circuit still holding water -- it falls first"
        "\n         where the road slopes, and that is the drying line"
        "\ngrip     the surface: wet asphalt grips less whatever is on it"
        f"\ntyre grip what the chosen tread can deliver at {REFERENCE_SPEED * 3.6:.0f} km/h,"
        "\n         which is the other half and the half that depends on the tyre"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
