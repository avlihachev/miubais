import asyncio
import shutil
import tempfile
from datetime import UTC, date, datetime
from importlib.metadata import version
from pathlib import Path

import httpx
import typer
import uvicorn
from rich.console import Console
from rich.table import Table

from miubais.api import create_app
from miubais.doctor import report as doctor_report
from miubais.exercises import Exercise, ExerciseError, Stage, list_exercises
from miubais.freshness.branch import BranchError, commit_on_branch, ensure_clean
from miubais.freshness.drafts import needs_draft, write_draft
from miubais.freshness.frontmatter import FrontmatterError, load_lessons
from miubais.freshness.links import load_ignore
from miubais.freshness.report import FreshnessReport, LessonFreshness, drift_summary, write_report
from miubais.freshness.resolve import gh_api
from miubais.freshness.run import build_report
from miubais.grader import StageResult, SubprocessRunner, run_exercise
from miubais.model import default_client
from miubais.paths import course_dir, miubais_home, repo_root, site_docs_dir, workspace_dir
from miubais.progress import clear, load_progress, save_progress
from miubais.publish import (
    BUILTIN_CONTENT_PATTERNS,
    DENYLIST,
    PublishError,
    check_dest,
    check_export,
    check_paths,
    dest_files,
    export_plan,
    export_tree,
    is_dirty,
    load_denylist,
    manifest_path,
    overlay_paths,
    scan_content,
    select_public,
    top_level_counts,
    tracked_files,
    write_manifest,
)
from miubais.record import RecordingRejected, RequirementError, record_fixtures
from miubais.requirements import SystemProbe
from miubais.selftest import selftest_exercise
from miubais.tutor.evals import (
    CASES_DIR,
    RUNS_DIR,
    EvalError,
    collect_hints,
    collect_selected,
    load_cases,
    load_run,
    record_run,
    score_hints,
)
from miubais.tutor.hint import HintError, build_context, generate_hint
from miubais.workspace import (
    StarterDrift,
    WorkspaceError,
    is_started,
    start_exercise,
    starter_drift,
    workspace_path,
)

app = typer.Typer(no_args_is_help=True)
SITE_URL = "https://factory.lihachev.pro"


def _print_version(value: bool) -> None:
    if value:
        typer.echo(f"miubais {version('miubais')}")
        raise typer.Exit()


@app.callback()
def main(
    show_version: bool = typer.Option(
        False, "--version", callback=_print_version, is_eager=True, help="Show version and exit."
    ),
) -> None:
    pass


@app.command()
def start(
    exercise_id: str = typer.Argument(..., metavar="EXERCISE_ID"),
    force: bool = typer.Option(False, "--force", help="Replace an already started exercise."),
) -> None:
    ex = next((e for e in list_exercises(course_dir()) if e.id == exercise_id), None)
    if ex is None:
        typer.echo(f"unknown exercise: {exercise_id}")
        raise typer.Exit(1)
    try:
        target = start_exercise(ex, force=force)
    except WorkspaceError as err:
        typer.echo(f"{err} (use --force to replace)")
        raise typer.Exit(1) from err
    if force:
        _reset_progress(ex.id)
    typer.echo(f"started {ex.id} at {target}")
    typer.echo(f"next: uv run miubais check {ex.id}")


def _reset_progress(exercise_id: str | None) -> list[str]:
    home = miubais_home()
    progress = load_progress(home)
    cleared = clear(progress, exercise_id)
    mirror = workspace_dir() / ".progress.json"
    save_progress(progress, home, mirror if mirror.exists() else None)
    for ex in cleared:
        shutil.rmtree(home / "output" / ex, ignore_errors=True)
    return cleared


@app.command()
def reset(
    exercise_id: str | None = typer.Argument(None, metavar="[EXERCISE_ID]"),
    all_: bool = typer.Option(False, "--all", help="Forget the progress of every exercise."),
) -> None:
    if (exercise_id is None) == (not all_):
        typer.echo("give an exercise id or --all")
        raise typer.Exit(1)
    cleared = _reset_progress(None if all_ else exercise_id)
    if not cleared:
        typer.echo("nothing recorded" + (f" for {exercise_id}" if exercise_id else ""))
        return
    typer.echo("forgot progress for " + ", ".join(cleared))
    typer.echo("the workspace copy is untouched; `uv run miubais start <id> --force` replaces it")


CourseOption = typer.Option(None, "--course", hidden=True, envvar="MIUBAIS_COURSE")


def _find(exercise_id: str, course: Path | None) -> Exercise | None:
    return next((e for e in list_exercises(course or course_dir()) if e.id == exercise_id), None)


def _status_text(result: StageResult) -> str:
    if result.status == "skipped" and result.reason:
        return f"skipped ({result.reason})"
    if result.status == "skipped":
        return f"skipped (needs {', '.join(result.missing)})"
    if result.cached:
        return "passed (cached live)"
    return result.status


@app.command()
def check(
    exercise_id: str = typer.Argument(..., metavar="EXERCISE_ID"),
    stage: str | None = typer.Option(None, "--stage", help="Run only this stage."),
    all_stages: bool = typer.Option(False, "--all", help="Keep going after a failure."),
    live: bool = typer.Option(False, "--live", help="Re-run live stages that already passed."),
    course: Path | None = CourseOption,
) -> None:
    ex = _find(exercise_id, course)
    if ex is None:
        typer.echo(f"unknown exercise: {exercise_id}")
        raise typer.Exit(1)
    if stage is not None and stage not in {s.id for s in ex.stages}:
        typer.echo(f"unknown stage: {stage}")
        raise typer.Exit(1)
    if not is_started(ex):
        typer.echo(f"{ex.id} is not started; run `uv run miubais start {ex.id}` first")
        raise typer.Exit(2)
    drift = starter_drift(ex, workspace_path(ex))
    if drift is not None:
        typer.echo(_drift_warning(ex, drift))
    result = run_exercise(
        ex,
        workspace_path(ex),
        stop_on_fail=not all_stages,
        only=stage,
        probe=SystemProbe(),
        runner=SubprocessRunner(),
        live=live,
        reuse_live_passes=stage is None and not live,
    )
    table = Table("stage", "title", "status")
    for r in result.results:
        table.add_row(r.stage.id, r.stage.title, _status_text(r))
    Console().print(table)
    failure = result.first_failure
    if failure is not None:
        typer.echo(failure.output)
        typer.echo(_failure_pointer(ex, failure.stage))
        raise typer.Exit(1)


def _drift_warning(ex: Exercise, drift: StarterDrift) -> str:
    starter = _shown(ex.starter_dir)
    if drift.stamped:
        lines = [f"warning: {starter} changed since you ran start; the tests follow the new one"]
    else:
        lines = [f"warning: your copy lacks files that {starter} has; the tests may need them"]
    lines += [f"  new: {f}" for f in drift.added]
    lines += [
        f"  changed: {f}" + (" (you have not edited it)" if f in drift.untouched else "")
        for f in drift.changed
    ]
    lines += [f"  removed: {f}" for f in drift.removed]
    lines.append(
        f"copy new and unedited files from {starter}/ into {_shown(workspace_path(ex))}/, "
        f"see `git log -p -- {starter}` for the rest, "
        f"or `uv run miubais start {ex.id} --force` for a fresh copy (it replaces your code)"
    )
    return "\n".join(lines)


def _shown(path: Path) -> Path:
    try:
        return path.resolve().relative_to(Path.cwd().resolve())
    except ValueError:
        return path


def _failure_pointer(ex: Exercise, stage: Stage) -> str:
    lines = [f"stage {stage.id} failed: {stage.title}", f"tests: {_shown(ex.dir / stage.tests)}"]
    if stage.lesson:
        lines.append(f"read first: lesson {stage.lesson} ({SITE_URL}/{stage.lesson}/)")
    lines.append(f"the stage is described under Stages in {_shown(ex.readme_path)}")
    return "\n".join(lines)


@app.command("record-fixtures")
def record_fixtures_command(
    exercise_id: str = typer.Argument(..., metavar="EXERCISE_ID"),
    course: Path | None = CourseOption,
) -> None:
    ex = _find(exercise_id, course)
    if ex is None:
        typer.echo(f"unknown exercise: {exercise_id}")
        raise typer.Exit(1)
    try:
        written = record_fixtures(ex)
    except (RequirementError, RecordingRejected) as err:
        typer.echo(str(err))
        raise typer.Exit(1) from err
    for path in written:
        typer.echo(str(path))


@app.command()
def progress(course: Path | None = CourseOption) -> None:
    saved = load_progress(miubais_home())
    table = Table("exercise", "stage", "status")
    for ex in list_exercises(course or course_dir()):
        records = saved.exercises.get(ex.id, {})
        for s in ex.stages:
            rec = records.get(s.id)
            table.add_row(ex.id, s.id, rec.status if rec else "-")
    Console().print(table)


@app.command()
def doctor() -> None:
    table = Table("name", "ok", "detail")
    for name, ok, detail in doctor_report():
        table.add_row(name, "ok" if ok else "--", detail)
    Console().print(table)
    typer.echo(
        "python and uv are required; anything else missing only skips the stages that use it"
    )


@app.command()
def selftest(
    exercise_id: str | None = typer.Argument(None, metavar="[EXERCISE_ID]"),
    course: Path | None = CourseOption,
    live: bool = typer.Option(False, "--live", help="Run live stages for real."),
) -> None:
    exercises = list_exercises(course or course_dir())
    if exercise_id is not None:
        exercises = [e for e in exercises if e.id == exercise_id]
        if not exercises:
            typer.echo(f"unknown exercise: {exercise_id}")
            raise typer.Exit(1)
    failed = False
    for ex in exercises:
        try:
            r = selftest_exercise(ex, runner=SubprocessRunner(), probe=SystemProbe(), live=live)
        except ExerciseError as err:
            typer.echo(str(err))
            raise typer.Exit(1) from err
        ref = "ok" if r.reference_ok else "FAIL"
        starter = "ok" if r.starter_fails_first else "FAIL"
        offline = "".join(f", {stage} ok (offline)" for stage in r.offline_live)
        typer.echo(
            f"{r.exercise_id}: reference {ref}, starter fails first {starter}, "
            f"{r.leak_terms_written} leak terms{offline}"
        )
        if not r.ok:
            failed = True
            typer.echo(r.details)
    if failed:
        raise typer.Exit(1)


@app.command()
def hint(
    exercise_id: str = typer.Argument(..., metavar="EXERCISE_ID"),
    course: Path | None = CourseOption,
) -> None:
    ex = _find(exercise_id, course)
    if ex is None:
        typer.echo(f"unknown exercise: {exercise_id}")
        raise typer.Exit(1)
    try:
        ctx = build_context(ex, workspace_path(ex), miubais_home())
    except HintError as err:
        typer.echo(str(err))
        raise typer.Exit(1) from err
    result = asyncio.run(generate_hint(ctx, default_client()))
    typer.echo(result.text)
    typer.echo(f"source: {result.source}")
    if result.error:
        typer.echo(f"the tutor could not reach the model: {result.error}")
        typer.echo("hints run on your Claude Code login: run `claude`, log in, then retry")


OnlyOption = typer.Option(
    None, "--only", help="with --live: generate only this case (file stem), replay the rest"
)


@app.command("tutor-eval")
def tutor_eval(
    live: bool = typer.Option(False, "--live", help="call the model and record the run"),
    only: list[str] | None = OnlyOption,
    course: Path | None = CourseOption,
) -> None:
    course_path = course or course_dir()
    if not CASES_DIR.is_dir():
        typer.echo(
            f"no tutor eval cases at {CASES_DIR}; they stay in the author's private checkout"
        )
        raise typer.Exit(1)
    cases = load_cases(CASES_DIR)
    sources = None
    if only and not live:
        typer.echo("--only needs --live")
        raise typer.Exit(1)
    try:
        if only:
            latest = RUNS_DIR / "latest.jsonl"
            hints, sources = asyncio.run(
                collect_selected(cases, set(only), default_client(), course_path, latest)
            )
        elif live:
            hints = asyncio.run(collect_hints(cases, default_client(), course_path))
        else:
            latest = RUNS_DIR / "latest.jsonl"
            if not latest.is_file():
                typer.echo(
                    f"no recorded run at {latest}; run `uv run miubais tutor-eval --live` first"
                )
                raise typer.Exit(1)
            hints = load_run(latest, cases)
        report = score_hints(cases, hints, course_path)
    except (EvalError, FileNotFoundError) as err:
        typer.echo(str(err))
        raise typer.Exit(1) from err
    typer.echo(
        f"cases={report.cases} leaks={report.leaks} "
        f"concept_hits={report.concept_hits} passed={report.passed}"
    )
    for case, h in zip(cases, hints, strict=True):
        typer.echo(
            f"{case.file}: source={h.source} model={h.model} "
            f"session={h.session_id} cost_usd={h.cost_usd:.4f}"
        )
    for failure in report.failures:
        typer.echo(failure)
    if live:
        try:
            typer.echo(f"recorded {record_run(cases, hints, RUNS_DIR, sources)}")
        except EvalError as err:
            typer.echo(str(err))
            raise typer.Exit(1) from err
    if not report.passed:
        raise typer.Exit(1)


def make_http() -> httpx.Client:
    return httpx.Client()


DryRunOption = typer.Option(False, "--dry-run", help="Print the table; write only with --out.")
DocsOption = typer.Option(None, "--docs", help="Lessons directory.")
OutOption = typer.Option(None, "--out", help="Output directory.")
NoDraftsOption = typer.Option(False, "--no-drafts", help="Skip model-written draft notes.")


async def _write_drafts(
    entries: list[LessonFreshness], out_dir: Path, today: date
) -> tuple[list[Path], int]:
    client = default_client()
    paths, failed = [], 0
    for entry in entries:
        path, ok = await write_draft(entry, client, out_dir, today)
        paths.append(path)
        failed += not ok
    return paths, failed


@app.command()
def freshen(
    dry_run: bool = DryRunOption,
    docs: Path | None = DocsOption,
    out: Path | None = OutOption,
    no_drafts: bool = NoDraftsOption,
) -> None:
    docs_dir = docs or site_docs_dir()
    use_branch = not dry_run and out is None
    try:
        if use_branch:
            ensure_clean(repo_root())
        lessons = load_lessons(docs_dir)
    except (BranchError, FrontmatterError, FileNotFoundError) as err:
        typer.echo(str(err))
        raise typer.Exit(1) from err
    today = datetime.now(UTC).date()
    root = repo_root()
    with make_http() as http:
        report = build_report(
            lessons, http=http, gh=gh_api, ignore=load_ignore(root), today=today, root=root
        )
    table = Table("lesson", "badge", "verified_on", "executed", "drift", "broken links")
    for entry in report.lessons:
        broken = sum(1 for link in entry.links if not link.ok)
        table.add_row(
            entry.slug,
            entry.badge,
            entry.verified_on.isoformat(),
            entry.executed,
            drift_summary(entry.drifts),
            str(broken),
        )
    Console(width=200).print(table)
    if dry_run and out is None:
        return
    if not use_branch:
        json_path, md_path = write_report(report, out)
        typer.echo(f"wrote {json_path} and {md_path}")
        if dry_run:
            return
        drafts, failed = _draft_all(report, out, today, no_drafts)
        typer.echo(f"{len(drafts)} drafts written to {out}; --out given, skipping git branch")
        _echo_failed(failed)
        return
    staging = Path(tempfile.mkdtemp(prefix="miubais-freshen-out-"))
    try:
        json_path, md_path = write_report(report, staging)
        drafts, failed = _draft_all(report, staging, today, no_drafts)
        files = [
            (p, Path("freshness") / p.relative_to(staging)) for p in [json_path, md_path, *drafts]
        ]
        sha = commit_on_branch(repo_root(), today, files)
    except BranchError as err:
        typer.echo(str(err))
        raise typer.Exit(1) from err
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    typer.echo(f"branch freshen/{today.isoformat()} at {sha}, {len(drafts)} drafts")
    _echo_failed(failed)


def _draft_all(
    report: FreshnessReport, out_dir: Path, today: date, no_drafts: bool
) -> tuple[list[Path], int]:
    if no_drafts:
        return [], 0
    pending = [e for e in report.lessons if needs_draft(e)]
    return asyncio.run(_write_drafts(pending, out_dir, today))


def _echo_failed(failed: int) -> None:
    if failed:
        typer.echo(f"{failed} drafts failed with a model error")


@app.command()
def serve(
    port: int = typer.Option(8787, "--port"),
    course: Path | None = CourseOption,
) -> None:
    api = create_app(
        course_dir=course or course_dir(),
        home=miubais_home(),
        workspace=workspace_dir(),
    )
    uvicorn.run(api, host="127.0.0.1", port=port, log_level="info")


DestOption = typer.Option(..., "--dest", help="Clone of the public repository.")
MAX_LISTED_REMOVALS = 20


@app.command()
def publish(
    dest: Path = DestOption,
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the plan; write nothing."),
    allow_dirty: bool = typer.Option(False, "--allow-dirty", help="Export uncommitted edits."),
) -> None:
    repo = repo_root()
    try:
        check_dest(repo, dest)
    except PublishError as err:
        typer.echo(str(err))
        raise typer.Exit(1) from err
    if not allow_dirty and is_dirty(repo):
        typer.echo("working tree is dirty; commit or pass --allow-dirty")
        raise typer.Exit(1)
    tracked = tracked_files(repo)
    if dry_run:
        plan = export_plan(repo, tracked)
        for top, count in top_level_counts(plan).items():
            typer.echo(f"{top}: {count}")
        overlay = len(overlay_paths(tracked))
        private = len(tracked) - len(select_public(tracked)) - overlay
        typer.echo(f"overlay: {overlay} files from publish/")
        typer.echo(f"private: {private} tracked files left out")
        removed = sorted(dest_files(dest) - plan.keys())
        typer.echo(f"would remove {len(removed)}")
        if len(removed) <= MAX_LISTED_REMOVALS:
            for path in removed:
                typer.echo(f"  {path}")
        _fail_on_offenders(check_paths(plan))
        _fail_on_content(repo, [source.relative_to(repo).as_posix() for source in plan.values()])
        return
    manifest_path(dest).unlink(missing_ok=True)
    report = export_tree(repo, dest, tracked)
    _fail_on_offenders(check_export(dest))
    _fail_on_content(dest, report.copied)
    write_manifest(dest, report.copied)
    typer.echo(f"copied {len(report.copied)} files, removed {len(report.removed)}")


def _fail_on_content(root: Path, paths: list[str]) -> None:
    denylist = miubais_home() / DENYLIST
    if not denylist.is_file():
        typer.echo(f"warning: no denylist at {denylist}; scanning with builtin patterns only")
    try:
        patterns = [*BUILTIN_CONTENT_PATTERNS, *load_denylist(denylist)]
    except PublishError as err:
        typer.echo(str(err))
        raise typer.Exit(1) from err
    hits = scan_content(root, paths, patterns)
    shown = denylist if denylist.is_file() else "none"
    typer.echo(f"content scan: {len(paths)} files, {len(hits)} hits, denylist {shown}")
    if hits:
        typer.echo("content scan failed:")
        for hit in hits:
            typer.echo(f"  {hit}")
        raise typer.Exit(1)


def _fail_on_offenders(offenders: list[str]) -> None:
    if offenders:
        typer.echo("export check failed:")
        for path in offenders:
            typer.echo(f"  {path}")
        raise typer.Exit(1)
