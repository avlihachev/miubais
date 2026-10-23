import difflib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from typing import Literal

from miubais.exercises import Exercise, Stage
from miubais.model import ModelClient, ModelError, ModelRequest
from miubais.progress import load_progress
from miubais.tutor.leak import exercise_leak_terms, find_leaks, learner_identifiers

MAX_OUTPUT_CHARS = 4000
MAX_DIFF_CHARS = 6000
MAX_CODE_LINES = 2
MAX_INDENTED_LINES = 2
MAX_ATTEMPTS = 2
FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
INDENTED = re.compile(r"^( {4}|\t)\S")


class HintError(Exception):
    pass


@dataclass(frozen=True)
class HintContext:
    exercise: Exercise
    stage: Stage
    diff: str
    failing_output: str
    leak_terms: set[str]
    workspace: Path
    home: Path


@dataclass(frozen=True)
class Hint:
    text: str
    source: Literal["model", "fallback"]
    leaks_rejected: int
    leaked_terms: tuple[str, ...] = ()
    model: str | None = None
    cost_usd: float = 0.0
    session_id: str | None = None


def _read(path: Path) -> list[str]:
    return path.read_text(errors="ignore").splitlines(keepends=True) if path.is_file() else []


def diff_against_starter(starter_src: Path, workspace_src: Path) -> str:
    names = {
        p.relative_to(root) for root in (starter_src, workspace_src) for p in root.rglob("*.py")
    }
    chunks = []
    for name in sorted(names):
        chunks.extend(
            difflib.unified_diff(
                _read(starter_src / name),
                _read(workspace_src / name),
                fromfile=f"starter/{name}",
                tofile=f"workspace/{name}",
            )
        )
    return "".join(chunks)


def leak_terms_for(ex: Exercise) -> set[str]:
    recorded = ex.leak_terms_path
    if recorded.is_file():
        return {line for line in recorded.read_text().splitlines() if line}
    if not ex.has_reference:
        raise HintError(
            f"leak terms missing at {recorded}; run `uv run miubais selftest` in the private checkout"
        )
    return exercise_leak_terms(ex)


def hint_leak_terms(ex: Exercise, diff: str) -> set[str]:
    return leak_terms_for(ex) - learner_identifiers(diff)


def build_context(ex: Exercise, workspace_path: Path, home: Path) -> HintContext:
    if not workspace_path.is_dir():
        raise HintError(f"{ex.id} is not started; run `uv run miubais start {ex.id}` first")
    records = load_progress(home).exercises.get(ex.id, {})
    failed = [
        (rec.at, stage)
        for stage in ex.stages
        if (rec := records.get(stage.id)) is not None and rec.status == "failed"
    ]
    if not failed:
        raise HintError("no failing stage recorded; run `uv run miubais check` first")
    _, stage = max(failed, key=lambda item: item[0])
    output_path = records[stage.id].output_path
    output = ""
    if output_path:
        try:
            output = Path(output_path).read_text(errors="ignore")
        except OSError:
            output = ""
    diff = diff_against_starter(ex.starter_dir / "src", workspace_path / "src")
    return HintContext(
        exercise=ex,
        stage=stage,
        diff=diff,
        failing_output=output,
        leak_terms=hint_leak_terms(ex, diff),
        workspace=workspace_path,
        home=home,
    )


def _prompt(ctx: HintContext, violation: str | None) -> str:
    prompt = (
        f"## Stage\n{ctx.stage.id}: {ctx.stage.title}\n\n"
        f"## Failing test output\n{ctx.failing_output[-MAX_OUTPUT_CHARS:]}\n\n"
        f"## Learner diff against the starter\n{ctx.diff[:MAX_DIFF_CHARS]}\n\n"
        "## Your task\nWrite a hint under 90 words, following the policy.\n"
    )
    if violation:
        prompt += f"\n## Retry\n{violation}\n"
    return prompt


def _fenced_blocks(lines: list[str]) -> tuple[list[list[str]], list[str]]:
    blocks: list[list[str]] = []
    outside: list[str] = []
    fence: str | None = None
    for line in lines:
        match = FENCE.match(line)
        if fence is None:
            if match:
                fence, current = match.group(1), []
            else:
                outside.append(line)
        elif match and match.group(1)[0] == fence[0] and len(match.group(1)) >= len(fence):
            blocks.append(current)
            fence = None
        else:
            current.append(line)
    if fence is not None:
        blocks.append(current)
    return blocks, outside


def _longest_indented_run(lines: list[str]) -> int:
    longest = run = 0
    for line in lines:
        if INDENTED.match(line):
            run += 1
            longest = max(longest, run)
        elif line.strip():
            run = 0
    return longest


def has_long_code(text: str) -> bool:
    blocks, outside = _fenced_blocks(text.splitlines())
    if any(sum(1 for line in b if line.strip()) > MAX_CODE_LINES for b in blocks):
        return True
    return _longest_indented_run(outside) > MAX_INDENTED_LINES


def _violation(text: str, terms: set[str]) -> tuple[str | None, list[str]]:
    leaked = find_leaks(text, terms)
    if leaked:
        return f"your previous hint leaked: {', '.join(leaked)}", list(leaked)
    if has_long_code(text):
        return "your previous hint contained a code block longer than two lines", []
    return None, []


def _fallback(ctx: HintContext) -> str:
    tests = Path(ctx.exercise.dir, ctx.stage.tests)
    return (
        f"The failing assertion is in {tests} (stage '{ctx.stage.title}'). "
        "Read the assertion and the name of the test; it tells you what the stage expects."
    )


def _log(ctx: HintContext, hint: Hint) -> None:
    path = ctx.home / "hints" / ctx.exercise.id / f"{ctx.stage.id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "at": datetime.now(UTC).isoformat(),
        "source": hint.source,
        "leaks_rejected": hint.leaks_rejected,
        "leaked_terms": list(hint.leaked_terms),
        "text": hint.text,
    }
    with path.open("a") as f:
        f.write(json.dumps(entry) + "\n")


async def generate_hint(ctx: HintContext, client: ModelClient) -> Hint:
    system = files("miubais.tutor").joinpath("policy.md").read_text()
    rejected = 0
    leaked: list[str] = []
    cost = 0.0
    violation = None
    hint = None
    for _ in range(MAX_ATTEMPTS):
        request = ModelRequest(
            system=system,
            prompt=_prompt(ctx, violation),
            cwd=ctx.workspace,
            allowed_tools=["Read", "Grep", "Glob"],
            max_turns=3,
            allowed_paths=[ctx.workspace, ctx.exercise.readme_path],
        )
        try:
            result = await client.complete(request)
        except ModelError as err:
            cost += err.cost_usd
            break
        cost += result.cost_usd
        violation, terms = _violation(result.text, ctx.leak_terms)
        leaked.extend(t for t in terms if t not in leaked)
        if violation is None:
            hint = Hint(
                result.text.strip(),
                "model",
                rejected,
                tuple(leaked),
                result.model,
                cost,
                result.session_id,
            )
            break
        rejected += 1
    if hint is None:
        hint = Hint(_fallback(ctx), "fallback", rejected, tuple(leaked), cost_usd=cost)
    _log(ctx, hint)
    return hint
