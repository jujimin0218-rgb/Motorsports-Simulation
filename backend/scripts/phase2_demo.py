"""Phase 2, end to end, through the API.

    python backend/scripts/phase2_demo.py [--distance 0.25]

New game -> start the round -> practice -> qualifying on the race engine ->
the grid it produced -> the grand prix on the race engine -> the championship
updated from the result -> save -> load -> the same game back.

Every lap of it is simulated by ``f1_race_engine``.  Nothing here decides a lap
time, a retirement or an overtake.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app.api.dependencies import get_service
from app.main import create_app
from app.services.game_service import GameService
from app.services.jobs import JobRunner
from app.services.storage import SaveStore


def rule(title: str) -> None:
    print(f"\n{title}\n{'-' * len(title)}", flush=True)


def await_job(client: TestClient, job: dict, label: str) -> dict:
    started = time.perf_counter()
    last = -1.0
    while job["status"] in ("pending", "running"):
        time.sleep(0.5)
        job = client.get(f"/api/jobs/{job['id']}").json()
        if job["progress"] - last >= 0.1:
            last = job["progress"]
            print(f"    {label} {100 * last:3.0f}%  ({time.perf_counter() - started:.0f}s)", flush=True)
    print(f"    {label} {job['status']} in {time.perf_counter() - started:.0f}s", flush=True)
    if job["status"] == "failed":
        print("    " + job.get("error", ""), flush=True)
        print(job.get("detail", ""), flush=True)
        raise SystemExit(1)
    return job["result"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--distance", type=float, default=0.25)
    parser.add_argument("--team", default="harrow")
    args = parser.parse_args()

    service = GameService(store=SaveStore(":memory:"), jobs=JobRunner())
    app = create_app()
    app.dependency_overrides[get_service] = lambda: service
    client = TestClient(app)

    rule("New game")
    snapshot = client.post(
        "/api/game/new", json={"player_team": args.team, "seed": 20260101}
    ).json()
    service.state.settings.race_distance = args.distance
    print(f"  {snapshot['name']}  seed {snapshot['seed']}")
    print(f"  player {snapshot['team']['name']}, car {snapshot['team']['car_overall']}")

    season = client.get("/api/season").json()
    print(f"  season {season['season']}, {season['rounds']} rounds, at {args.distance:.0%} distance")

    rule("Round 1")
    started = client.post("/api/round/start").json()
    circuit = started["circuit"]
    print(f"  {circuit['name']}  {circuit['length_km']} km")
    print(f"  {started['laps']} laps of a {started['full_distance_laps']}-lap grand prix")
    print(f"  running on the engine circuit {circuit['physics_track']}")
    client.post("/api/round/practice")

    rule("Qualifying (the race engine's own knockout session)")
    result = await_job(client, client.post("/api/qualifying/run").json(), "qualifying")
    for row in result["qualifying"][:5]:
        print("    P%-2d %-24s %-24s %s"
              % (row["position"], row["driver"], row["team"],
                 f"{row['best']:.3f}" if row["best"] else "--"))
    print("    ...")

    rule("The grand prix")
    race = await_job(client, client.post("/api/race/run").json(), "race")
    print(f"  race {race['race_id']}, {race['retirements']} retirements, "
          f"{len(race['flags'])} flag periods")
    for row in race["classification"][:6]:
        state = service.state
        print("    P%-2d %-24s %-24s %s"
              % (row["position"], state.driver(row["driver"]).name,
                 state.team(row["team"]).name,
                 "RETIRED" if row["retired"] else f"started P{row['started']}"))
    print("    ...")

    rule("Championship, updated from that result")
    client.post("/api/round/development")
    standings = client.get("/api/standings").json()
    state = service.state
    for row in standings["drivers"][:5]:
        print("    P%-2d %-24s %-24s %3d pts"
              % (row["position"], state.driver(row["driver"]).name,
                 state.team(row["team"]).name if row["team"] else "", row["points"]))
    print("    Constructors:")
    for row in standings["teams"][:3]:
        print("      P%-2d %-24s %3d pts"
              % (row["position"], state.team(row["team"]).name, row["points"]))

    rule("The replay data the engine produced")
    archive = client.get(f"/api/race/{race['race_id']}").json()
    lap_records = archive.get("lap_records", {})
    print(f"  {len(lap_records)} cars with lap-by-lap timing")
    any_car = next(iter(lap_records.values()), [])
    if any_car:
        print(f"  car 1 lap 1: {any_car[0]}")
    print(f"  overtakes recorded: {len(archive.get('overtakes', []))}")
    print(f"  incidents recorded: {len(archive.get('incidents', []))}")

    rule("Save and load")
    saved = client.post("/api/game/save", json={"name": "Phase 2"}).json()
    before = service.state.to_dict()
    client.post("/api/game/load", json={"save_id": saved["id"]})
    print(f"  reloaded and identical: {service.state.to_dict() == before}")
    print(f"  season now waiting on round {client.get('/api/round/next').json()['round']}")

    service.close()
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
