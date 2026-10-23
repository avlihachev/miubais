import os
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from pydantic import BaseModel

from miubais.exercises import Exercise, ExerciseError, list_exercises
from miubais.grader import Runner, StageResult, run_exercise
from miubais.requirements import Probe
from miubais.tutor.leak import exercise_leak_terms, write_leak_terms


class SelftestResult(BaseModel):
    exercise_id: str
    reference_ok: bool
    starter_fails_first: bool
    leak_terms_written: int
    details: str = ""
    offline_live: list[str] = []

    @property
    def ok(self) -> bool:
        return self.reference_ok and self.starter_fails_first


def _grade(ex: Exercise, source: Path, *, runner: Runner | None, probe: Probe | None, live: bool):
    root = Path(tempfile.mkdtemp(prefix="miubais-selftest-"))
    try:
        workspace = root / "ws"
        shutil.copytree(source, workspace)
        env = {"MIUBAIS_HOME": str(root / "home")}
        with mock.patch.dict(os.environ, env):
            return run_exercise(
                ex,
                workspace,
                stop_on_fail=False,
                probe=probe,
                runner=runner,
                offline=not live,
                live=live,
            )
    finally:
        shutil.rmtree(root, ignore_errors=True)


def selftest_exercise(
    ex: Exercise,
    *,
    runner: Runner | None = None,
    probe: Probe | None = None,
    live: bool = False,
) -> SelftestResult:
    if not ex.has_reference:
        raise ExerciseError(f"{ex.id}: no reference/ solution; selftest needs the private checkout")
    offline = not live
    reference = _grade(ex, ex.reference_dir, runner=runner, probe=probe, live=live)
    failing = [
        r
        for r in reference.results
        if r.status == "failed"
        or (r.status == "skipped" and (r.missing if not r.stage.live else live))
    ]
    reference_ok = not failing
    offline_live = [
        r.stage.id
        for r in reference.results
        if offline and r.stage.live and r.status == "skipped" and r.reason
    ]
    starter = _grade(ex, ex.starter_dir, runner=runner, probe=probe, live=live)
    starter_fails_first = bool(starter.results) and starter.results[0].status == "failed"
    terms = exercise_leak_terms(ex)
    write_leak_terms(ex, terms)
    details = "\n".join(f"{r.stage.id}: {_failure_text(r)}" for r in failing)
    return SelftestResult(
        exercise_id=ex.id,
        reference_ok=reference_ok,
        starter_fails_first=starter_fails_first,
        leak_terms_written=len(terms),
        details=details,
        offline_live=offline_live,
    )


def _failure_text(result: StageResult) -> str:
    if result.status != "skipped":
        return result.output
    if result.stage.live or not result.missing:
        return _skip_reason(result)
    return "; ".join(f"needs {req}: install it to grade this module" for req in result.missing)


def _skip_reason(result: StageResult) -> str:
    return f"skipped ({result.reason or 'needs ' + ', '.join(result.missing)})"


def selftest_all(
    course_dir: Path,
    *,
    runner: Runner | None = None,
    probe: Probe | None = None,
    live: bool = False,
) -> list[SelftestResult]:
    return [
        selftest_exercise(ex, runner=runner, probe=probe, live=live)
        for ex in list_exercises(course_dir)
    ]
