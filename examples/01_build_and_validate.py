"""Build every shipped circuit, validate it, and print its benchmark report.

    python examples/01_build_and_validate.py [--json out/]

This is the Phase 1 benchmark run (project rule 41).  There is no vehicle yet,
so what is measured is the circuit itself: how long it is, what mix of corners
it has, how well the geometry closes, and how finely it had to be sampled.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from f1_race_engine.core.config import default_config
from f1_race_engine.track.builder import build_track
from f1_race_engine.track.io import builtin_track_names, load_builtin_definition
from f1_race_engine.track.report import format_track_report, track_report
from f1_race_engine.track.validation import Severity, validate_track


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, help="directory to write JSON reports into")
    parser.add_argument("--track", help="build only this circuit")
    args = parser.parse_args()

    config = default_config()
    names = [args.track] if args.track else builtin_track_names()
    failed = False

    for name in names:
        definition = load_builtin_definition(name)
        track = build_track(definition, config)
        report = validate_track(track, config.track_validation)

        print(format_track_report(track_report(track)))
        print()
        print(report.format(min_severity=Severity.INFO))
        print()

        if not report.ok:
            failed = True
            print(f"!! {name} FAILED validation", file=sys.stderr)

        if args.json:
            args.json.mkdir(parents=True, exist_ok=True)
            payload = {
                "track": track.to_dict(),
                "report": track_report(track),
                "validation": report.to_dict(),
            }
            path = args.json / f"{name}.json"
            path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            print(f"wrote {path}")
            print()

    print("=" * 72)
    print("FAILED" if failed else f"OK -- {len(names)} circuit(s) built and validated")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
