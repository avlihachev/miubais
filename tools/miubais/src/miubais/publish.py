import os
import re
import shutil
import subprocess
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

PRIVATE_PATTERNS: tuple[str, ...] = (
    "course/*/reference/**",
    "book/**",
    "docs/**",
    "research/**",
    "site/src/pages/book.astro",
    "README.md",
    "publish/**",
    "tools/miubais/src/miubais/tutor/evals/cases/**",
    "tools/miubais/src/miubais/tutor/evals/runs/**",
    "freshness/report-*.md",
)
PUBLIC_TOP: frozenset[str] = frozenset(
    {
        "course",
        "fixtures",
        "site",
        "tools",
        "freshness",
        "scripts",
        "workspace",
        "pyproject.toml",
        "uv.lock",
        ".python-version",
        ".gitignore",
        ".freshignore",
        "README.md",
        "LICENSE",
        "LICENSE-CONTENT",
        ".github",
    }
)
OVERLAY = "publish/"
GIT_DIR = ".git"
MANIFEST = "publish-manifest"
DENYLIST = "publish-denylist.txt"
BUILTIN_CONTENT_PATTERNS: tuple[tuple[str, str], ...] = (
    ("cyrillic", r"[\u0400-\u04ff]{3,}"),
    ("home-path", r"/Users/(?!x/)[A-Za-z]+|/home/(?!dev\b)[A-Za-z]+"),
    ("anthropic-key", r"sk-ant-(?!api03-(?:fake|Zx9fake|EXAMPLE|Q{3}))[A-Za-z0-9_-]{8,}"),
    ("github-token", r"gh[po]_(?!x\b|fake|FAKE|0{10})[A-Za-z0-9]{10,}"),
    ("author-email", r"aleksandr\.likhachev@|lihachev[@]"),
)
SCAN_SKIP: frozenset[str] = frozenset({"site/pnpm-lock.yaml", "uv.lock"})
BINARY_PROBE = 8192


def _pattern_regex(pattern: str) -> re.Pattern[str]:
    parts = re.split(r"(\*\*|\*)", pattern)
    body = "".join(
        ".*" if part == "**" else "[^/]*" if part == "*" else re.escape(part) for part in parts
    )
    return re.compile(body)


PRIVATE_REGEXES = tuple(_pattern_regex(p) for p in PRIVATE_PATTERNS)


class PublishError(Exception):
    pass


@dataclass
class ExportReport:
    copied: list[str]
    removed: list[str]


def is_private(path: str) -> bool:
    return any(regex.fullmatch(path) for regex in PRIVATE_REGEXES)


def select_public(tracked: Iterable[str]) -> list[str]:
    return sorted(path for path in tracked if not is_private(path))


def overlay_paths(tracked: Iterable[str]) -> dict[str, str]:
    return {path: path[len(OVERLAY) :] for path in sorted(tracked) if path.startswith(OVERLAY)}


def export_plan(repo: Path, tracked: Iterable[str]) -> dict[str, Path]:
    tracked = list(tracked)
    plan = {path: repo / path for path in select_public(tracked)}
    plan.update({target: repo / source for source, target in overlay_paths(tracked).items()})
    # a tracked file deleted in the working tree (--allow-dirty) is left out, not a crash
    return {path: plan[path] for path in sorted(plan) if os.path.lexists(plan[path])}


def tree_files(root: Path) -> set[str]:
    if not root.is_dir():
        return set()
    found: set[str] = set()
    for child in root.iterdir():
        if child.name == GIT_DIR:
            continue
        paths = [child] if not child.is_dir() or child.is_symlink() else child.rglob("*")
        found.update(p.relative_to(root).as_posix() for p in paths if p.is_symlink() or p.is_file())
    return found


def dest_files(dest: Path) -> set[str]:
    if (dest / GIT_DIR).exists():
        # ignored .venv and node_modules in a clone are not part of the export
        listed = subprocess.run(
            ["git", "-C", str(dest), f"--git-dir={GIT_DIR}", "ls-files", "-z"],
            check=False,
            capture_output=True,
            text=True,
        )
        if listed.returncode == 0:
            return {path for path in listed.stdout.split("\0") if path}
    return tree_files(dest)


def _clear(dest: Path) -> None:
    for child in dest.iterdir():
        if child.name == GIT_DIR:
            continue
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()


def check_dest(repo: Path, dest: Path) -> None:
    repo, dest = repo.resolve(), dest.resolve()
    if repo.is_relative_to(dest) or dest.is_relative_to(repo):
        raise PublishError(f"refusing to export into {dest}: it overlaps the repository at {repo}")
    if not (dest / GIT_DIR).exists() and (dest.is_file() or dest.is_dir() and any(dest.iterdir())):
        raise PublishError(f"refusing to export into {dest}: it is not empty and not a git clone")


def export_tree(repo: Path, dest: Path, tracked: list[str]) -> ExportReport:
    check_dest(repo, dest)
    before = dest_files(dest)
    plan = export_plan(repo, tracked)
    dest.mkdir(parents=True, exist_ok=True)
    _clear(dest)
    for path, source in plan.items():
        target = dest / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target, follow_symlinks=False)
    return ExportReport(copied=list(plan), removed=sorted(before - plan.keys()))


def check_paths(paths: Iterable[str]) -> list[str]:
    files = set(paths)
    offenders = {path for path in files if is_private(path) and path != "README.md"}
    offenders.update(top for path in files if (top := path.split("/", 1)[0]) not in PUBLIC_TOP)
    for path in files:
        parts = path.split("/")
        if len(parts) == 3 and parts[0] == "course" and parts[2] == "stages.yaml":
            terms = f"course/{parts[1]}/tests/.leak-terms"
            if terms not in files:
                offenders.add(terms)
    return sorted(offenders)


def check_export(dest: Path) -> list[str]:
    offenders = set(check_paths(tree_files(dest)))
    offenders.update(
        child.name
        for child in dest.iterdir()
        if child.name != GIT_DIR and child.name not in PUBLIC_TOP
    )
    return sorted(offenders)


def top_level_counts(paths: Iterable[str]) -> dict[str, int]:
    return dict(sorted(Counter(path.split("/", 1)[0] for path in paths).items()))


def manifest_path(dest: Path) -> Path:
    return dest / GIT_DIR / MANIFEST


def write_manifest(dest: Path, copied: list[str]) -> Path:
    path = manifest_path(dest)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{p}\n" for p in copied))
    return path


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout


def is_dirty(repo: Path) -> bool:
    return bool(_git(repo, "status", "--porcelain", "--untracked-files=no").strip())


def tracked_files(repo: Path) -> list[str]:
    return [path for path in _git(repo, "ls-files", "-z").split("\0") if path]


def load_denylist(path: Path) -> list[tuple[str, str]]:
    if not path.is_file():
        return []
    patterns: list[tuple[str, str]] = []
    for line_no, line in enumerate(path.read_text().splitlines(), start=1):
        term = line.strip()
        if not term or term.startswith("#"):
            continue
        try:
            re.compile(term)
        except re.error as err:
            raise PublishError(f"{path}:{line_no}: invalid pattern: {err}") from err
        patterns.append((f"deny:{line_no}", f"(?i){term}"))
    return patterns


def scan_content(
    dest: Path, paths: Iterable[str], patterns: Iterable[tuple[str, str]]
) -> list[str]:
    compiled = [(name, re.compile(pattern)) for name, pattern in patterns]
    hits: list[str] = []
    for path in sorted(paths):
        file = dest / path
        if path in SCAN_SKIP or file.is_symlink() or not file.is_file():
            continue
        data = file.read_bytes()
        if b"\0" in data[:BINARY_PROBE]:
            continue
        for line_no, line in enumerate(data.decode(errors="replace").splitlines(), start=1):
            hits.extend(
                f"{path}:{line_no}: {name}" for name, regex in compiled if regex.search(line)
            )
    return hits
