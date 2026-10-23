import os
from pathlib import Path


def repo_root() -> Path:
    start = Path.cwd().resolve()
    for directory in (start, *start.parents):
        pyproject = directory / "pyproject.toml"
        if pyproject.is_file() and "[tool.uv.workspace]" in pyproject.read_text():
            return directory
    raise FileNotFoundError(f"no uv workspace root above {start}")


def miubais_home() -> Path:
    override = os.environ.get("MIUBAIS_HOME")
    return Path(override) if override else Path.home() / ".miubais"


def workspace_dir() -> Path:
    return repo_root() / "workspace"


def course_dir() -> Path:
    return repo_root() / "course"


def site_docs_dir() -> Path:
    return repo_root() / "site" / "src" / "content" / "docs"
