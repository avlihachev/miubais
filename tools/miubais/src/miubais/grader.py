import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel

from miubais.exercises import Exercise, Stage
from miubais.paths import miubais_home, repo_root
from miubais.progress import load_progress, record, save_progress
from miubais.requirements import Probe, Requirement, missing

TIMEOUT_EXIT = 124
NO_TESTS_COLLECTED = 5
SKIP_LIVE_REASON = "MIUBAIS_SKIP_LIVE=1"
OFFLINE_ARGS = ["-m", "not live", "-p", "miubais.offline_guard"]
LIVE_REPORT_ARGS = ["-p", "miubais.live_report"]
Env = dict[str, str | None]


class Runner(Protocol):
    def run(
        self, cmd: list[str], cwd: Path, env: Env, timeout: float | None = None
    ) -> tuple[int, str]: ...


def _text(value: str | bytes | None) -> str:
    return value.decode(errors="replace") if isinstance(value, bytes) else value or ""


class SubprocessRunner:
    def run(
        self, cmd: list[str], cwd: Path, env: Env, timeout: float | None = None
    ) -> tuple[int, str]:
        merged = {k: v for k, v in {**os.environ, **env}.items() if v is not None}
        try:
            proc = subprocess.run(
                cmd,
                cwd=cwd,
                env=merged,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout,
            )
        except FileNotFoundError as err:
            return 127, f"cannot run {cmd[0]}: {err}"
        except subprocess.TimeoutExpired as err:
            partial = _text(err.stdout) + _text(err.stderr)
            return TIMEOUT_EXIT, f"{partial}\ntimed out after {timeout} s"
        return proc.returncode, proc.stdout + proc.stderr


class StageResult(BaseModel):
    stage: Stage
    status: Literal["passed", "failed", "skipped"]
    output: str = ""
    missing: list[Requirement] = []
    reason: str = ""
    cached: bool = False


class ExerciseResult(BaseModel):
    exercise: Exercise
    results: list[StageResult]

    @property
    def passed_stages(self) -> list[str]:
        return [r.stage.id for r in self.results if r.status == "passed"]

    @property
    def first_failure(self) -> StageResult | None:
        return next((r for r in self.results if r.status == "failed"), None)


def run_stage(
    ex: Exercise,
    stage: Stage,
    workspace_path: Path,
    *,
    probe: Probe | None = None,
    runner: Runner | None = None,
    offline: bool = False,
    live: bool = False,
) -> StageResult:
    lacking = [] if stage.live and offline else missing(stage.requires, probe)
    if lacking:
        return StageResult(stage=stage, status="skipped", missing=lacking)
    runner = runner or SubprocessRunner()
    cmd = [
        "uv",
        "run",
        "--frozen",
        "pytest",
        str(ex.dir / stage.tests),
        "-q",
        "--tb=short",
        "-p",
        "no:cacheprovider",
        "-x",
        *(OFFLINE_ARGS if offline else []),
    ]
    env: Env = {
        "MIUBAIS_WORKSPACE": str(workspace_path),
        "PYTHONPATH": str(workspace_path / "src"),
    }
    if offline and stage.live:
        env["MIUBAIS_SKIP_LIVE"] = "1"
    if live and stage.live:
        env["MIUBAIS_SKIP_LIVE"] = None
    skip_live = (
        stage.live and env.get("MIUBAIS_SKIP_LIVE", os.environ.get("MIUBAIS_SKIP_LIVE")) == "1"
    )
    report_live = stage.live and not offline and not skip_live
    with tempfile.TemporaryDirectory(prefix="miubais-live-") as scratch:
        live_report = Path(scratch) / "live.json"
        if report_live:
            cmd += LIVE_REPORT_ARGS
            env["MIUBAIS_LIVE_REPORT"] = str(live_report)
        code, output = runner.run(cmd, repo_root(), env, stage.timeout)
        skipped_live = _all_live_skipped(live_report) if report_live and code == 0 else None
    # a live stage may have no offline tests left once -m "not live" deselects the live ones
    passed = code == 0 or (skip_live and code == NO_TESTS_COLLECTED)
    if passed and skip_live:
        return StageResult(stage=stage, status="skipped", output=output, reason=SKIP_LIVE_REASON)
    if skipped_live:
        return StageResult(stage=stage, status="skipped", output=output, reason=skipped_live)
    return StageResult(stage=stage, status="passed" if passed else "failed", output=output)


def _all_live_skipped(path: Path) -> str | None:
    try:
        summary = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    skipped = summary.get("skipped") or []
    if summary.get("passed") != 0 or not skipped:
        return None
    return skipped[0] or "live test skipped"


def _save_output(home: Path, ex: Exercise, result: StageResult) -> str:
    path = home / "output" / ex.id / f"{result.stage.id}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(result.output)
    return str(path)


def run_exercise(
    ex: Exercise,
    workspace_path: Path,
    *,
    stop_on_fail: bool = True,
    only: str | None = None,
    probe: Probe | None = None,
    runner: Runner | None = None,
    home: Path | None = None,
    offline: bool = False,
    live: bool = False,
    reuse_live_passes: bool = False,
) -> ExerciseResult:
    home = home if home is not None else miubais_home()
    progress = load_progress(home)
    results: list[StageResult] = []
    for stage in ex.stages:
        if only is not None and stage.id != only:
            continue
        previous = progress.exercises.get(ex.id, {}).get(stage.id)
        if reuse_live_passes and stage.live and previous and previous.status == "passed":
            results.append(StageResult(stage=stage, status="passed", cached=True))
            continue
        result = run_stage(
            ex, stage, workspace_path, probe=probe, runner=runner, offline=offline, live=live
        )
        results.append(result)
        output_path = _save_output(home, ex, result) if result.status == "failed" else None
        # a skipped run proves nothing, so it must not erase an earlier real pass
        if not (result.status == "skipped" and previous and previous.status == "passed"):
            record(progress, ex.id, stage.id, result.status, output_path)
            save_progress(progress, home, workspace_path.parent / ".progress.json")
        if result.status == "failed" and stop_on_fail:
            break
    return ExerciseResult(exercise=ex, results=results)
