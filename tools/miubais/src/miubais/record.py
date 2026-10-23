import importlib.util
import json
import shutil
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import yaml

from miubais.exercises import Exercise, load_exercise
from miubais.grader import Runner, run_exercise
from miubais.requirements import Probe, missing


class RequirementError(Exception):
    pass


class RecordingRejected(Exception):
    pass


class _NoLiveStages:
    def has(self, req) -> bool:
        return False


def _load_record(path: Path) -> Callable:
    spec = importlib.util.spec_from_file_location("miubais_fixture_record", path)
    if spec is None or spec.loader is None:
        raise RequirementError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.record


def _default_client():
    import anthropic

    return anthropic.Anthropic()


def _write(fixtures_dir: Path, recorded: dict[str, dict]) -> list[Path]:
    written = []
    for name, fixture in recorded.items():
        path = fixtures_dir / f"{name}.json"
        path.write_text(json.dumps(fixture, indent=2) + "\n")
        written.append(path)
    return written


def _check_against_reference(
    ex: Exercise, recorded: dict[str, dict], runner: Runner | None
) -> list[str]:
    staging = Path(tempfile.mkdtemp(prefix="miubais-record-"))
    try:
        trial_dir = staging / ex.dir.name
        shutil.copytree(ex.dir, trial_dir, ignore=shutil.ignore_patterns("__pycache__"))
        _write(trial_dir / "fixtures", recorded)
        trial = load_exercise(trial_dir)
        workspace = staging / "ws"
        shutil.copytree(trial.reference_dir, workspace)
        result = run_exercise(
            trial,
            workspace,
            stop_on_fail=False,
            probe=_NoLiveStages(),
            runner=runner,
            home=staging / "home",
        )
        return [r.stage.id for r in result.results if r.status == "failed"]
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _update_manifest(fixtures_dir: Path, recorded: dict[str, dict], written: list[Path]) -> None:
    manifest_path = fixtures_dir / "MANIFEST.yaml"
    manifest = yaml.safe_load(manifest_path.read_text()) or {}
    entries = {f["name"]: f for f in manifest.get("files", [])}
    today = datetime.now(UTC).date().isoformat()
    for path in written:
        entry = entries.setdefault(path.name, {"name": path.name})
        body = recorded[path.stem].get("body") or {}
        entry.update(recorded="live", recorded_on=today)
        if body.get("model"):
            entry["model"] = body["model"]
    manifest["files"] = list(entries.values())
    all_live = all(f.get("recorded") == "live" for f in manifest["files"])
    manifest["recorded"] = "live" if all_live else "mixed"
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False, width=200))


def record_fixtures(
    ex: Exercise,
    *,
    probe: Probe | None = None,
    record_fn: Callable[[object], dict[str, dict]] | None = None,
    client_factory: Callable[[], object] | None = None,
    runner: Runner | None = None,
) -> list[Path]:
    if not ex.has_reference:
        raise RequirementError(
            f"{ex.id}: no reference/ solution; record-fixtures needs the private checkout"
        )
    if missing(["api-key"], probe):
        raise RequirementError("record-fixtures needs: api-key")
    fixtures_dir = ex.dir / "fixtures"
    record = record_fn or _load_record(fixtures_dir / "record.py")
    recorded = record((client_factory or _default_client)())
    failed = _check_against_reference(ex, recorded, runner)
    if failed:
        raise RecordingRejected(
            f"recorded fixtures fail stage {', '.join(failed)} against the reference; "
            "kept the original fixtures"
        )
    written = _write(fixtures_dir, recorded)
    _update_manifest(fixtures_dir, recorded, written)
    return written
