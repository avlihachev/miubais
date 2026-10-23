import shutil
import subprocess
import sys

from miubais.exercises import Exercise, ExerciseError, list_exercises
from miubais.paths import course_dir
from miubais.requirements import REQUIREMENTS, Probe, SystemProbe

Row = tuple[str, bool, str]

EXTRA_USERS = {"claude-auth": ["hint"], "node": ["local site"], "pnpm": ["local site"]}


def _tool_version(name: str) -> tuple[bool, str]:
    if shutil.which(name) is None:
        return False, "not found"
    try:
        result = subprocess.run(
            [name, "--version"], check=False, capture_output=True, text=True, timeout=5
        )
    except Exception:  # noqa: BLE001 - any probe failure means missing
        return False, "not found"
    if result.returncode != 0:
        return False, "not found"
    return True, result.stdout.strip()


def _course_exercises() -> list[Exercise]:
    try:
        return list_exercises(course_dir())
    except (FileNotFoundError, ExerciseError):
        return []


def _users(name: str, exercises: list[Exercise]) -> list[str]:
    modules = {ex.module for ex in exercises for st in ex.stages if name in st.requires}
    return [*sorted(modules), *EXTRA_USERS.get(name, [])]


def _detail(ok: bool, text: str, used_by: list[str]) -> str:
    return text if ok or not used_by else f"{text}; used by {', '.join(used_by)}"


def report(probe: Probe | None = None, exercises: list[Exercise] | None = None) -> list[Row]:
    probe = probe or SystemProbe()
    exercises = _course_exercises() if exercises is None else exercises
    py = sys.version_info
    rows: list[Row] = [("python", py >= (3, 12), f"{py.major}.{py.minor}.{py.micro}")]
    tools = ("uv", "node", "pnpm")
    for name in tools:
        ok, detail = _tool_version(name)
        rows.append((name, ok, _detail(ok, detail, _users(name, exercises))))
    for req in REQUIREMENTS:
        if req in tools:
            continue
        ok = probe.has(req)  # type: ignore[arg-type]
        rows.append(
            (req, ok, _detail(ok, "available" if ok else "missing", _users(req, exercises)))
        )
    return rows
