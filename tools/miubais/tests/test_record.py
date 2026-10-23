import shutil
from datetime import UTC, datetime

import pytest
import yaml
from conftest import AllProbe, NoProbe
from miubais.exercises import load_exercise
from miubais.record import RecordingRejected, RequirementError, record_fixtures


@pytest.fixture
def ex(sample_ex, tmp_path):
    shutil.copytree(sample_ex.dir, tmp_path / "x-sample")
    ex = load_exercise(tmp_path / "x-sample")
    (ex.dir / "fixtures").mkdir()
    (ex.dir / "fixtures" / "MANIFEST.yaml").write_text(
        "files:\n  - name: a.json\n    purpose: p\n    recorded: synthetic\n  - name: z.json\n    recorded: synthetic\n"
    )
    return ex


def fake_record(client):
    assert client == "client"
    return {
        "a": {"status": 200, "headers": {}, "body": {"model": "claude-haiku-5-5"}},
        "b": {"status": 200, "headers": {}, "body_text": "event: x\n"},
    }


def test_record_fixtures_requires_api_key(ex):
    with pytest.raises(RequirementError, match="record-fixtures needs: api-key"):
        record_fixtures(ex, probe=NoProbe(), record_fn=fake_record)


def test_record_fixtures_without_reference_refuses_before_recording(ex):
    shutil.rmtree(ex.reference_dir)

    def never(client):
        raise AssertionError("recorded live without a reference")

    with pytest.raises(RequirementError, match="no reference/ solution"):
        record_fixtures(ex, probe=AllProbe(), record_fn=never, client_factory=lambda: "client")


def test_record_fixtures_writes_files_and_manifest(ex):
    paths = record_fixtures(
        ex, probe=AllProbe(), record_fn=fake_record, client_factory=lambda: "client"
    )
    assert [p.name for p in paths] == ["a.json", "b.json"]
    assert '"status": 200' in paths[0].read_text()
    manifest = yaml.safe_load((ex.dir / "fixtures" / "MANIFEST.yaml").read_text())
    assert manifest["recorded"] == "mixed"
    by_name = {f["name"]: f for f in manifest["files"]}
    today = datetime.now(UTC).date().isoformat()
    assert by_name["a.json"] == {
        "name": "a.json",
        "purpose": "p",
        "recorded": "live",
        "recorded_on": today,
        "model": "claude-haiku-5-5",
    }
    assert by_name["b.json"] == {"name": "b.json", "recorded": "live", "recorded_on": today}
    assert by_name["z.json"] == {"name": "z.json", "recorded": "synthetic"}


def test_manifest_is_live_when_every_file_is_rewritten(ex):
    (ex.dir / "fixtures" / "MANIFEST.yaml").write_text("files: []\n")
    record_fixtures(ex, probe=AllProbe(), record_fn=fake_record, client_factory=lambda: "client")
    manifest = yaml.safe_load((ex.dir / "fixtures" / "MANIFEST.yaml").read_text())
    assert manifest["recorded"] == "live"


def test_record_fixtures_loads_record_py_from_the_exercise(ex):
    (ex.dir / "fixtures" / "record.py").write_text(
        "def record(client):\n    return {'c': {'status': 200, 'headers': {}, 'body': {}}}\n"
    )
    paths = record_fixtures(ex, probe=AllProbe(), client_factory=lambda: "client")
    assert [p.name for p in paths] == ["c.json"]


def test_cli_record_fixtures_without_key_exits_1(fixture_course, monkeypatch):
    from miubais.cli import app
    from typer.testing import CliRunner

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    res = CliRunner().invoke(app, ["record-fixtures", "x-sample", "--course", str(fixture_course)])
    assert res.exit_code == 1
    assert "record-fixtures needs: api-key" in res.output


def test_cli_record_fixtures_prints_written_paths(fixture_course, monkeypatch, tmp_path):
    from miubais.cli import app
    from typer.testing import CliRunner

    monkeypatch.setattr("miubais.cli.record_fixtures", lambda ex: [tmp_path / "a.json"])
    res = CliRunner().invoke(app, ["record-fixtures", "x-sample", "--course", str(fixture_course)])
    assert res.exit_code == 0
    assert str(tmp_path / "a.json") in res.output


FIXTURE_STAGE = """  - id: "03-fixture"
    title: fixture model
    tests: tests/test_03_fixture.py
"""
FIXTURE_TEST = """import json
from pathlib import Path


def test_model():
    path = Path(__file__).parents[1] / "fixtures" / "a.json"
    assert json.loads(path.read_text())["body"]["model"] == "claude-haiku-5-5"
"""


@pytest.fixture
def ex_with_fixture_stage(ex):
    original = '{"status": 200, "headers": {}, "body": {"model": "claude-haiku-5-5"}}\n'
    (ex.dir / "fixtures" / "a.json").write_text(original)
    (ex.dir / "tests" / "test_03_fixture.py").write_text(FIXTURE_TEST)
    stages = ex.dir / "stages.yaml"
    stages.write_text(stages.read_text() + FIXTURE_STAGE)
    return load_exercise(ex.dir)


def test_recording_that_breaks_a_stage_keeps_the_originals(ex_with_fixture_stage):
    ex = ex_with_fixture_stage
    before = {p.name: p.read_text() for p in (ex.dir / "fixtures").iterdir()}

    def bad_record(client):
        return {"a": {"status": 200, "headers": {}, "body": {"model": "other"}}}

    with pytest.raises(RecordingRejected, match="03-fixture"):
        record_fixtures(ex, probe=AllProbe(), record_fn=bad_record, client_factory=lambda: "c")
    assert {p.name: p.read_text() for p in (ex.dir / "fixtures").iterdir()} == before


def test_recording_that_passes_every_stage_is_swapped_in(ex_with_fixture_stage):
    ex = ex_with_fixture_stage

    def good_record(client):
        return {
            "a": {"status": 200, "headers": {}, "body": {"model": "claude-haiku-5-5", "id": "n"}}
        }

    record_fixtures(ex, probe=AllProbe(), record_fn=good_record, client_factory=lambda: "c")
    assert '"id": "n"' in (ex.dir / "fixtures" / "a.json").read_text()


def test_course_recorder_renumbers_tool_use_ids():
    import importlib.util

    from miubais.paths import course_dir

    path = course_dir() / "m0-cost-lab" / "fixtures" / "record.py"
    spec = importlib.util.spec_from_file_location("m0_record", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    content = [
        {"type": "thinking", "thinking": "", "signature": "s"},
        {"type": "tool_use", "id": "toolu_live_x", "name": "a", "input": {}},
        {"type": "tool_use", "id": "toolu_live_y", "name": "b", "input": {}},
    ]
    fixture = module.renumber_tool_uses({"status": 200, "body": {"content": content}})
    assert [b.get("id") for b in fixture["body"]["content"]] == [None, "toolu_01", "toolu_02"]
