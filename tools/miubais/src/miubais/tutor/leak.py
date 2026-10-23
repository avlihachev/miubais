import ast
import re
from importlib.resources import files
from pathlib import Path

from miubais.exercises import Exercise

MIN_IDENTIFIER = 4
MIN_LITERAL = 8
MIN_FRAGMENT = 12
MAX_COMMON_WORDS = 4
PUBLIC_SUFFIXES = {".py", ".md", ".toml", ".txt", ".json", ".jsonl", ".yaml", ".yml"}
IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def stoplist() -> set[str]:
    text = files("miubais.tutor").joinpath("stoplist.txt").read_text()
    return {line.strip().lower() for line in text.splitlines() if line.strip()}


def _python_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root] if root.suffix == ".py" else []
    return sorted(root.rglob("*.py")) if root.is_dir() else []


def _collect(*roots: Path) -> set[str]:
    found: set[str] = set()
    for path in (p for root in roots for p in _python_files(root)):
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                found.add(node.name)
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                found.add(node.id)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                found.update(_literal_terms(node.value))
    return {t for t in found if len(t) >= (MIN_IDENTIFIER if t.isidentifier() else MIN_LITERAL)}


def _literal_terms(value: str) -> list[str]:
    if "\n" not in value.strip():
        return [value] if any(c.isalpha() for c in value) else []
    lines = (line.strip() for line in value.splitlines())
    return [line for line in lines if len(line) >= MIN_FRAGMENT and any(c.isalpha() for c in line)]


def _common_words_only(term: str, stop: set[str]) -> bool:
    words = [w.strip(".,:;!?()[]{}'\"`").lower() for w in term.split()]
    return len(words) <= MAX_COMMON_WORDS and all(w in stop for w in words if w)


def _plain_text(*roots: Path) -> str:
    chunks = []
    for root in roots:
        paths = [root] if root.is_file() else sorted(root.rglob("*")) if root.is_dir() else []
        for path in paths:
            if path.is_file() and path.suffix in PUBLIC_SUFFIXES:
                chunks.append(path.read_text(errors="ignore"))
    return "\n".join(chunks)


def contains(text: str, term: str) -> bool:
    if term.isidentifier():
        return re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text) is not None
    return term.lower() in text.lower()


def leak_terms(reference_dir: Path, *public: Path, ignore: set[str] = frozenset()) -> set[str]:
    text = _plain_text(*public)
    stop = stoplist()
    candidates = _collect(reference_dir) - _collect(*public)
    return {
        t
        for t in candidates
        if t.strip() not in ignore
        and t.lower() not in stop
        and (t.isidentifier() or not _common_words_only(t, stop))
        and not contains(text, t)
    }


def public_paths(ex: Exercise) -> list[Path]:
    return [ex.starter_dir, ex.tests_dir, ex.readme_path, ex.dir / "fixtures"]


def leak_ignore(ex: Exercise) -> set[str]:
    path = ex.reference_dir / ".leak-ignore"
    if not path.is_file():
        return set()
    return {line.strip() for line in path.read_text().splitlines() if line.strip()}


def exercise_leak_terms(ex: Exercise) -> set[str]:
    return leak_terms(ex.reference_dir, *public_paths(ex), ignore=leak_ignore(ex))


def write_leak_terms(ex: Exercise, terms: set[str]) -> Path:
    path = ex.leak_terms_path
    path.write_text("".join(f"{t}\n" for t in sorted(terms)))
    return path


def learner_identifiers(diff: str) -> set[str]:
    added = (
        line[1:]
        for line in diff.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )
    return {m.group() for line in added for m in IDENTIFIER.finditer(line)}


def find_leaks(text: str, terms: set[str]) -> list[str]:
    return sorted(t for t in terms if contains(text, t))
