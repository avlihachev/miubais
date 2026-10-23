import json
from datetime import date, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from miubais.freshness.frontmatter import Lesson
from miubais.freshness.links import LinkStatus
from miubais.freshness.resolve import Level

Badge = Literal["green", "amber", "red"]
GREEN_DAYS = 90
RED_DAYS = 180


class DriftInfo(BaseModel):
    pinned: str
    latest: str | None
    level: Level


class LessonFreshness(BaseModel):
    slug: str
    path: Path
    title: str
    verified_on: date
    executed: str
    drifts: dict[str, DriftInfo]
    links: list[LinkStatus]
    badge: Badge


class FreshnessReport(BaseModel):
    generated_at: str
    lessons: list[LessonFreshness]


def badge_for(
    lesson: Lesson, drifts: dict[str, DriftInfo], links: list[LinkStatus], today: date
) -> Badge:
    age = (today - lesson.verified_on).days
    if age > RED_DAYS or any(not link.ok for link in links):
        return "red"
    stale_pin = any(d.level in ("minor", "major", "unknown") for d in drifts.values())
    if lesson.executed == "none" or stale_pin or any(link.redirected for link in links):
        return "amber"
    return "green" if age <= GREEN_DAYS else "amber"


def drift_summary(drifts: dict[str, DriftInfo]) -> str:
    flagged = [
        f"{k} {d.pinned} -> {d.latest} ({d.level})" for k, d in drifts.items() if d.level != "none"
    ]
    return "; ".join(flagged) or "none"


def render_markdown(report: FreshnessReport) -> str:
    lines = ["# Freshness report", "", f"Generated at {report.generated_at}", ""]
    for entry in report.lessons:
        lines += [
            f"## {entry.slug} - {entry.badge}",
            "",
            f"- verified_on: {entry.verified_on.isoformat()}",
            f"- executed: {entry.executed}",
            f"- drift: {drift_summary(entry.drifts)}",
        ]
        broken = [link for link in entry.links if not link.ok]
        lines.append("- broken links: " + (", ".join(link.url for link in broken) or "none"))
        lines.append("")
    return "\n".join(lines)


def write_report(report: FreshnessReport, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    generated_on = datetime.fromisoformat(report.generated_at).date()
    json_path = out_dir / "latest.json"
    md_path = out_dir / f"report-{generated_on.isoformat()}.md"
    json_path.write_text(json.dumps(report.model_dump(mode="json"), indent=2) + "\n")
    md_path.write_text(render_markdown(report))
    return json_path, md_path
