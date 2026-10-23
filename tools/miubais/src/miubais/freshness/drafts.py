from datetime import date
from pathlib import Path

from miubais.freshness.report import DriftInfo, LessonFreshness
from miubais.model import ModelClient, ModelError, ModelRequest
from miubais.paths import repo_root

HEADER = "<!-- draft by model, review before use -->"
SYSTEM = (
    "You draft maintenance notes for a technical course. "
    "Be concrete and cautious; cite the URLs you consulted."
)
TASK = (
    "Write at most 200 words: what changed between the pinned and latest versions that could "
    "affect this lesson, and which sections or code samples to re-verify. You may fetch the "
    "official release notes or changelog for the listed packages. Do not invent changes you "
    "did not find; if nothing relevant, say so."
)


def needs_draft(lf: LessonFreshness) -> bool:
    return any(d.level in ("minor", "major") for d in lf.drifts.values()) or any(
        not link.ok for link in lf.links
    )


def _drift_line(key: str, drift: DriftInfo) -> str:
    return f"{key} {drift.pinned} -> {drift.latest}"


def build_prompt(lf: LessonFreshness) -> str:
    drifted = [_drift_line(k, d) for k, d in lf.drifts.items() if d.level in ("minor", "major")]
    broken = [
        f"{link.url} status={link.status} final_url={link.final_url}"
        for link in lf.links
        if not link.ok or link.redirected
    ]
    return "\n".join(
        [
            "## Lesson",
            f"title: {lf.title}",
            f"slug: {lf.slug}",
            f"verified_on: {lf.verified_on.isoformat()}",
            "",
            "## Drifted pins",
            *(drifted or ["none"]),
            "",
            "## Broken or redirected sources",
            *(broken or ["none"]),
            "",
            "## Your task",
            TASK,
        ]
    )


async def draft_note(lf: LessonFreshness, client: ModelClient) -> str:
    request = ModelRequest(
        system=SYSTEM,
        prompt=build_prompt(lf),
        cwd=repo_root(),
        allowed_tools=["WebFetch", "WebSearch"],
        max_turns=6,
        allow_web=True,
    )
    return (await client.complete(request)).text


def draft_path(out_dir: Path, slug: str) -> Path:
    return out_dir / "drafts" / f"{slug.replace('/', '__')}.md"


async def write_draft(
    lf: LessonFreshness, client: ModelClient, out_dir: Path, today: date
) -> tuple[Path, bool]:
    try:
        body, ok = await draft_note(lf, client), True
    except ModelError as err:
        body, ok = f"model error: {err}", False
    path = draft_path(out_dir, lf.slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    title = f"# {lf.title} — freshness note {today.isoformat()}"
    path.write_text(f"{HEADER}\n{title}\n\n{body.strip()}\n" if ok else f"{HEADER}\n{body}\n")
    return path, ok
