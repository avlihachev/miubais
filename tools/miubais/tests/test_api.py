import json

import pytest
from conftest import FakeRunner, NoProbe
from fastapi.testclient import TestClient
from miubais.api import create_app
from miubais.model import FakeModelClient, ModelResult
from miubais.progress import load_progress
from miubais.workspace import start_exercise


def _app(tmp_repo, fixture_course, outcomes=None, client=None, freshness=None):
    return create_app(
        course_dir=fixture_course,
        home=tmp_repo / "home",
        workspace=tmp_repo / "workspace",
        client_factory=lambda: client or FakeModelClient([ModelResult("a nudge", None, 0.0, None)]),
        runner=FakeRunner(outcomes or {}),
        probe=NoProbe(),
        freshness_path=freshness or tmp_repo / "freshness" / "latest.json",
    )


@pytest.fixture
def api(tmp_repo, fixture_course):
    return TestClient(_app(tmp_repo, fixture_course))


@pytest.fixture
def api_started(tmp_repo, fixture_course, sample_ex):
    start_exercise(sample_ex, workspace=tmp_repo / "workspace")
    return TestClient(_app(tmp_repo, fixture_course))


def _events(text):
    out = []
    for block in text.strip().split("\n\n"):
        name, data = block.split("\n")
        out.append((name.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return out


def test_exercises_lists_sample(api):
    body = api.get("/exercises").json()
    assert body[0]["id"] == "x-sample"
    assert body[0]["started"] is False
    assert {"id", "title", "live", "requires"} <= body[0]["stages"][0].keys()


def test_exercises_marks_started(api_started):
    assert api_started.get("/exercises").json()[0]["started"] is True


def test_check_streams_stage_events(api_started):
    r = api_started.post("/check/x-sample")
    assert r.headers["content-type"].startswith("text/event-stream")
    assert '"event": "stage"' in r.text and '"event": "done"' in r.text
    events = _events(r.text)
    assert events[-1][0] == "done"
    assert all("output" not in data for _, data in events)


def test_check_reports_failure_in_done(tmp_repo, fixture_course, sample_ex):
    start_exercise(sample_ex, workspace=tmp_repo / "workspace")
    first = sample_ex.stages[0]
    name = first.tests.rsplit("/", 1)[-1]
    client = TestClient(_app(tmp_repo, fixture_course, {name: (1, "boom")}))
    text = client.post("/check/x-sample").text
    events = _events(text)
    assert events[-1][1]["failed"] == first.id
    assert events[0][1]["status"] == "failed"
    assert "boom" not in text


def test_check_single_stage(api_started, sample_ex):
    stage = sample_ex.stages[0].id
    events = _events(api_started.post("/check/x-sample", json={"stage": stage}).text)
    assert [d["stage"] for n, d in events if n == "stage"] == [stage]


def test_check_unknown_stage_is_404(api_started):
    assert api_started.post("/check/x-sample", json={"stage": "nope"}).status_code == 404


def test_check_not_started_returns_409(api):
    r = api.post("/check/x-sample")
    assert r.status_code == 409
    assert r.json() == {"detail": "run `uv run miubais start x-sample` first"}


def test_check_unknown_exercise_is_404(api):
    assert api.post("/check/nope").status_code == 404


def test_progress_reflects_check(api_started):
    api_started.post("/check/x-sample")
    assert "x-sample" in api_started.get("/progress").json()["exercises"]


def test_hint_after_failure(tmp_repo, fixture_course, sample_ex):
    start_exercise(sample_ex, workspace=tmp_repo / "workspace")
    name = sample_ex.stages[0].tests.rsplit("/", 1)[-1]
    client = TestClient(_app(tmp_repo, fixture_course, {name: (1, "boom")}))
    client.post("/check/x-sample")
    body = client.post("/hint/x-sample").json()
    assert set(body) == {"text", "source", "leaks_rejected"}


def test_hint_without_failing_stage_is_422(api_started):
    assert api_started.post("/hint/x-sample").status_code == 422


def test_hint_not_started_and_unknown(api):
    assert api.post("/hint/x-sample").status_code == 409
    assert api.post("/hint/nope").status_code == 404


def test_freshness_empty_then_content(tmp_repo, fixture_course):
    assert TestClient(_app(tmp_repo, fixture_course)).get("/freshness").json() == {}
    path = tmp_repo / "freshness" / "latest.json"
    path.parent.mkdir()
    path.write_text('{"lessons": []}')
    assert TestClient(_app(tmp_repo, fixture_course, freshness=path)).get("/freshness").json() == {
        "lessons": []
    }


def test_cors_allows_only_site_origin(api):
    ok = api.get("/exercises", headers={"Origin": "http://localhost:4321"})
    bad = api.get("/exercises", headers={"Origin": "http://evil.example"})
    assert ok.headers["access-control-allow-origin"] == "http://localhost:4321"
    assert "access-control-allow-origin" not in bad.headers


class RaisingRunner:
    def run(self, cmd, cwd, env, timeout=None):
        raise RuntimeError("runner exploded")


def test_check_runner_exception_yields_error_event(tmp_repo, fixture_course, sample_ex):
    start_exercise(sample_ex, workspace=tmp_repo / "workspace")
    client = TestClient(
        create_app(
            course_dir=fixture_course,
            home=tmp_repo / "home",
            workspace=tmp_repo / "workspace",
            runner=RaisingRunner(),
            probe=NoProbe(),
        )
    )
    r = client.post("/check/x-sample")
    assert r.status_code == 200
    assert _events(r.text) == [("error", {"event": "error", "message": "runner exploded"})]


def test_check_records_progress_under_api_home(tmp_repo, fixture_course, sample_ex):
    start_exercise(sample_ex, workspace=tmp_repo / "workspace")
    other = tmp_repo / "other-home"
    client = TestClient(
        create_app(
            course_dir=fixture_course,
            home=other,
            workspace=tmp_repo / "workspace",
            runner=FakeRunner({}),
            probe=NoProbe(),
        )
    )
    client.post("/check/x-sample")
    assert "x-sample" in load_progress(other).exercises
    assert "x-sample" not in load_progress(tmp_repo / "home").exercises
