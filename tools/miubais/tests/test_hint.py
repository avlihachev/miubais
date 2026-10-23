import asyncio
import json
import shutil

import pytest
from miubais.cli import app
from miubais.exercises import load_exercise
from miubais.model import FakeModelClient, ModelError, ModelResult
from miubais.paths import miubais_home
from miubais.progress import load_progress, record, save_progress
from miubais.tutor.hint import (
    HintContext,
    HintError,
    build_context,
    generate_hint,
    leak_terms_for,
)
from typer.testing import CliRunner


def reply(text):
    return ModelResult(text=text, structured=None, cost_usd=0, session_id=None)


@pytest.fixture
def ctx(sample_ex, tmp_repo):
    return HintContext(
        exercise=sample_ex,
        stage=sample_ex.stages[0],
        diff="--- a\n+++ b\n+    pass\n",
        failing_output="assert add(1, 2) == 3",
        leak_terms={"compute_total_secret"},
        workspace=tmp_repo / "workspace" / sample_ex.id,
        home=miubais_home(),
    )


def test_hint_rejects_leak_then_falls_back(ctx):
    client = FakeModelClient([reply("use compute_total_secret()")] * 2)
    h = asyncio.run(generate_hint(ctx, client))
    assert h.source == "fallback" and h.leaks_rejected == 2
    assert "compute_total_secret" not in h.text
    assert "leak" in client.requests[1].prompt.lower()
    assert "## Retry" not in client.requests[0].prompt


def test_hint_accepts_clean_answer(ctx):
    client = FakeModelClient([reply("The test calls add with two ints and expects their sum.")])
    h = asyncio.run(generate_hint(ctx, client))
    assert h.source == "model" and h.leaks_rejected == 0
    req = client.requests[0]
    assert req.allowed_tools == ["Read", "Grep", "Glob"] and req.max_turns == 3
    sections = ["## Stage", "## Failing test output", "## Learner diff", "## Your task"]
    positions = [req.prompt.index(s) for s in sections]
    assert positions == sorted(positions)


def test_hint_recovers_on_retry(ctx):
    client = FakeModelClient([reply("use compute_total_secret()"), reply("Check your return.")])
    h = asyncio.run(generate_hint(ctx, client))
    assert h.source == "model" and h.leaks_rejected == 1 and h.text == "Check your return."


def test_hint_rejects_long_code_block(ctx):
    long_code = reply("```python\na=1\nb=2\nc=3\n```")
    client = FakeModelClient([long_code, long_code])
    h = asyncio.run(generate_hint(ctx, client))
    assert h.source == "fallback" and h.leaks_rejected == 2
    assert "code block" in client.requests[1].prompt


@pytest.mark.parametrize(
    "text",
    [
        "Try this:\n```python\na=1\nb=2\nc=3\n",
        "Try this:\n~~~python\na=1\nb=2\nc=3\n~~~\n",
        "Try this:\n\n    a = 1\n    b = 2\n    c = 3\n\nthen rerun.",
        "Try this:\n\n\ta = 1\n\tb = 2\n\tc = 3\n",
    ],
    ids=["unclosed-backticks", "tilde-fence", "indented-spaces", "indented-tabs"],
)
def test_hint_rejects_other_code_forms(ctx, text):
    client = FakeModelClient([reply(text), reply(text)])
    h = asyncio.run(generate_hint(ctx, client))
    assert h.source == "fallback" and h.leaks_rejected == 2
    assert "code block" in client.requests[1].prompt


def test_hint_allows_short_indented_code(ctx):
    client = FakeModelClient([reply("Look at:\n\n    return a - b\n\nwhat does it compute?")])
    assert asyncio.run(generate_hint(ctx, client)).source == "model"


def test_hint_scopes_tools_to_workspace_and_readme(ctx):
    client = FakeModelClient([reply("Check your return.")])
    asyncio.run(generate_hint(ctx, client))
    assert client.requests[0].allowed_paths == [ctx.workspace, ctx.exercise.readme_path]


def test_hint_carries_cost_session_and_model(ctx):
    paid = ModelResult("Check your return.", None, 0.03, "sid-1", "claude-x")
    h = asyncio.run(generate_hint(ctx, FakeModelClient([paid])))
    assert (h.cost_usd, h.session_id, h.model) == (0.03, "sid-1", "claude-x")


def test_fallback_is_logged_with_leaked_terms(ctx):
    client = FakeModelClient([reply("use compute_total_secret()")] * 2)
    asyncio.run(generate_hint(ctx, client))
    log = miubais_home() / "hints" / ctx.exercise.id / f"{ctx.stage.id}.jsonl"
    entry = json.loads(log.read_text().splitlines()[0])
    assert entry["source"] == "fallback" and entry["leaks_rejected"] == 2
    assert entry["leaked_terms"] == ["compute_total_secret"]


def test_hint_allows_short_code_block(ctx):
    client = FakeModelClient([reply("Try:\n```python\nreturn x\n```")])
    assert asyncio.run(generate_hint(ctx, client)).source == "model"


def test_model_error_falls_back(ctx):
    class Failing:
        async def complete(self, req):
            raise ModelError("boom")

    h = asyncio.run(generate_hint(ctx, Failing()))
    assert h.source == "fallback" and h.leaks_rejected == 0
    assert "tests/test_01_add.py" in h.text and ctx.stage.title in h.text


def test_hint_is_logged(ctx):
    asyncio.run(generate_hint(ctx, FakeModelClient([reply("Check your return.")])))
    log = miubais_home() / "hints" / ctx.exercise.id / f"{ctx.stage.id}.jsonl"
    entry = json.loads(log.read_text().splitlines()[0])
    assert entry["source"] == "model" and entry["text"] == "Check your return."
    assert entry["leaks_rejected"] == 0 and "at" in entry


def test_build_context_reads_diff_and_output(sample_ex, started_ws, tmp_repo):
    src = started_ws / "src"
    target = next(src.rglob("*.py"))
    target.write_text(target.read_text() + "\nMARKER_LINE = 1\n")
    (src / "extra_file.py").write_text("NEW_FILE = 2\n")
    home = miubais_home()
    out = home / "output" / sample_ex.id / "01-add.txt"
    out.parent.mkdir(parents=True)
    out.write_text("AssertionError: boom")
    p = load_progress(home)
    record(p, sample_ex.id, "01-add", "failed", str(out))
    save_progress(p, home, None)
    c = build_context(sample_ex, started_ws, home)
    assert c.stage.id == "01-add"
    assert "+MARKER_LINE = 1" in c.diff and "+NEW_FILE = 2" in c.diff
    assert c.failing_output == "AssertionError: boom"


def test_build_context_tolerates_deleted_output(sample_ex, started_ws, tmp_repo):
    home = miubais_home()
    p = load_progress(home)
    record(p, sample_ex.id, "01-add", "failed", str(home / "output" / "gone.txt"))
    save_progress(p, home, None)
    assert build_context(sample_ex, started_ws, home).failing_output == ""


def test_build_context_without_failure(sample_ex, started_ws, tmp_repo):
    with pytest.raises(HintError, match="no failing stage recorded"):
        build_context(sample_ex, started_ws, miubais_home())


def test_build_context_not_started(sample_ex, tmp_repo):
    with pytest.raises(HintError, match="not started"):
        build_context(sample_ex, tmp_repo / "workspace" / sample_ex.id, miubais_home())


def public_copy(sample_ex, tmp_path):
    shutil.copytree(sample_ex.dir, tmp_path / "ex")
    shutil.rmtree(tmp_path / "ex" / "reference")
    return load_exercise(tmp_path / "ex")


def test_leak_terms_read_from_tests_dir(sample_ex, tmp_path):
    ex = public_copy(sample_ex, tmp_path)
    ex.leak_terms_path.write_text("hidden_alpha\n")
    assert leak_terms_for(ex) == {"hidden_alpha"}


def test_leak_terms_missing_without_reference_raises(sample_ex, tmp_path):
    ex = public_copy(sample_ex, tmp_path)
    with pytest.raises(HintError, match="selftest"):
        leak_terms_for(ex)


def test_cli_hint_unknown_exercise(fixture_course_cli):
    r = CliRunner().invoke(app, ["hint", "nope"])
    assert r.exit_code == 1 and "unknown exercise" in r.output


def test_cli_hint_without_failure(fixture_course_cli, started_ws):
    r = CliRunner().invoke(app, ["hint", "x-sample"])
    assert r.exit_code == 1 and "no failing stage recorded" in r.output


def test_cli_hint_prints_hint_and_source(fixture_course_cli, started_ws, sample_ex, monkeypatch):
    home = miubais_home()
    p = load_progress(home)
    record(p, sample_ex.id, "01-add", "failed", None)
    save_progress(p, home, None)
    monkeypatch.setattr(
        "miubais.cli.default_client", lambda: FakeModelClient([reply("Check your return.")])
    )
    r = CliRunner().invoke(app, ["hint", "x-sample"])
    assert r.exit_code == 0
    assert "Check your return." in r.output and "source: model" in r.output
