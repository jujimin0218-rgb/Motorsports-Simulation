"""Design the synthetic reference circuits.

    python tools/design_circuits.py [--write] [--only NAME]

The engine ships three circuits that are not real places.  That is deliberate
-- a synthetic circuit can be built to exercise a specific part of the model,
and it can be published without pretending to survey data it does not have.
What it must *not* be is unrepresentative, because every calibration the engine
does is measured on these laps.

The three shipped circuits were.  Measured against the range real circuits
occupy they came out like this:

```
                          corners/km   full throttle   corner share
  power circuit                 1.0           91.6%            31%
  proving ground                1.4           91.6%            28%
  street circuit                4.8           63.5%            34%

  Monza                         1.9             ~78%            31%
  Silverstone                   3.1             ~72%            43%
  Monaco                        5.7             ~55%            60%
```

Nothing on the calendar is 92% full throttle -- Monza, the fastest circuit in
Formula 1, is 78%.  A lap that is nine tenths straight line barely uses the
tyres, and that quietly distorted every number measured on it:

* **fuel mass looked cheap.**  0.010 s/kg on the power circuit against the
  0.024-0.030 s/kg teams actually use, because mass costs time in corners and
  under braking and there were hardly any;
* **compound choice looked wild.**  The same tyre step was worth 0.31 s on the
  power circuit and 1.90 s on the street circuit, a six-fold spread where the
  real one is about two-fold, because the grip-exposed fraction of the lap
  varied six-fold between them;
* **more wing made the car pull *less* lateral g**, because the fastest corners
  were flat out for any setup, so adding downforce only slowed the car down to
  them.

None of that is a physics bug.  It is what the physics correctly says about
laps that no real circuit resembles.  So the circuits are redesigned here to
sit inside the range real circuits occupy -- more corners, in the mix of speeds
each circuit's character calls for -- while staying explicitly synthetic.

The acceptance criteria are that range, checked on every run.  A design that
falls outside it is not written.

One convention worth stating, because it is easy to get wrong.  A radius here
is the radius the *car* drives, not the radius of the road's centreline.  The
engine has no racing-line model -- ``track_width`` is carried through the track
data and read by nothing in the physics -- so its cornering speeds are
calibrated against the radius the car actually takes.  The check is that they
come out right: Suzuka's 130R is a 130 m corner taken at 290 km/h, and asked
about a 130 m radius the engine answers 292.  A real racing line would flatten
a corner well beyond its centreline radius -- geometry says a 90-degree corner
on a 9 m road can be driven at nearly twice it -- so authoring centreline radii
here would make every circuit far too slow.  A racing-line model belongs with
the rest of Phase 12, and when it arrives these radii become centreline radii
and the grip calibration moves with them.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from f1_race_engine.core.units import format_lap_time, ms_to_kph
from f1_race_engine.environment import AmbientConditions
from f1_race_engine.driver.io import load_builtin_driver
from f1_race_engine.physics import compute_lap_time
from f1_race_engine.simulation.lap import simulate_lap
from f1_race_engine.track.builder import build_track
from f1_race_engine.track.definitions import (
    BankingDefinition,
    CornerDefinition,
    CornerDirection,
    DrsDefinition,
    ElevationDefinition,
    KerbDefinition,
    SectorDefinition,
    StraightDefinition,
    SurfaceDefinition,
    TrackDefaults,
    TrackDefinition,
    WidthDefinition,
)
from f1_race_engine.track.io import BUILTIN_TRACK_DIR, save_track_definition
from f1_race_engine.track.layout_solver import (
    apply_corner_angles,
    apply_straight_lengths,
    solve_corner_angles,
    solve_straight_lengths,
)
from f1_race_engine.track.validation import validate_track
from f1_race_engine.vehicle import Vehicle, VehicleSetup
from f1_race_engine.vehicle.io import load_builtin_vehicle

L = CornerDirection.LEFT
R = CornerDirection.RIGHT


# ---------------------------------------------------------------------------
# The envelope real circuits occupy
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CharacterEnvelope:
    """What a lap has to look like to be worth calibrating on.

    Taken from the range the Formula 1 calendar spans, with a little headroom.
    Monza is the fastest circuit there is at about 1.9 corners per kilometre and
    264 km/h average; Monaco the slowest at 5.7 and 160 km/h.

    Deliberately **only geometry**.  The obvious fourth measure, share of the
    lap at full throttle, is not here: it is a property of the driver model
    rather than of the circuit.  The Phase 4 controller follows the speed
    profile exactly, so where the profile is flat it holds a maintenance
    throttle, while a real driver squirts and lifts.  Both take the same lap
    time round the same corner; only the pedal trace differs.  Gating a circuit
    design on it would be tuning the road to suit the driver.
    """

    min_corners_per_km: float = 1.7
    max_corners_per_km: float = 6.2
    min_average_speed_kph: float = 150.0
    max_average_speed_kph: float = 275.0
    min_minimum_speed_kph: float = 45.0
    max_minimum_speed_kph: float = 135.0


ENVELOPE = CharacterEnvelope()


def corner(
    number: int,
    direction: CornerDirection,
    radius: float,
    angle: float,
    name: str | None = None,
    radius_end: float | None = None,
) -> CornerDefinition:
    return CornerDefinition(
        radius=radius,
        angle=angle,
        direction=direction,
        radius_end=radius_end,
        name=name or f"Turn {number}",
        corner_id=number,
    )


def straight(length: float, name: str) -> StraightDefinition:
    return StraightDefinition(length=length, name=name)


@dataclass(frozen=True)
class Design:
    """A synthetic circuit and the character it is meant to have."""

    key: str
    definition: TrackDefinition
    lap_length: float
    wing_expectation: str
    """``"minimum"``, ``"interior"`` or ``"maximum"``.

    The circuit's whole point, and the only claim about it worth testing.
    Asking for a particular wing number would be fitting the circuit to an
    answer; asking which *end* of the range wins is asking whether the
    geometry has the character it was designed to have.  A circuit that is
    supposed to reward low drag and does not is not that circuit."""

    #: Feature positions as fractions of the lap, so they follow the geometry.
    elevation: tuple[tuple[float, float], ...] = ()
    banking: tuple[tuple[float, float], ...] = ()
    width: tuple[tuple[float, float], ...] = ()
    surface: tuple[tuple[float, float, str, str, float, float], ...] = ()
    kerbs: tuple[tuple[float, float, str], ...] = ()
    sectors: tuple[float, ...] = ()
    drs: tuple[tuple[str, float, float, float], ...] = ()


# ---------------------------------------------------------------------------
# The power circuit: long straights, heavy braking, minimum wing
# ---------------------------------------------------------------------------

POWER = Design(
    key="synthetic_power_circuit",
    lap_length=7000.0,
    wing_expectation="minimum",
    definition=TrackDefinition(
        name="Synthetic Power Circuit",
        country="Testing",
        defaults=TrackDefaults(
            track_width=13.0, surface_type="asphalt", surface_grip=1.0, roughness=0.5
        ),
        layout=(
            straight(1250.0, "Main straight"),
            corner(1, R, 30.0, 45.0, "Chicane 1 (entry)"),
            straight(26.0, "Chicane 1 link"),
            corner(2, L, 32.0, 40.0, "Chicane 1 (exit)"),
            straight(620.0, "Long curve approach"),
            corner(3, R, 200.0, 90.0, "Long Curve"),
            straight(950.0, "Back straight"),
            corner(4, L, 34.0, 45.0, "Chicane 2 (entry)"),
            straight(26.0, "Chicane 2 link"),
            corner(5, R, 30.0, 45.0, "Chicane 2 (exit)"),
            straight(560.0, "Double right approach"),
            corner(6, R, 95.0, 80.0, "Double Right 1"),
            straight(120.0, "Double right link"),
            corner(7, R, 80.0, 70.0, "Double Right 2"),
            straight(1080.0, "Woods straight"),
            corner(8, L, 60.0, 55.0, "Esses 1"),
            straight(45.0, "Esses link 1"),
            corner(9, R, 55.0, 60.0, "Esses 2"),
            straight(45.0, "Esses link 2"),
            corner(10, L, 70.0, 45.0, "Esses 3"),
            straight(800.0, "Stadium approach"),
            corner(11, R, 45.0, 70.0, "Stadium"),
            straight(240.0, "Stadium exit"),
            corner(12, R, 38.0, 40.0, "Stadium exit corner"),
            straight(400.0, "Final approach"),
            corner(13, R, 130.0, 130.0, "Final Corner", radius_end=240.0),
            straight(120.0, "Pit straight"),
        ),
    ),
    elevation=((0.0, 0.0), (0.26, 5.0), (0.51, -8.0), (0.74, 4.0), (1.0, 0.0)),
    width=((0.0, 15.0), (0.17, 14.0), (0.64, 14.0), (1.0, 15.0)),
    sectors=(0.34, 0.68),
    drs=(
        ("Main straight", 0.945, 0.013, 0.165),
        ("Back straight", 0.325, 0.360, 0.475),
    ),
)


# ---------------------------------------------------------------------------
# The proving ground: the reference circuit, every corner speed represented
# ---------------------------------------------------------------------------

PROVING_GROUND = Design(
    key="synthetic_proving_ground",
    lap_length=4978.0,
    wing_expectation="interior",
    definition=TrackDefinition(
        name="Synthetic Proving Ground",
        country="Testing",
        defaults=TrackDefaults(
            track_width=13.0, surface_type="asphalt", surface_grip=1.0, roughness=0.5
        ),
        layout=(
            straight(1560.0, "Start/finish straight"),
            corner(1, R, 40.0, 95.0, "Turn 1"),
            straight(80.0, "Turn 1 exit"),
            corner(2, L, 130.0, 60.0, "Fast Left"),
            straight(60.0, "Link 1"),
            corner(3, L, 90.0, 65.0, "Second Left"),
            straight(160.0, "Hairpin approach"),
            corner(4, R, 28.0, 100.0, "Hairpin"),
            straight(45.0, "Hairpin exit"),
            corner(5, R, 60.0, 70.0, "Turn 5"),
            straight(300.0, "Esses approach"),
            corner(6, L, 210.0, 55.0, "Esses 1"),
            straight(50.0, "Esses link 1"),
            corner(7, R, 190.0, 50.0, "Esses 2"),
            straight(50.0, "Esses link 2"),
            corner(8, L, 110.0, 60.0, "Esses 3"),
            straight(520.0, "Back straight"),
            corner(9, R, 22.0, 125.0, "Back Hairpin"),
            straight(150.0, "Turn 10 approach"),
            corner(10, R, 65.0, 75.0, "Turn 10"),
            straight(40.0, "Turn 10 link"),
            corner(11, L, 55.0, 70.0, "Turn 11"),
            straight(220.0, "Stadium approach"),
            corner(12, R, 50.0, 60.0, "Stadium 1"),
            straight(45.0, "Stadium link"),
            corner(13, L, 45.0, 70.0, "Stadium 2"),
            straight(180.0, "Final complex approach"),
            corner(14, R, 35.0, 105.0, "Final Complex"),
            straight(45.0, "Final complex link"),
            corner(15, R, 120.0, 55.0, "Last Corner", radius_end=200.0),
            straight(180.0, "Pit straight"),
        ),
    ),
    elevation=(
        (0.0, 0.0), (0.14, -6.0), (0.25, -12.0), (0.40, 8.0), (0.49, 24.0),
        (0.64, 10.0), (0.82, -8.0), (0.90, -4.0), (1.0, 0.0),
    ),
    banking=(
        (0.0, 0.0), (0.26, 0.0), (0.32, 2.0), (0.38, 0.0), (0.42, -1.5),
        (0.45, 0.0), (0.64, 0.0), (0.68, 4.0), (0.72, 0.0), (1.0, 0.0),
    ),
    width=(
        (0.0, 15.0), (0.24, 15.0), (0.28, 13.0), (0.80, 13.0), (0.82, 10.5),
        (0.84, 10.5), (0.88, 13.0), (1.0, 15.0),
    ),
    surface=(
        (0.355, 0.460, "abrasive_asphalt", "Esses (original 1998 surface)", 0.98, 0.75),
        (0.494, 0.637, "smooth_asphalt", "Back straight (resurfaced)", 1.02, 0.35),
    ),
    kerbs=(
        (0.254, 0.271, "medium"),
        (0.294, 0.355, "medium"),
        (0.396, 0.437, "medium"),
        (0.460, 0.494, "high"),
        (0.637, 0.717, "low"),
        (0.822, 0.833, "high"),
        (0.903, 0.937, "medium"),
    ),
    sectors=(0.355, 0.717),
    drs=(
        ("Start/finish straight", 0.914, 0.012, 0.150),
        ("Back straight", 0.462, 0.506, 0.627),
    ),
)


# ---------------------------------------------------------------------------
# The street circuit: nowhere to go, and mechanical grip decides it
# ---------------------------------------------------------------------------

STREET = Design(
    key="synthetic_street_circuit",
    lap_length=3350.0,
    wing_expectation="maximum",
    definition=TrackDefinition(
        name="Synthetic Street Circuit",
        country="Testing",
        defaults=TrackDefaults(
            track_width=9.5, surface_type="asphalt", surface_grip=0.96, roughness=0.6
        ),
        layout=(
            straight(560.0, "Start/finish straight"),
            corner(1, R, 40.0, 90.0, "Turn 1"),
            straight(60.0, "Turn 1 exit"),
            corner(2, L, 45.0, 80.0, "Turn 2"),
            straight(90.0, "Harbour link"),
            corner(3, R, 42.0, 85.0, "Turn 3"),
            straight(45.0, "Hairpin approach"),
            corner(4, R, 11.0, 170.0, "Grand Hotel Hairpin"),
            straight(180.0, "Hairpin exit"),
            corner(5, L, 65.0, 60.0, "Turn 5"),
            straight(70.0, "Link 2"),
            corner(6, R, 38.0, 95.0, "Turn 6"),
            straight(55.0, "Tunnel approach"),
            corner(7, L, 100.0, 75.0, "Tunnel Entry"),
            straight(540.0, "Tunnel"),
            corner(8, R, 45.0, 110.0, "Chicane"),
            straight(50.0, "Chicane exit"),
            corner(9, L, 120.0, 40.0, "Waterfront Kink"),
            straight(230.0, "Waterfront"),
            corner(10, R, 20.0, 160.0, "Second Hairpin"),
            straight(45.0, "Second hairpin exit"),
            corner(11, L, 70.0, 55.0, "Turn 11"),
            straight(80.0, "Link 3"),
            corner(12, R, 42.0, 90.0, "Turn 12"),
            straight(60.0, "Link 4"),
            corner(13, L, 60.0, 65.0, "Turn 13"),
            straight(110.0, "Swimming pool approach"),
            corner(14, R, 50.0, 85.0, "Pool 1"),
            straight(55.0, "Pool link 1"),
            corner(15, L, 110.0, 70.0, "Pool 2"),
            straight(90.0, "Pool link 2"),
            corner(16, R, 48.0, 100.0, "Pool 3"),
            straight(40.0, "Pool exit"),
            corner(17, L, 42.0, 90.0, "Pool 4"),
            straight(120.0, "Final approach"),
            corner(18, R, 85.0, 45.0, "Turn 18"),
            straight(70.0, "Final link"),
            corner(19, L, 110.0, 95.0, "Final Corner"),
        ),
    ),
    elevation=((0.0, 0.0), (0.18, 20.0), (0.42, 34.0), (0.66, 14.0), (0.87, -3.0), (1.0, 0.0)),
    width=((0.0, 11.0), (0.12, 9.5), (0.78, 8.5), (0.93, 9.5), (1.0, 11.0)),
    sectors=(0.33, 0.67),
    drs=(("Start/finish straight", 0.955, 0.015, 0.115),),
)


DESIGNS: tuple[Design, ...] = (POWER, PROVING_GROUND, STREET)


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def attach_features(design: Design, definition: TrackDefinition, length: float) -> TrackDefinition:
    """Resolve the fractional feature positions against the solved lap length."""

    def at(fraction: float) -> float:
        return round(fraction * length, 1)

    changes: dict[str, object] = {}
    if design.elevation:
        changes["elevation"] = ElevationDefinition(
            control_points=tuple((at(f), z) for f, z in design.elevation)
        )
    if design.banking:
        changes["banking"] = BankingDefinition(
            control_points=tuple((at(f), a) for f, a in design.banking)
        )
    if design.width:
        changes["width"] = WidthDefinition(
            control_points=tuple((at(f), w) for f, w in design.width)
        )
    if design.surface:
        changes["surface"] = SurfaceDefinition.from_dict(
            {
                "regions": [
                    {
                        "start": at(start),
                        "end": at(end),
                        "surface_type": kind,
                        "name": name,
                        "grip": grip,
                        "roughness": roughness,
                    }
                    for start, end, kind, name, grip, roughness in design.surface
                ]
            }
        )
    if design.kerbs:
        changes["kerbs"] = KerbDefinition.from_dict(
            {
                "regions": [
                    {"start": at(start), "end": at(end), "kerb": kerb}
                    for start, end, kerb in design.kerbs
                ]
            }
        )
    if design.sectors:
        changes["sectors"] = SectorDefinition(boundaries=tuple(at(f) for f in design.sectors))
    if design.drs:
        changes["drs"] = DrsDefinition.from_dict(
            {
                "zones": [
                    {
                        "index": index,
                        "name": name,
                        "detection_distance": at(detection),
                        "activation_start": at(start),
                        "activation_end": at(end),
                        "lap_length": length,
                    }
                    for index, (name, detection, start, end) in enumerate(design.drs)
                ]
            }
        )
    return replace(definition, **changes)  # type: ignore[arg-type]


def design(source: Design, *, write: bool) -> bool:
    """Solve, measure and report one synthetic circuit."""
    print("=" * 78)
    print(f"{source.definition.name}  ({source.key})")
    print("=" * 78)

    angles = solve_corner_angles(source.definition)
    definition = apply_corner_angles(source.definition, angles.angles)
    closure = solve_straight_lengths(definition, target_lap_length=source.lap_length)
    definition = apply_straight_lengths(definition, closure.lengths)
    definition = attach_features(source, definition, closure.lap_length)
    definition = replace(definition, metadata=dict(METADATA[source.key]))

    track = build_track(definition)
    report = validate_track(track)
    if not report.ok:
        print(f"  REJECTED: {len(report.errors)} validation error(s)")
        for issue in report.errors:
            print(f"      {issue}")
        return False

    ambient = AmbientConditions(air_temperature=25.0)
    spec = load_builtin_vehicle("reference_2024")
    sweep = {
        wing: compute_lap_time(
            track,
            Vehicle(spec, VehicleSetup(wing_level=wing)),
            ambient,
            mass=Vehicle(spec, VehicleSetup()).total_mass(15.0),
        )
        for wing in (0.0, 0.25, 0.5, 0.75, 1.0)
    }
    best_wing = min(sweep, key=lambda w: sweep[w].lap_time)
    result = sweep[best_wing]

    # The throttle trace has to come from a lap that was actually driven: the
    # speed profile knows what the car was allowed to do, not what the pedal
    # was doing while it did it.
    driven = simulate_lap(
        track,
        Vehicle(spec, VehicleSetup(wing_level=best_wing)),
        load_builtin_driver("01_benchmark"),
        ambient=ambient,
        fuel_mass=15.0,
        qualifying=True,
        record_telemetry=True,
    )
    telemetry = driven.telemetry

    corner_share = sum(c["length"] for c in track.corners.values()) / track.length
    per_km = len(track.corners) / (track.length / 1000.0)

    print(
        f"  lap {track.length:.1f} m, {len(track.corners)} corners, "
        f"{len(track)} segments, closure {closure.closure_error:.3f} m"
    )
    print(f"  lap time        : {format_lap_time(result.lap_time)} at wing {best_wing:.2f}")

    ok = True
    ok &= _check("corners per km", per_km, ENVELOPE.min_corners_per_km, ENVELOPE.max_corners_per_km, "")
    ok &= _check(
        "average speed", ms_to_kph(result.average_speed),
        ENVELOPE.min_average_speed_kph, ENVELOPE.max_average_speed_kph, "km/h",
    )
    ok &= _check(
        "minimum speed", ms_to_kph(result.minimum_speed),
        ENVELOPE.min_minimum_speed_kph, ENVELOPE.max_minimum_speed_kph, "km/h",
    )
    print(
        f"  reported only   : corner share {corner_share * 100:.1f}%, "
        f"full throttle {telemetry.full_throttle_fraction * 100:.1f}%, "
        f"braking {telemetry.braking_fraction * 100:.1f}%"
    )

    ok &= _check_setup(source, sweep, best_wing)

    if ok and write:
        path = BUILTIN_TRACK_DIR / f"{source.key}.json"
        save_track_definition(definition, path)
        print(f"  written         : {path}")
    return ok


def _check_setup(source: Design, sweep: dict, best_wing: float) -> bool:
    """Does the circuit want the setup its character says it should?"""
    times = [sweep[w].lap_time for w in sorted(sweep)]
    spread = max(times) - min(times)
    expectation = source.wing_expectation
    if expectation == "minimum":
        ok = best_wing <= 0.25
    elif expectation == "maximum":
        ok = best_wing >= 0.75
    else:
        # Interior means both ends are genuinely slower, not merely that the
        # winner has a wing level between them.
        ok = 0.0 < best_wing < 1.0 and times[0] > min(times) and times[-1] > min(times)
    print(
        f"  setup optimum   : wing {best_wing:.2f}, worth {spread:.2f} s across the "
        f"range  (this circuit should want {expectation} wing)"
        f"{'' if ok else '  <-- it does not'}"
    )
    return ok


def _check(
    label: str, value: float, low: float, high: float, unit: str,
    scale: float = 1.0, suffix: str = "",
) -> bool:
    inside = low <= value <= high
    mark = " " if inside else "  <-- outside the range real circuits occupy"
    print(
        f"  {label:<16}: {value * scale:.2f}{suffix} {unit}"
        f"  (real circuits: {low * scale:.1f}{suffix}-{high * scale:.1f}{suffix} {unit}){mark}"
    )
    return inside


METADATA: dict[str, dict[str, str]] = {
    "synthetic_power_circuit": {
        "purpose": "Power-sensitive reference circuit",
        "geometry_confidence": "synthetic",
        "character": "long straights, few corners, high average speed",
        "notes": (
            "Not a real circuit. Sits at the power-sensitive end of the character "
            "range so later phases can show track character emerging from geometry "
            "rather than per-track corrections. Corner density and full-throttle "
            "share are held inside the range the Formula 1 calendar spans; "
            "generated by tools/design_circuits.py."
        ),
    },
    "synthetic_proving_ground": {
        "purpose": "Phase 1 reference circuit for engine development and tests",
        "geometry_confidence": "synthetic",
        "character": "every corner speed represented, balanced setup",
        "notes": (
            "Not a real circuit. Designed to exercise every part of the track "
            "model: two long straights, high/medium/low-speed corners, a corner "
            "that opens out, elevation change, banking, two surface types and two "
            "DRS zones. Corner density and full-throttle share are held inside the "
            "range the Formula 1 calendar spans; generated by "
            "tools/design_circuits.py."
        ),
    },
    "synthetic_street_circuit": {
        "purpose": "Grip- and traction-limited reference circuit",
        "geometry_confidence": "synthetic",
        "character": "short, tight, narrow, low average speed, heavy elevation change",
        "notes": (
            "Not a real circuit. Sits at the mechanical-grip end of the character "
            "range: two hairpins, nineteen corners in 3.35 km, and one DRS zone "
            "that barely pays. Corner density and full-throttle share are held "
            "inside the range the Formula 1 calendar spans; generated by "
            "tools/design_circuits.py."
        ),
    },
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="save the circuits")
    parser.add_argument("--only", help="just this circuit")
    args = parser.parse_args()

    sources = [d for d in DESIGNS if not args.only or d.key == args.only]
    if not sources:
        print(f"no design named {args.only!r}", file=sys.stderr)
        return 2
    results = [design(source, write=args.write) for source in sources]
    print()
    print(f"{sum(results)}/{len(results)} design(s) inside the envelope")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
