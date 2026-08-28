"""Generate the real benchmark circuits from published layout data.

    python tools/author_circuits.py [--write] [--only NAME]

Project rule 10 asks for real circuits as benchmarks, and rule 2.3 says their
character has to *emerge* -- Monza must reward power because it has long
straights, not because a table says so.  So a circuit is authored the way a
track map describes one: corner radii, turn angles, and the straights between
them.  Everything else the engine needs is derived.

Two design-time solvers do the reconciling, and both of them are also honesty
checks:

``solve_corner_angles``
    A closed lap turns through exactly 360 degrees.  Angles read off a map
    never sum to it, and how far they have to move to get there says how good
    the reading was.  This tool refuses to write a circuit whose angles need
    more than :data:`MAX_ANGLE_ADJUSTMENT` -- at that point the layout is a
    guess wearing a real circuit's name.

``solve_straight_lengths``
    With the headings settled, the straights are the only free variables left,
    and they are pinned by the published lap length.

The result is then checked against the published pole lap.  Geometry that
produces the right lap time is geometry that is doing real work; geometry that
does not is a drawing, and the tool says so and refuses to write it.  The check
that matters most is not the lap time itself but **where the setup search
lands**: Monza has to want minimum wing.  If it does not, the layout has the
wrong balance of straight to corner however well its total length matches, and
calling it Monza would put a made-up circuit into the engine's calibration set
under a real circuit's name.

Status: all three layouts here are **drafts and none of them ship**.  Their
corner radii are close to published figures, but the turn angles are read from
memory of the track maps rather than from survey data, and the checks below
catch that -- Silverstone and Spa need their angles moved by 44% and 80% to
close a lap, and Monza closes but comes out 9% slow with its setup optimum at
the wrong end of the wing range.  What is finished here is the pipeline and the
acceptance criteria.  Real geometry -- a survey trace, or corner radii and
straight lengths recovered from telemetry (project rule 43) -- is what these
drafts are missing, and with it they become data files rather than guesses.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass, replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from f1_race_engine.core.units import format_lap_time, ms_to_kph
from f1_race_engine.environment import AmbientConditions
from f1_race_engine.physics import compute_lap_time
from f1_race_engine.track.builder import build_track
from f1_race_engine.track.definitions import (
    BankingDefinition,
    CornerDefinition,
    CornerDirection,
    DrsDefinition,
    ElevationDefinition,
    SectorDefinition,
    StraightDefinition,
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

#: A layout whose angles need more correction than this is not a reading of a
#: real circuit, it is an invention, and this tool will not write it out.
MAX_ANGLE_ADJUSTMENT = 0.15

#: How far the computed lap may sit from the published pole lap.  Wider than a
#: calibration target, because the reference car is not the pole car and the
#: setup is not the pole setup -- but a layout outside it has the wrong balance
#: of straight to corner, whatever its total length says.
MAX_LAP_TIME_ERROR = 0.03


def corner(
    number: int,
    name: str,
    direction: CornerDirection,
    radius: float,
    angle: float,
    radius_end: float | None = None,
) -> CornerDefinition:
    """One corner, as a track map describes it."""
    return CornerDefinition(
        radius=radius,
        angle=angle,
        direction=direction,
        radius_end=radius_end,
        name=name,
        corner_id=number,
    )


def straight(length: float, name: str) -> StraightDefinition:
    """One straight, length being a first guess the solver will refine."""
    return StraightDefinition(length=length, name=name)


@dataclass(frozen=True)
class CircuitSource:
    """A circuit's published data and what the engine should reproduce."""

    key: str
    definition: TrackDefinition
    lap_length: float
    """Published lap length, m -- what the straights are solved against."""

    reference_lap: float | None = None
    """Published pole lap, s.  A benchmark, never a target to fit."""

    reference_top_speed: float | None = None
    """Published speed-trap figure, km/h."""

    reference_minimum_speed: float | None = None
    """Published slowest-corner speed, km/h."""

    wing_level: float = 0.5
    """Where the setup search is expected to land for this circuit."""


# ---------------------------------------------------------------------------
# Monza
# ---------------------------------------------------------------------------

MONZA = CircuitSource(
    key="monza",
    lap_length=5793.0,
    reference_lap=79.327,
    reference_top_speed=354.0,
    reference_minimum_speed=85.0,
    wing_level=0.05,
    definition=TrackDefinition(
        name="Autodromo Nazionale Monza",
        country="Italy",
        defaults=TrackDefaults(
            track_width=13.5, surface_type="asphalt", surface_grip=1.0, roughness=0.45
        ),
        layout=(
            straight(800.0, "Rettifilo Tribune"),
            corner(1, "Variante del Rettifilo (entry)", R, 38.0, 55.0),
            straight(28.0, "Rettifilo link"),
            corner(2, "Variante del Rettifilo (exit)", L, 42.0, 40.0),
            straight(190.0, "Curva Biassono approach"),
            corner(3, "Curva Grande", R, 340.0, 85.0),
            straight(640.0, "Roggia approach"),
            corner(4, "Variante della Roggia (entry)", L, 46.0, 55.0),
            straight(26.0, "Roggia link"),
            corner(5, "Variante della Roggia (exit)", R, 44.0, 50.0),
            straight(420.0, "Lesmo approach"),
            corner(6, "Curva di Lesmo 1", R, 92.0, 80.0),
            straight(115.0, "Lesmo link"),
            corner(7, "Curva di Lesmo 2", R, 78.0, 75.0),
            straight(800.0, "Curva del Serraglio"),
            corner(8, "Variante Ascari (1)", L, 105.0, 55.0),
            straight(30.0, "Ascari link 1"),
            corner(9, "Variante Ascari (2)", R, 72.0, 70.0),
            straight(30.0, "Ascari link 2"),
            corner(10, "Variante Ascari (3)", L, 125.0, 45.0),
            straight(620.0, "Rettifilo Centro"),
            corner(11, "Curva Parabolica (Alboreto)", R, 105.0, 180.0, radius_end=260.0),
            straight(130.0, "Parabolica exit"),
        ),
        elevation=ElevationDefinition(
            control_points=(
                (0.0, 0.0), (900.0, 2.0), (2200.0, 6.0), (3400.0, 8.0),
                (4300.0, 4.0), (5200.0, 1.0), (5793.0, 0.0),
            )
        ),
        width=WidthDefinition(
            control_points=((0.0, 15.0), (700.0, 13.0), (4600.0, 13.0), (5793.0, 15.0))
        ),
        metadata={
            "geometry_confidence": "approximate",
            "character": "very long straights, four heavy braking zones, minimum wing",
            "calibration": "published lap length, corner radii and turn counts",
            "notes": (
                "The temple of speed. Three quarters of the lap is full throttle, so "
                "engine power and low drag decide it -- which the engine works out "
                "from the geometry, not from a per-track correction."
            ),
        },
    ),
)


# ---------------------------------------------------------------------------
# Silverstone
# ---------------------------------------------------------------------------

SILVERSTONE = CircuitSource(
    key="silverstone",
    lap_length=5891.0,
    reference_lap=85.819,
    reference_top_speed=330.0,
    reference_minimum_speed=110.0,
    wing_level=0.55,
    definition=TrackDefinition(
        name="Silverstone Circuit",
        country="United Kingdom",
        defaults=TrackDefaults(
            track_width=14.0, surface_type="asphalt", surface_grip=1.0, roughness=0.5
        ),
        layout=(
            straight(430.0, "Hamilton Straight"),
            corner(1, "Abbey", R, 210.0, 60.0),
            straight(120.0, "Farm link"),
            corner(2, "Farm Curve", R, 320.0, 40.0),
            straight(260.0, "Village approach"),
            corner(3, "Village", R, 32.0, 110.0),
            straight(45.0, "Village link"),
            corner(4, "The Loop", L, 24.0, 150.0),
            straight(120.0, "Aintree approach"),
            corner(5, "Aintree", L, 95.0, 45.0),
            straight(740.0, "Wellington Straight"),
            corner(6, "Brooklands", L, 60.0, 95.0),
            straight(90.0, "Brooklands link"),
            corner(7, "Luffield", R, 55.0, 150.0, radius_end=90.0),
            straight(60.0, "Woodcote approach"),
            corner(8, "Woodcote", R, 240.0, 35.0),
            straight(560.0, "National Straight"),
            corner(9, "Copse", R, 195.0, 70.0),
            straight(180.0, "Maggotts approach"),
            corner(10, "Maggotts", L, 190.0, 55.0),
            straight(60.0, "Becketts link 1"),
            corner(11, "Becketts", R, 110.0, 75.0),
            straight(50.0, "Becketts link 2"),
            corner(12, "Chapel", L, 130.0, 70.0),
            straight(770.0, "Hangar Straight"),
            corner(13, "Stowe", R, 105.0, 95.0),
            straight(360.0, "Vale"),
            corner(14, "Vale", L, 40.0, 90.0),
            straight(40.0, "Club approach"),
            corner(15, "Club", R, 75.0, 120.0, radius_end=140.0),
            straight(200.0, "Club exit"),
        ),
        elevation=ElevationDefinition(
            control_points=(
                (0.0, 0.0), (900.0, -4.0), (1800.0, -6.0), (2900.0, 2.0),
                (3900.0, 6.0), (4900.0, 3.0), (5891.0, 0.0),
            )
        ),
        width=WidthDefinition(
            control_points=((0.0, 15.0), (600.0, 14.0), (5200.0, 14.0), (5891.0, 15.0))
        ),
        metadata={
            "geometry_confidence": "approximate",
            "character": "high-speed direction changes, aerodynamically demanding",
            "calibration": "published lap length, corner radii and turn counts",
            "notes": (
                "Maggotts-Becketts-Chapel is three fast corners taken as one, so the "
                "car is never straight and never unloaded. It rewards downforce the "
                "way Monza punishes it."
            ),
        },
    ),
)


# ---------------------------------------------------------------------------
# Spa-Francorchamps
# ---------------------------------------------------------------------------

SPA = CircuitSource(
    key="spa",
    lap_length=7004.0,
    reference_lap=113.159,
    reference_top_speed=340.0,
    reference_minimum_speed=75.0,
    wing_level=0.3,
    definition=TrackDefinition(
        name="Circuit de Spa-Francorchamps",
        country="Belgium",
        defaults=TrackDefaults(
            track_width=13.0, surface_type="asphalt", surface_grip=1.0, roughness=0.55
        ),
        layout=(
            straight(280.0, "Start straight"),
            corner(1, "La Source", R, 20.0, 180.0),
            straight(300.0, "Eau Rouge approach"),
            corner(2, "Eau Rouge", L, 105.0, 55.0),
            straight(40.0, "Raidillon link"),
            corner(3, "Raidillon", R, 130.0, 70.0),
            straight(1350.0, "Kemmel Straight"),
            corner(5, "Les Combes (entry)", R, 60.0, 75.0),
            straight(45.0, "Combes link"),
            corner(6, "Malmedy", L, 65.0, 70.0),
            straight(150.0, "Rivage approach"),
            corner(7, "Bruxelles", R, 38.0, 150.0),
            straight(220.0, "Bruxelles exit"),
            corner(8, "Speaker's Corner", L, 190.0, 40.0),
            straight(330.0, "Pouhon approach"),
            corner(9, "Pouhon", L, 150.0, 105.0, radius_end=210.0),
            straight(330.0, "Fagnes approach"),
            corner(10, "Fagnes (entry)", R, 85.0, 70.0),
            straight(40.0, "Fagnes link"),
            corner(11, "Fagnes (exit)", L, 90.0, 60.0),
            straight(230.0, "Campus approach"),
            corner(12, "Campus", R, 55.0, 105.0),
            straight(60.0, "Campus link"),
            corner(13, "Campus exit", L, 70.0, 60.0),
            straight(400.0, "Blanchimont approach"),
            corner(14, "Blanchimont", L, 340.0, 65.0),
            straight(420.0, "Bus Stop approach"),
            corner(15, "Bus Stop (entry)", R, 30.0, 80.0),
            straight(35.0, "Bus Stop link"),
            corner(16, "Bus Stop (exit)", L, 32.0, 75.0),
            straight(230.0, "Pit straight"),
        ),
        elevation=ElevationDefinition(
            control_points=(
                (0.0, 0.0), (300.0, -12.0), (700.0, 20.0), (1000.0, 38.0),
                (2100.0, 60.0), (3200.0, 40.0), (4200.0, 18.0), (5200.0, 6.0),
                (6300.0, 2.0), (7004.0, 0.0),
            )
        ),
        width=WidthDefinition(
            control_points=((0.0, 14.0), (500.0, 13.0), (6400.0, 13.0), (7004.0, 14.0))
        ),
        metadata={
            "geometry_confidence": "approximate",
            "character": "long straights and fast corners with 100 m of elevation",
            "calibration": "published lap length, corner radii and turn counts",
            "notes": (
                "The compromise circuit: a wing that is quick through Pouhon and "
                "Blanchimont is slow up the Kemmel, and the engine has to find the "
                "balance without being told there is one."
            ),
        },
    ),
)


CIRCUITS: tuple[CircuitSource, ...] = (MONZA, SILVERSTONE, SPA)


# ---------------------------------------------------------------------------
# Where the timing lines and the DRS zones go
# ---------------------------------------------------------------------------

#: ``key -> (sector boundaries, DRS zones)``, expressed against corner numbers
#: so they follow the geometry when the solvers move it.
#:
#: A sector boundary is ``("after", turn)`` or ``("before", turn)`` with an
#: offset in metres.  A DRS zone is
#: ``(name, detection anchor, activation start anchor, activation end anchor)``.
FEATURES: dict[str, dict[str, object]] = {
    "monza": {
        "sectors": [("after", 5, 60.0), ("after", 10, 40.0)],
        "drs": [
            ("Rettifilo", ("before", 11, 250.0), ("after", 11, 40.0), ("before", 1, 120.0)),
            ("Curva Grande", ("after", 3, 30.0), ("after", 3, 120.0), ("before", 4, 120.0)),
        ],
    },
    "silverstone": {
        "sectors": [("after", 5, 40.0), ("after", 12, 60.0)],
        "drs": [
            ("Wellington", ("before", 5, 120.0), ("after", 5, 90.0), ("before", 6, 110.0)),
            ("Hangar", ("before", 12, 100.0), ("after", 12, 110.0), ("before", 13, 130.0)),
        ],
    },
    "spa": {
        "sectors": [("after", 5, 30.0), ("after", 13, 60.0)],
        "drs": [
            ("Kemmel", ("after", 3, 20.0), ("after", 3, 180.0), ("before", 5, 180.0)),
            ("Pit straight", ("before", 15, 200.0), ("after", 16, 60.0), ("before", 1, 100.0)),
        ],
    },
}


def _anchor(corners: dict[int, dict], spec: tuple, length: float) -> float:
    """Resolve an ``("after"|"before", turn, offset)`` anchor to a distance."""
    where, turn, offset = spec
    corner_data = corners[turn]
    if where == "after":
        base = corner_data["start_distance"] + corner_data["length"]
        return (base + offset) % length
    if where == "before":
        return (corner_data["start_distance"] - offset) % length
    raise ValueError(f"unknown anchor {where!r}")


def place_features(source: CircuitSource, definition: TrackDefinition) -> TrackDefinition:
    """Attach sector lines and DRS zones, positioned relative to the corners."""
    track = build_track(definition)
    corners = track.corners
    length = track.length
    spec = FEATURES[source.key]

    boundaries = tuple(
        sorted(_anchor(corners, item, length) for item in spec["sectors"])  # type: ignore[arg-type]
    )
    zones = []
    for index, (name, detection, start, end) in enumerate(spec["drs"]):  # type: ignore[misc]
        activation_start = _anchor(corners, start, length)
        activation_end = _anchor(corners, end, length)
        zones.append(
            {
                "index": index,
                "name": name,
                "detection_distance": _anchor(corners, detection, length),
                "activation_start": activation_start,
                "activation_end": activation_end,
                "lap_length": length,
            }
        )
    return replace(
        definition,
        sectors=SectorDefinition(boundaries=boundaries),
        drs=DrsDefinition.from_dict({"zones": zones}),
    )


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def author(source: CircuitSource, *, write: bool) -> bool:
    """Solve, validate and report one circuit.  Returns whether it is usable."""
    print("=" * 78)
    print(f"{source.definition.name}  ({source.key})")
    print("=" * 78)

    angles = solve_corner_angles(source.definition)
    worst = angles.worst_adjustment_fraction
    print(
        f"  heading closure : authored angles were {angles.residual_deg:+.1f} deg "
        f"short of {360 * angles.turns:+.0f}; every angle moved {worst * 100:.1f}%"
    )
    if worst > MAX_ANGLE_ADJUSTMENT:
        print(
            f"  REJECTED: {worst * 100:.1f}% is more than the "
            f"{MAX_ANGLE_ADJUSTMENT * 100:.0f}% a reading of a real circuit should "
            f"need.  These angles are a guess; do not ship them under this name."
        )
        return False

    definition = apply_corner_angles(source.definition, angles.angles)
    closure = solve_straight_lengths(definition, target_lap_length=source.lap_length)
    print(
        f"  plan-view close : {closure.initial_closure_error:8.1f} m -> "
        f"{closure.closure_error:.3f} m in {closure.iterations} pass(es); "
        f"lap {closure.lap_length:.1f} m vs published {source.lap_length:.0f} m"
    )
    definition = apply_straight_lengths(definition, closure.lengths)
    definition = place_features(source, definition)

    track = build_track(definition)
    report = validate_track(track)
    print(
        f"  validation      : {len(report.errors)} error(s), "
        f"{len(report.warnings)} warning(s)"
    )
    for issue in list(report.errors) + list(report.warnings):
        print(f"      {issue}")
    if not report.ok:
        print("  REJECTED: the built circuit does not validate.")
        return False

    ambient = AmbientConditions(air_temperature=25.0)
    spec = load_builtin_vehicle("reference_2024")
    sweep = {
        wing: compute_lap_time(track, Vehicle(spec, VehicleSetup(wing_level=wing)), ambient)
        for wing in (0.0, 0.25, 0.5, 0.75, 1.0)
    }
    best_wing = min(sweep, key=lambda w: sweep[w].lap_time)
    result = sweep[best_wing]

    print(f"  corners {len(track.corners)}, segments {len(track)}, "
          f"sectors at {[round(b) for b in track.sector_boundaries]}")
    print(
        f"  setup optimum   : wing {best_wing:.2f} "
        f"(expected around {source.wing_level:.2f})"
    )
    _compare("lap time", result.lap_time, source.reference_lap, "s", format_lap_time)
    _compare("top speed", ms_to_kph(result.top_speed), source.reference_top_speed, "km/h")
    _compare(
        "minimum speed", ms_to_kph(result.minimum_speed),
        source.reference_minimum_speed, "km/h",
    )

    if source.reference_lap is not None:
        error = abs(result.lap_time - source.reference_lap) / source.reference_lap
        if error > MAX_LAP_TIME_ERROR:
            print(
                f"  REJECTED: the lap is {error * 100:.1f}% from the published pole, "
                f"more than the {MAX_LAP_TIME_ERROR * 100:.0f}% a real layout should "
                f"need.  The corner-to-straight balance is wrong."
            )
            return False
    if abs(best_wing - source.wing_level) > 0.3:
        print(
            f"  REJECTED: the setup search wants wing {best_wing:.2f} where this "
            f"circuit should want {source.wing_level:.2f}.  Whatever this layout is, "
            f"it does not have the circuit's character."
        )
        return False

    if write:
        path = BUILTIN_TRACK_DIR / f"{source.key}.json"
        save_track_definition(definition, path)
        print(f"  written         : {path}")
    return True


def _compare(label: str, value: float, reference: float | None, unit: str, fmt=None) -> None:
    shown = fmt(value) if fmt else f"{value:.1f}"
    if reference is None:
        print(f"  {label:<16}: {shown} {unit}")
        return
    reference_shown = fmt(reference) if fmt else f"{reference:.1f}"
    error = (value - reference) / reference * 100.0
    print(
        f"  {label:<16}: {shown} {unit}  vs published {reference_shown} {unit}  "
        f"({error:+.1f}%)"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="save the circuits")
    parser.add_argument("--only", help="just this circuit")
    args = parser.parse_args()

    sources = [c for c in CIRCUITS if not args.only or c.key == args.only]
    if not sources:
        print(f"no circuit named {args.only!r}", file=sys.stderr)
        return 2
    usable = [author(source, write=args.write) for source in sources]
    print()
    print(f"{sum(usable)}/{len(usable)} circuit(s) usable")
    return 0 if all(usable) else 1


if __name__ == "__main__":
    raise SystemExit(main())
