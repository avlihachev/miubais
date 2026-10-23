import asyncio
from datetime import date
from pathlib import Path

from miubais.freshness.drafts import HEADER, draft_note, needs_draft, write_draft
from miubais.freshness.links import LinkStatus
from miubais.freshness.report import DriftInfo, LessonFreshness
from miubais.model import FakeModelClient, ModelError, ModelResult


def make_lesson(drifts=None, links=None, slug="m1/01-harness"):
    return LessonFreshness(
        slug=slug,
        path=Path("x.md"),
        title="Harness",
        verified_on=date(2026, 9, 1),
        executed="full",
        drifts=drifts if drifts is not None else {},
        links=links or [],
        badge="amber",
    )


def drifted():
    return make_lesson(
        {
            "pypi:langfuse": DriftInfo(pinned="3.4.0", latest="5.0.2", level="major"),
            "npm:x": DriftInfo(pinned="1.0.0", latest="1.0.0", level="none"),
        },
        [LinkStatus(url="https://a.dev/x", status=404, ok=False)],
    )


def reply(text):
    return ModelResult(text=text, structured=None, cost_usd=0.0, session_id=None)


def test_draft_note_prompt_names_each_drift():
    client = FakeModelClient([reply("note")])
    assert asyncio.run(draft_note(drifted(), client)) == "note"
    req = client.requests[0]
    assert "pypi:langfuse 3.4.0 -> 5.0.2" in req.prompt
    assert "npm:x" not in req.prompt
    assert "https://a.dev/x" in req.prompt and "Harness" in req.prompt
    assert req.allowed_tools == ["WebFetch", "WebSearch"] and req.allow_web


def test_needs_draft():
    assert needs_draft(drifted())
    assert not needs_draft(make_lesson())
    broken = [LinkStatus(url="u", status=500, ok=False)]
    assert needs_draft(make_lesson(links=broken))
    patch = {"a": DriftInfo(pinned="1", latest="1.0.1", level="patch")}
    assert not needs_draft(make_lesson(patch))


def test_write_draft_file_layout(tmp_path):
    client = FakeModelClient([reply("what changed")])
    path, ok = asyncio.run(write_draft(drifted(), client, tmp_path, date(2026, 10, 16)))
    assert ok and path == tmp_path / "drafts" / "m1__01-harness.md"
    lines = path.read_text().splitlines()
    assert lines[0] == HEADER
    assert lines[1] == "# Harness — freshness note 2026-10-16"
    assert lines[-1] == "what changed"


def test_write_draft_records_model_error(tmp_path):
    client = FakeModelClient([ModelError("boom")])
    path, ok = asyncio.run(write_draft(drifted(), client, tmp_path, date(2026, 10, 16)))
    assert not ok
    assert path.read_text() == f"{HEADER}\nmodel error: boom\n"
