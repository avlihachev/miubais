import json
from datetime import date, timedelta
from pathlib import Path

import pytest
from miubais.freshness.frontmatter import Lesson
from miubais.freshness.links import LinkStatus
from miubais.freshness.report import (
    DriftInfo,
    FreshnessReport,
    LessonFreshness,
    badge_for,
    render_markdown,
    write_report,
)

TODAY = date(2026, 10, 17)
OK = LinkStatus(
    url="https://a.com", status=200, final_url="https://a.com", ok=True, redirected=False
)
BROKEN = LinkStatus(
    url="https://b.com", status=404, final_url="https://b.com", ok=False, redirected=False
)
MOVED = OK.model_copy(update={"redirected": True})


def lesson(age, executed="local"):
    return Lesson(
        path=Path("m1/a.md"),
        title="A",
        module="m1",
        order=1,
        verified_on=TODAY - timedelta(days=age),
        executed=executed,
    )


def test_badge_rules():
    assert badge_for(lesson(10), {}, [OK], TODAY) == "green"
    assert badge_for(lesson(10, "none"), {}, [OK], TODAY) == "amber"
    assert badge_for(lesson(200), {}, [OK], TODAY) == "red"
    assert badge_for(lesson(10), {}, [BROKEN], TODAY) == "red"
    minor = {"pypi:x": DriftInfo(pinned="1.0.0", latest="1.1.0", level="minor")}
    assert badge_for(lesson(10), minor, [OK], TODAY) == "amber"


@pytest.mark.parametrize(
    ("age", "badge"), [(90, "green"), (91, "amber"), (180, "amber"), (181, "red")]
)
def test_age_boundaries(age, badge):
    assert badge_for(lesson(age), {}, [OK], TODAY) == badge


def test_patch_drift_keeps_green_redirect_is_amber():
    soft = {"pypi:x": DriftInfo(pinned="1.0.0", latest="1.0.1", level="patch")}
    assert badge_for(lesson(10), soft, [OK], TODAY) == "green"
    assert badge_for(lesson(10), {}, [MOVED], TODAY) == "amber"


def test_unknown_drift_is_amber_and_listed():
    unresolved = {"npm:y": DriftInfo(pinned="1", latest=None, level="unknown")}
    assert badge_for(lesson(10), unresolved, [OK], TODAY) == "amber"
    entry = sample_report().lessons[0].model_copy(update={"drifts": unresolved})
    md = render_markdown(FreshnessReport(generated_at="2026-10-17T10:00:00+00:00", lessons=[entry]))
    assert "npm:y 1 -> None (unknown)" in md


def sample_report():
    entry = LessonFreshness(
        slug="m1/a",
        path=Path("m1/a.md"),
        title="A",
        verified_on=TODAY,
        executed="local",
        drifts={"pypi:x": DriftInfo(pinned="1.0.0", latest="2.0.0", level="major")},
        links=[BROKEN],
        badge="red",
    )
    return FreshnessReport(generated_at="2026-10-17T10:00:00+00:00", lessons=[entry])


def test_write_report_files(tmp_path):
    json_path, md_path = write_report(sample_report(), tmp_path)
    assert json_path == tmp_path / "latest.json" and md_path == tmp_path / "report-2026-10-17.md"
    data = json.loads(json_path.read_text())
    row = data["lessons"][0]
    assert row["slug"] == "m1/a" and row["verified_on"] == "2026-10-17" and row["badge"] == "red"
    assert row["drifts"]["pypi:x"] == {"pinned": "1.0.0", "latest": "2.0.0", "level": "major"}
    assert row["links"][0]["url"] == "https://b.com" and row["links"][0]["ok"] is False
    md = md_path.read_text()
    assert "m1/a" in md and "red" in md and "pypi:x" in md and "https://b.com" in md
    assert render_markdown(sample_report()) == md


def test_report_filename_uses_generated_at_utc_date(tmp_path):
    late = sample_report().model_copy(update={"generated_at": "2026-10-16T23:30:00+00:00"})
    _, md_path = write_report(late, tmp_path)
    assert md_path.name == "report-2026-10-16.md"
