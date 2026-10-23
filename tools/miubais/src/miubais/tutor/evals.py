import hashlib
import json
import shutil
import tempfile
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from miubais.exercises import Exercise, load_exercise
from miubais.model import ModelClient, ModelError, ModelRequest, ModelResult
from miubais.tutor.hint import (
    Hint,
    HintContext,
    diff_against_starter,
    generate_hint,
    hint_leak_terms,
)
from miubais.tutor.leak import find_leaks

EVALS_DIR = Path(__file__).parent / "evals"
CASES_DIR = EVALS_DIR / "cases"
RUNS_DIR = EVALS_DIR / "runs"
CONCEPT_THRESHOLD = 0.8
MAX_HINT_WORDS = 90


class EvalError(Exception):
    pass


class EvalCase(BaseModel):
    exercise: str
    stage: str
    learner_src: dict[str, str]
    failing_output: str
    must_mention_all: list[list[str]] = Field(min_length=1)
    must_not_contain: list[str]
    file: str = ""


class EvalReport(BaseModel):
    cases: int
    leaks: int
    concept_hits: int
    failures: list[str]
    too_long: int = 0

    @property
    def passed(self) -> bool:
        return (
            self.leaks == 0
            and self.too_long == 0
            and self.cases > 0
            and self.concept_hits / self.cases >= CONCEPT_THRESHOLD
        )


def case_hash(case: EvalCase) -> str:
    content = json.dumps(case.model_dump(exclude={"file"}), sort_keys=True)
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def load_cases(directory: Path) -> list[EvalCase]:
    cases = []
    for path in sorted(directory.glob("*.yaml")):
        case = EvalCase.model_validate(yaml.safe_load(path.read_text()))
        cases.append(case.model_copy(update={"file": path.name}))
    return cases


def _load(case: EvalCase, course_dir: Path) -> Exercise:
    path = course_dir / case.exercise
    if not path.is_dir():
        raise EvalError(f"{case.file}: unknown exercise {case.exercise!r} in {course_dir}")
    return load_exercise(path)


def score_hints(cases: list[EvalCase], hints: list[Hint], course_dir: Path) -> EvalReport:
    leaks = hits = too_long = 0
    failures = []
    for case, hint in zip(cases, hints, strict=True):
        text = hint.text.lower()
        ex = _load(case, course_dir)
        banned = {*case.must_not_contain, *hint_leak_terms(ex, case_diff(case, ex))}
        leaked = hint.leaks_rejected > 0 or bool(find_leaks(hint.text, banned))
        fallback = hint.source == "fallback"
        hit = not fallback and all(
            any(m.lower() in text for m in group) for group in case.must_mention_all
        )
        words = len(hint.text.split())
        leaks += leaked
        hits += hit
        if leaked:
            failures.append(f"{case.file}: leak")
        if fallback:
            failures.append(f"{case.file}: fallback hint")
        elif not hit:
            failures.append(f"{case.file}: no concept hit")
        if words > MAX_HINT_WORDS:
            too_long += 1
            failures.append(f"{case.file}: hint is {words} words, limit {MAX_HINT_WORDS}")
    return EvalReport(
        cases=len(cases),
        leaks=leaks,
        concept_hits=hits,
        failures=failures,
        too_long=too_long,
    )


def _write_workspace(case: EvalCase, workspace: Path) -> None:
    for name, content in case.learner_src.items():
        target = workspace / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)


def _prepare_workspace(case: EvalCase, ex: Exercise, workspace: Path) -> None:
    shutil.copytree(ex.starter_dir, workspace)
    _write_workspace(case, workspace)


def case_diff(case: EvalCase, ex: Exercise) -> str:
    with tempfile.TemporaryDirectory(prefix="miubais-eval-diff-") as root:
        workspace = Path(root) / "ws"
        _prepare_workspace(case, ex, workspace)
        return diff_against_starter(ex.starter_dir / "src", workspace / "src")


class RetryOnce:
    def __init__(self, client: ModelClient) -> None:
        self.client = client

    async def complete(self, req: ModelRequest) -> ModelResult:
        try:
            return await self.client.complete(req)
        except ModelError as err:
            try:
                result = await self.client.complete(req)
            except ModelError as again:
                again.cost_usd += err.cost_usd
                raise
            return replace(result, cost_usd=result.cost_usd + err.cost_usd)


async def _generate(case: EvalCase, client: ModelClient, course_dir: Path) -> Hint:
    ex = _load(case, course_dir)
    stage = next((s for s in ex.stages if s.id == case.stage), None)
    if stage is None:
        raise EvalError(f"{case.file}: unknown stage {case.stage!r} in {case.exercise}")
    root = Path(tempfile.mkdtemp(prefix="miubais-eval-"))
    try:
        workspace = root / "ws"
        _prepare_workspace(case, ex, workspace)
        diff = diff_against_starter(ex.starter_dir / "src", workspace / "src")
        ctx = HintContext(
            exercise=ex,
            stage=stage,
            diff=diff,
            failing_output=case.failing_output,
            leak_terms=hint_leak_terms(ex, diff),
            workspace=workspace,
            home=root / "home",
        )
        return await generate_hint(ctx, RetryOnce(client))
    finally:
        shutil.rmtree(root, ignore_errors=True)


async def collect_hints(cases: list[EvalCase], client: ModelClient, course_dir: Path) -> list[Hint]:
    return [await _generate(case, client, course_dir) for case in cases]


async def run_cases(cases: list[EvalCase], client: ModelClient, course_dir: Path) -> EvalReport:
    return score_hints(cases, await collect_hints(cases, client, course_dir), course_dir)


def case_stem(case: EvalCase) -> str:
    return Path(case.file).stem


def _recorded(path: Path) -> dict[str, dict]:
    entries = [json.loads(line) for line in path.read_text().splitlines() if line]
    return {entry["case"]: entry for entry in entries}


def _replay_source(latest: Path, entry: dict) -> str:
    if entry.get("source", "").startswith("replay:"):
        return entry["source"]
    text = latest.read_text()
    dated = (p for p in sorted(latest.parent.glob("2*.jsonl")) if p.read_text() == text)
    return f"replay:{next(dated, latest).name}"


async def collect_selected(
    cases: list[EvalCase], only: set[str], client: ModelClient, course_dir: Path, latest: Path
) -> tuple[list[Hint], list[str]]:
    unknown = only - {case_stem(c) for c in cases}
    if unknown:
        raise EvalError(f"--only names unknown cases: {', '.join(sorted(unknown))}")
    kept = [c for c in cases if case_stem(c) not in only]
    replayed = dict(zip((c.file for c in kept), load_run(latest, kept), strict=True))
    entries = _recorded(latest) if kept else {}
    hints, sources = [], []
    for case in cases:
        if case.file in replayed:
            hints.append(replayed[case.file])
            sources.append(_replay_source(latest, entries[case.file]))
        else:
            hints.append(await _generate(case, client, course_dir))
            sources.append("live")
    return hints, sources


def record_run(
    cases: list[EvalCase],
    hints: list[Hint],
    runs_dir: Path = RUNS_DIR,
    sources: list[str] | None = None,
) -> Path:
    sources = sources or ["live"] * len(cases)
    fallbacks = [c.file for c, h in zip(cases, hints, strict=True) if h.source == "fallback"]
    if fallbacks:
        raise EvalError(f"not recording: fallback hints for {', '.join(fallbacks)}")
    now = datetime.now(UTC)
    lines = "".join(
        json.dumps(
            {
                "case": case.file,
                "case_hash": case_hash(case),
                "hint": hint.text,
                "source": source,
                "leaks_rejected": hint.leaks_rejected,
                "model": hint.model,
                "at": now.isoformat(timespec="seconds"),
                "cost_usd": hint.cost_usd,
                "session_id": hint.session_id,
            }
        )
        + "\n"
        for case, hint, source in zip(cases, hints, sources, strict=True)
    )
    runs_dir.mkdir(parents=True, exist_ok=True)
    dated = _unused_run_path(runs_dir, now.date().isoformat())
    dated.write_text(lines)
    (runs_dir / "latest.jsonl").write_text(lines)
    return dated


def _unused_run_path(runs_dir: Path, day: str) -> Path:
    path = runs_dir / f"{day}.jsonl"
    suffix = 2
    while path.exists():
        path = runs_dir / f"{day}-{suffix}.jsonl"
        suffix += 1
    return path


def load_run(path: Path, cases: list[EvalCase]) -> list[Hint]:
    recorded = {}
    for line in path.read_text().splitlines():
        entry = json.loads(line)
        recorded[entry["case"]] = entry
    missing = [c.file for c in cases if c.file not in recorded]
    if missing:
        raise FileNotFoundError(f"no recorded hint for: {', '.join(missing)}; rerun with --live")
    hints = []
    for case in cases:
        entry = recorded[case.file]
        if not entry.get("session_id") or not entry.get("model"):
            raise EvalError(
                f"{case.file}: not a live recording (no model/session); rerun with --live"
            )
        if entry.get("case_hash") != case_hash(case):
            raise EvalError(f"{case.file}: case changed since the recorded run; rerun with --live")
        hints.append(
            Hint(
                entry["hint"],
                "fallback" if entry["source"] == "fallback" else "model",
                entry["leaks_rejected"],
                model=entry["model"],
                cost_usd=entry.get("cost_usd", 0.0),
                session_id=entry["session_id"],
            )
        )
    return hints
