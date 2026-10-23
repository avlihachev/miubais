from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path

import httpx

from miubais.freshness.frontmatter import Lesson, parse_pin_key
from miubais.freshness.links import check_all
from miubais.freshness.report import DriftInfo, FreshnessReport, LessonFreshness, badge_for
from miubais.freshness.resolve import drift, latest


def _relative(path: Path, root: Path | None) -> Path:
    if root is None or not path.is_absolute() or not path.is_relative_to(root):
        return path
    return path.relative_to(root)


def build_report(
    lessons: list[Lesson],
    *,
    http: httpx.Client,
    gh: Callable[[str], dict] | None,
    ignore: list[str],
    today: date,
    root: Path | None = None,
) -> FreshnessReport:
    urls = [str(s.url) for lesson in lessons for s in lesson.sources]
    statuses = dict(zip(urls, check_all(urls, http=http, ignore=ignore)))
    entries = []
    for lesson in lessons:
        drifts = {}
        for key, pinned in lesson.pins.items():
            kind, name = parse_pin_key(key)
            newest = latest(kind, name, http=http, gh=gh)
            drifts[key] = DriftInfo(
                pinned=pinned, latest=newest, level=drift(pinned, newest, kind=kind)
            )
        links = [statuses[str(s.url)] for s in lesson.sources]
        entries.append(
            LessonFreshness(
                slug=lesson.slug,
                path=_relative(lesson.path, root),
                title=lesson.title,
                verified_on=lesson.verified_on,
                executed=lesson.executed,
                drifts=drifts,
                links=links,
                badge=badge_for(lesson, drifts, links, today),
            )
        )
    return FreshnessReport(
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"), lessons=entries
    )
