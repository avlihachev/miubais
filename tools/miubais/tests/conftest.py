import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def no_inherited_skip_live(monkeypatch):
    monkeypatch.delenv("MIUBAIS_SKIP_LIVE", raising=False)


@pytest.fixture
def tmp_repo(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "miubais-root"\n\n[tool.uv.workspace]\nmembers = []\n'
    )
    (tmp_path / "course").mkdir()
    (tmp_path / "workspace").mkdir()
    (tmp_path / "site" / "src" / "content" / "docs").mkdir(parents=True)
    monkeypatch.setenv("MIUBAIS_HOME", str(tmp_path / "home"))
    return tmp_path


@pytest.fixture
def fixture_course():
    return Path(__file__).parent / "fixtures" / "course"


@pytest.fixture
def sample_ex(fixture_course):
    from miubais.exercises import load_exercise

    return load_exercise(fixture_course / "x-sample")


@pytest.fixture
def started_ws(sample_ex, tmp_repo):
    from miubais.workspace import start_exercise

    workspace = tmp_repo / "workspace"
    return start_exercise(sample_ex, workspace=workspace)


@pytest.fixture
def fixture_course_cli(tmp_repo, fixture_course, monkeypatch):
    monkeypatch.chdir(tmp_repo)
    monkeypatch.setenv("MIUBAIS_COURSE", str(fixture_course))
    return tmp_repo


class FakeRunner:
    def __init__(self, outcomes: dict[str, tuple[int, str]]):
        self.outcomes = outcomes
        self.commands: list[list[str]] = []
        self.timeouts: list[float | None] = []
        self.envs: list[dict] = []

    def run(self, cmd, cwd, env, timeout=None):
        self.commands.append(cmd)
        self.timeouts.append(timeout)
        self.envs.append(env)
        name = next(Path(c).name for c in cmd if c.endswith(".py"))
        return self.outcomes.get(name, (0, ""))


class NoProbe:
    def has(self, req):
        return False


class AllProbe:
    def has(self, req):
        return True


def pytest_collection_modifyitems(config, items):
    from miubais.model import claude_available

    if os.environ.get("MIUBAIS_SKIP_LIVE") == "1":
        skip = pytest.mark.skip(reason="MIUBAIS_SKIP_LIVE=1")
    elif claude_available():
        return
    else:
        skip = pytest.mark.skip(reason="needs claude auth")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def fixture_docs():
    return Path(__file__).parent / "fixtures" / "docs"


@pytest.fixture
def tmp_git_repo(tmp_repo):
    import subprocess

    def git(*args):
        subprocess.run(["git", *args], cwd=tmp_repo, check=True, capture_output=True)

    (tmp_repo / "site" / "src" / "content" / "docs" / ".keep").write_text("")
    (tmp_repo / "freshness").mkdir()
    (tmp_repo / "freshness" / ".keep").write_text("")
    git("init", "-b", "main")
    git("config", "user.name", "t")
    git("config", "user.email", "t@example.com")
    git("add", "-A")
    git("commit", "-m", "init")
    return tmp_repo
