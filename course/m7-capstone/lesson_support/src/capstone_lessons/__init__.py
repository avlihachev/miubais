import json
import re
import statistics
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

import yaml
from capstone.types import Finding, Label
from pydantic import ValidationError

WEIGHTS = {
    "conflict": 100,
    "verify-failed": 90,
    "stale-migration": 80,
    "missing-second-approval": 60,
    "unreviewed-age": 30,
}
BLOCKING_SIGNALS = {"conflict", "verify-failed", "stale-migration"}
TWO_APPROVAL_DIRS = ("proto/", "migrations/", ".claude/")
MAX_AGE_DAYS = 14
GLOB_TOKEN = re.compile(r"\*\*/|\*\*|\*|\?|[^*?]+")
TOP_LEVEL_COMMA = re.compile(r",(?![^{]*\})")
DIFF_PATH = re.compile(r"^(?:\+\+\+ b|--- a)/(\S+)$", re.MULTILINE)


def expand_braces(pattern: str) -> list[str]:
    group = re.search(r"\{([^{}]*)\}", pattern)
    if group is None:
        return [pattern]
    head, tail = pattern[: group.start()], pattern[group.end() :]
    return [
        out for option in group.group(1).split(",") for out in expand_braces(head + option + tail)
    ]


def glob_regex(pattern: str, *, globstar: bool = True) -> str:
    out = []
    for token in GLOB_TOKEN.findall(pattern):
        if token == "**/":
            out.append(r"(?:[^/]+/)*" if globstar else r"[^/]*/")
        elif token == "**":
            out.append(r".*" if globstar else r"[^/]*")
        elif token == "*":
            out.append(r"[^/]*")
        elif token == "?":
            out.append(r"[^/]")
        else:
            out.append(re.escape(token))
    return "".join(out)


def glob_matches(pattern: str, path: str, *, globstar: bool = True) -> bool:
    return any(re.fullmatch(glob_regex(p, globstar=globstar), path) for p in expand_braces(pattern))


@dataclass(frozen=True)
class RuleInfo:
    name: str
    paths: tuple[str, ...]


def load_rules(repo: Path) -> list[RuleInfo]:
    root = Path(repo) / ".claude" / "rules"
    found = []
    for path in sorted(root.rglob("*.md"), key=lambda p: p.relative_to(root).as_posix()):
        text = path.read_text()
        meta = {}
        if text.startswith("---\n"):
            meta = yaml.safe_load(text.split("---\n", 2)[1]) or {}
        raw = meta.get("paths") or []
        if isinstance(raw, str):
            raw = TOP_LEVEL_COMMA.split(raw)
        name = path.relative_to(root).with_suffix("").as_posix()
        found.append(RuleInfo(name, tuple(p.strip() for p in raw if p.strip())))
    return found


def rules_for(rules: list[RuleInfo], files: Iterable[str]) -> list[str]:
    files = list(files)
    always = [r.name for r in rules if not r.paths]
    scoped = [
        r.name for r in rules if r.paths and any(glob_matches(p, f) for p in r.paths for f in files)
    ]
    return always + scoped


def changed_paths(patch_text: str) -> list[str]:
    seen: list[str] = []
    for path in DIFF_PATH.findall(patch_text):
        if path not in seen:
            seen.append(path)
    return seen


def accept_findings(raw: list[dict]) -> tuple[list[Finding], list[str]]:
    accepted, rejected = [], []
    for item in raw:
        try:
            accepted.append(Finding(**item))
        except ValidationError as error:
            fields = sorted({str(e["loc"][0]) for e in error.errors()})
            rejected.append(
                f"{item.get('file')}:{item.get('line')} rejected on {', '.join(fields)}"
            )
    return accepted, rejected


def same_issue(finding: Finding, label: Label, slack: int = 3) -> bool:
    return (
        finding.file == label.file
        and finding.category == label.category
        and label.start - slack <= finding.line <= label.end + slack
    )


def same_file(finding: Finding, label: Label) -> bool:
    return finding.file == label.file


def pair_up(
    findings: list[Finding],
    labels: list[Label],
    rule: Callable[[Finding, Label], bool] = same_issue,
) -> list[tuple[int, int]]:
    free = list(range(len(labels)))
    pairs = []
    for i in sorted(range(len(findings)), key=lambda i: -findings[i].confidence):
        j = next((j for j in free if rule(findings[i], labels[j])), None)
        if j is not None:
            free.remove(j)
            pairs.append((i, j))
    return sorted(pairs, key=lambda pair: pair[1])


@dataclass(frozen=True)
class Scored:
    precision: float
    recall: float
    f1: float
    findings: int
    labels: int


def score(
    findings: list[Finding],
    labels: list[Label],
    pairs: list[tuple[int, int]],
    severity: str | None = None,
) -> Scored:
    def keep(item: Finding | Label) -> bool:
        return severity is None or item.severity == severity

    n_findings = sum(1 for f in findings if keep(f))
    n_labels = sum(1 for label in labels if keep(label))
    hit_findings = sum(1 for i, _ in pairs if keep(findings[i]))
    hit_labels = sum(1 for _, j in pairs if keep(labels[j]))
    precision = hit_findings / n_findings if n_findings else 1.0
    recall = hit_labels / n_labels if n_labels else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return Scored(precision, recall, f1, n_findings, n_labels)


@dataclass(frozen=True)
class Signals:
    pr: str
    touches: tuple[str, ...] = ()
    approvals: int = 0
    age_days: int = 0
    applied: bool = True
    tests_failed: bool = False
    existing_migrations: tuple[int, ...] = ()
    new_migrations: tuple[int, ...] = ()
    finding_severities: tuple[str, ...] = ()


def blocker_kinds(s: Signals) -> list[str]:
    kinds = []
    if not s.applied:
        kinds.append("conflict")
    elif s.tests_failed:
        kinds.append("verify-failed")
    expected = max(s.existing_migrations, default=0) + 1
    for offset, number in enumerate(sorted(s.new_migrations)):
        if number in s.existing_migrations or number != expected + offset:
            kinds.append("stale-migration")
            break
    if any(p.startswith(TWO_APPROVAL_DIRS) for p in s.touches) and s.approvals < 2:
        kinds.append("missing-second-approval")
    if s.approvals == 0 and s.age_days > MAX_AGE_DAYS:
        kinds.append("unreviewed-age")
    return sorted(kinds, key=lambda k: -WEIGHTS[k])


def verdict(kinds: list[str], finding_severities: Iterable[str]) -> str:
    severities = set(finding_severities)
    if "blocker" in severities or BLOCKING_SIGNALS & set(kinds):
        return "block"
    if "major" in severities or kinds:
        return "hold"
    return "merge"


@dataclass(frozen=True)
class RankedPR:
    pr: str
    score: int
    kinds: tuple[str, ...]
    verdict: str


def rank_prs(signals: list[Signals]) -> list[RankedPR]:
    rows = []
    for s in signals:
        kinds = blocker_kinds(s)
        rows.append(
            RankedPR(
                s.pr,
                sum(WEIGHTS[k] for k in kinds),
                tuple(kinds),
                verdict(kinds, s.finding_severities),
            )
        )
    return sorted(rows, key=lambda r: (-r.score, r.pr))


def live_summary(path: Path) -> dict:
    record = json.loads(Path(path).read_text())
    reviewed = [p for p in record["prs"] if p["review"] == "ok"]
    costs = [p["cost_usd"] for p in reviewed]
    turns = [p["turns"] for p in reviewed]
    seconds = [p["duration_ms"] / 1000 for p in reviewed]
    overall = record["metrics"]["overall"]
    matched = round(overall["precision"] * overall["findings"])
    return {
        "model": record["model"],
        "prs": record["totals"]["prs"],
        "reviewed": len(reviewed),
        "total_usd": record["totals"]["cost_usd"],
        "usd_min": min(costs),
        "usd_median": statistics.median(costs),
        "usd_max": max(costs),
        "usd_mean": statistics.fmean(costs),
        "turns_median": statistics.median(turns),
        "turns_max": max(turns),
        "seconds_median": statistics.median(seconds),
        "wall_seconds": record["totals"]["duration_ms"] / 1000,
        "verdicts": dict(Counter(p["verdict"] for p in record["prs"])),
        "precision": overall["precision"],
        "recall": overall["recall"],
        "blocker_recall": record["metrics"]["blocker_recall"],
        "findings": overall["findings"],
        "noise": overall["findings"] - matched,
        "labels": overall["labels"],
        "agree_with_key": record["verdicts_agreeing_with_key"],
        "review_failed": record["totals"]["review_failed"],
    }
