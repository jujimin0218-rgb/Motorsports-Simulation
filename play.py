#!/usr/bin/env python3
"""Start the game.

    python play.py

That is the whole thing: it checks what it needs, builds the frontend if it has
not been built, starts the server and opens a browser at it.  One process, one
port, no separate frontend to run.

    python play.py --rounds 1        a one-race season (the default)
    python play.py --rounds 22       the full season
    python play.py --port 9000       somewhere else
    python play.py --no-browser      just serve it

The season length is a *starting* preference, not a setting the server holds:
it is written to the page the browser opens, and the game is created by the
browser through the ordinary API.  Nothing here reaches around the game to set
something up specially, because a beta that is played through a special path is
not a beta of the thing.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FRONTEND = ROOT / "frontend"
DIST = FRONTEND / "dist"


def _fail(message: str, *fixes: str) -> None:
    print(f"\n  {message}\n", file=sys.stderr)
    for fix in fixes:
        print(f"    {fix}", file=sys.stderr)
    print(file=sys.stderr)
    raise SystemExit(1)


def check_python() -> None:
    if sys.version_info < (3, 11):
        _fail(
            f"This needs Python 3.11 or newer; you have {sys.version.split()[0]}.",
            "The engine uses 3.11 syntax, so an older one will not import.",
        )
    missing = [
        name
        for name in ("fastapi", "uvicorn", "pydantic")
        if not _importable(name)
    ]
    if missing:
        _fail(
            f"Missing Python packages: {', '.join(missing)}.",
            "pip install -e .",
        )


def _importable(name: str) -> bool:
    from importlib.util import find_spec

    try:
        return find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def build_frontend(force: bool = False) -> None:
    """Build the page, unless it is already built and still current.

    Rebuilding takes about a second, but it needs Node, and somebody who was
    given a built copy should not need Node at all -- so a present, newer-than-
    the-source build is left alone and nothing is checked for.
    """
    index = DIST / "index.html"
    if index.is_file() and not force:
        newest_source = max(
            (p.stat().st_mtime for p in (FRONTEND / "src").rglob("*") if p.is_file()),
            default=0.0,
        )
        if index.stat().st_mtime >= newest_source:
            return
        print("  the page is older than its source, rebuilding")

    npm = shutil.which("npm")
    if npm is None:
        if index.is_file():
            print("  no npm; using the build that is already there")
            return
        _fail(
            "The page has not been built and npm is not installed.",
            "Install Node 18+ (https://nodejs.org), then run this again.",
        )
    if not (FRONTEND / "node_modules").is_dir():
        print("  installing frontend packages (once, about a minute)")
        subprocess.run([npm, "ci"], cwd=FRONTEND, check=True)
    print("  building the page")
    subprocess.run([npm, "run", "build"], cwd=FRONTEND, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Start the game.")
    parser.add_argument("--rounds", type=int, default=1, help="races in the season")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--rebuild", action="store_true", help="force a page rebuild")
    args = parser.parse_args()

    if args.rounds < 1:
        _fail(f"A season needs at least one round, not {args.rounds}.")

    print("\n  F1 Season Management -- beta\n")
    check_python()
    build_frontend(force=args.rebuild)

    sys.path.insert(0, str(ROOT / "backend"))
    import uvicorn

    from app.main import app

    url = f"http://{args.host}:{args.port}/?rounds={args.rounds}"
    print(f"\n  ready at {url}")
    print(f"  {args.rounds} race(s) this season -- Ctrl-C to stop\n")

    if not args.no_browser:
        # After the server is actually listening, not before: a browser that
        # wins the race shows a connection error and the tester thinks it is
        # broken.
        threading.Thread(
            target=lambda: (time.sleep(1.5), webbrowser.open(url)), daemon=True
        ).start()

    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
