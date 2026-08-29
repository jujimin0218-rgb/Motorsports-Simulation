"""The HTTP surface, and the rule it exists to enforce.

The important one: **the backend refuses out-of-phase actions.**  A client that
posts to the race endpoint without having qualified gets a 409 with a code it
can branch on, not a race.  Hiding the button is a courtesy to the player; this
is the rule.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_service
from app.main import create_app
from app.services.game_service import GameService
from app.services.jobs import JobRunner
from app.services.storage import SaveStore


@pytest.fixture
def service() -> GameService:
    made = GameService(store=SaveStore(":memory:"), jobs=JobRunner(max_workers=1))
    yield made
    made.close()


@pytest.fixture
def client(service: GameService) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_service] = lambda: service
    return TestClient(app)


@pytest.fixture
def started(client: TestClient) -> TestClient:
    client.post("/api/game/new", json={"player_team": "harrow", "seed": 20260101})
    return client


# -- before there is a game --------------------------------------------------


def test_health_needs_no_game(client: TestClient):
    assert client.get("/health").json() == {"status": "ok"}


def test_the_team_list_is_available_before_a_game_exists(client: TestClient):
    """It has to be: choosing a team is how a game starts."""
    rows = client.get("/api/game/teams").json()
    assert len(rows) == 10
    assert all("car_rating" in row and "budget" in row for row in rows)


def test_asking_about_a_game_that_is_not_loaded_says_so(client: TestClient):
    response = client.get("/api/game")
    assert response.status_code == 404
    assert response.json()["code"] == "SaveNotFound"


def test_starting_as_a_team_that_does_not_exist_is_refused(client: TestClient):
    response = client.post("/api/game/new", json={"player_team": "ferrari"})
    assert response.status_code == 404
    assert response.json()["code"] == "UnknownEntity"


# -- a game --------------------------------------------------------------


def test_a_new_game_comes_back_whole(started: TestClient):
    payload = started.get("/api/game").json()
    assert payload["season"] == 2026
    assert payload["team"]["name"] == "Harrow Motorsport"
    assert len(payload["drivers"]) == 2
    assert payload["current_round"]["number"] == 1
    assert payload["current_round"]["circuit"]["name"]
    assert payload["standings"]["drivers"]


def test_the_season_the_calendar_and_the_field(started: TestClient):
    assert started.get("/api/season").json()["rounds"] == 22
    assert len(started.get("/api/calendar").json()) == 22
    assert len(started.get("/api/teams").json()) == 10
    assert len(started.get("/api/drivers").json()) == 30
    assert len(started.get("/api/drivers?free_agents=true").json()) == 10


def test_the_calendar_reports_the_laps_this_game_will_actually_run(
    started: TestClient, service: GameService
):
    """The calendar holds the full grand prix distance; a game run at half
    distance has to say what it is going to do, not what the sport does."""
    service.state.settings.race_distance = 0.5
    rows = started.get("/api/calendar").json()
    for row in rows:
        assert row["race_laps"] <= row["circuit"]["race_laps"]
    assert any(row["race_laps"] < row["circuit"]["race_laps"] for row in rows)


# -- the phase machine, enforced here rather than in the UI -------------------


@pytest.mark.parametrize(
    "path",
    ["/api/qualifying/run", "/api/race/run", "/api/round/practice", "/api/round/development"],
)
def test_every_step_of_a_weekend_refuses_to_be_taken_out_of_order(
    started: TestClient, path: str
):
    response = started.post(path)
    assert response.status_code == 409
    assert response.json()["code"] == "InvalidGamePhase"
    assert "round 1" in response.json()["message"]


def test_the_weekend_advances_one_step_at_a_time(started: TestClient):
    assert started.post("/api/round/start").json()["phase"] == "practice"
    assert started.post("/api/round/practice").json()["phase"] == "qualifying"
    # And it will not be started twice.
    assert started.post("/api/round/start").status_code == 409


# -- saving ------------------------------------------------------------------


def test_save_list_load_delete(started: TestClient):
    started.post("/api/round/start")
    saved = started.post("/api/game/save", json={"name": "A Save"}).json()
    assert saved["name"] == "A Save"
    assert saved["season"] == 2026

    listed = started.get("/api/game/saves").json()
    assert saved["id"] in {row["id"] for row in listed}

    loaded = started.post("/api/game/load", json={"save_id": saved["id"]}).json()
    assert loaded["current_round"]["phase"] == "practice"

    assert started.delete(f"/api/game/saves/{saved['id']}").status_code == 200
    assert started.post(
        "/api/game/load", json={"save_id": saved["id"]}
    ).status_code == 404


def test_the_game_autosaves_after_every_step(started: TestClient):
    """Losing a race that took ten minutes to a closed tab is not an
    experience worth shipping."""
    started.post("/api/round/start")
    slots = {row["slot"] for row in started.get("/api/game/saves").json()}
    assert "autosave" in slots
    reloaded = started.post("/api/game/load", json={"slot": "autosave"}).json()
    assert reloaded["current_round"]["phase"] == "practice"


def test_loading_nothing_in_particular_is_refused(started: TestClient):
    assert started.post("/api/game/load", json={}).status_code == 404


# -- jobs --------------------------------------------------------------------


def test_an_unknown_job_is_a_404(started: TestClient):
    assert started.get("/api/jobs/nope").status_code == 404


def test_a_missing_race_archive_is_a_404(started: TestClient):
    assert started.get("/api/race/2026-01").status_code == 404


def test_the_long_sessions_hand_back_a_job_rather_than_a_result(
    started: TestClient, monkeypatch: pytest.MonkeyPatch
):
    """A grand prix is minutes of simulation.  Holding a request open for it
    would be a lie about what is happening.

    The session itself is stubbed here on purpose: this is a test of the job
    plumbing, and running the real engine would be re-testing the engine at a
    cost of several minutes.  ``test_race_integration`` runs the real thing.
    """
    from app.game.calendar import RoundPhase
    from app.services import round_service

    def fake_qualifying(state, **_kwargs):
        entry = state.current_round
        entry.grid = list(state.drivers)[:20]
        entry.advance(RoundPhase.QUALIFYING)
        return round_service.RoundReport(
            entry.number, entry.phase, {"pole": entry.grid[0], "grid": entry.grid}
        )

    monkeypatch.setattr(round_service, "run_qualifying", fake_qualifying)

    started.post("/api/round/start")
    started.post("/api/round/practice")
    job = started.post("/api/qualifying/run").json()
    assert job["kind"] == "qualifying"
    assert job["status"] in ("pending", "running", "done")

    finished = started.get(f"/api/jobs/{job['id']}").json()
    assert finished["id"] == job["id"]
    assert started.get("/api/jobs").json()[0]["id"] == job["id"]

    # And when it lands, the result is the report -- and the round moved.
    import time

    for _ in range(200):
        state = started.get(f"/api/jobs/{job['id']}").json()
        if state["status"] in ("done", "failed"):
            break
        time.sleep(0.02)
    assert state["status"] == "done", state
    assert state["result"]["phase"] == "strategy"
    assert started.get("/api/season").json()["phase"] == "strategy"
