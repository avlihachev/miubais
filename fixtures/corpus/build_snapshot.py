"""Copy the frozen course snapshot into fixtures/corpus/docs and write MANIFEST.md."""

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
MODULES = ("m0", "m1", "m2", "m3", "m5", "m7")
INTERVIEW_MODULES = ("m0", "m1", "m2", "m3", "m5")
SNAPSHOT = "course snapshot 2026-10-17"
INTERVIEW_SNAPSHOT = "course snapshot 2026-10-23"
STORIES = (
    ("gift-of-the-magi.txt", "Project Gutenberg eBook #7256"),
    ("yellow-wallpaper.txt", "Project Gutenberg eBook #1952"),
    ("tell-tale-heart.txt", "Project Gutenberg eBook #2148 (extract)"),
)


def sources(root: Path) -> list[tuple[str, Path, str]]:
    pages = root / "site/src/content/docs"
    lessons = [
        (f"{module}-{path.stem}", path, SNAPSHOT)
        for module in MODULES
        for path in sorted((pages / module).glob("0[1-4]-*.md*"))
    ]
    interviews = [
        (
            f"{module}-07-interview-angle",
            pages / module / "07-interview-angle.md",
            INTERVIEW_SNAPSHOT,
        )
        for module in INTERVIEW_MODULES
    ]
    return lessons + interviews


def strip_frontmatter(text: str) -> str:
    if not text.startswith("---\n"):
        return text.lstrip("\n")
    end = text.index("\n---\n", 4)
    header, body = text[4:end], text[end + 5 :].lstrip("\n")
    if re.match(r"# ", body):
        return body
    match = re.search(r"^title:\s*(.+?)\s*$", header, re.MULTILINE)
    title = match.group(1).strip("\"'") if match else ""
    return f"# {title}\n\n{body}"


def build(root: Path, out: Path) -> list[str]:
    docs = out / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    for stale in docs.glob("*.md"):
        stale.unlink()
    rows = []
    for doc_id, path, snapshot in sources(root):
        body = strip_frontmatter(path.read_text(encoding="utf-8")).rstrip("\n") + "\n"
        (docs / f"{doc_id}.md").write_text(body, encoding="utf-8")
        rows.append(f"| docs/{doc_id}.md | {path.relative_to(root).as_posix()} | {snapshot} |")
    rows += [f"| stories/{name} | {origin} | public domain |" for name, origin in STORIES]
    manifest = "\n".join(
        [
            "# MANIFEST",
            "",
            f"provenance: {SNAPSHOT} and {INTERVIEW_SNAPSHOT} (docs), Project Gutenberg (stories)",
            "as_of: 2026-10-23",
            "",
            "`docs/` is written by `build_snapshot.py`; `stories/` is extracted by hand (see `README.md`).",
            "",
            "| file | source | provenance |",
            "| --- | --- | --- |",
            *rows,
            "",
        ]
    )
    (out / "MANIFEST.md").write_text(manifest, encoding="utf-8")
    return [doc_id for doc_id, _, _ in sources(root)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, default=HERE)
    args = parser.parse_args()
    print(f"wrote {len(build(args.root, args.out))} documents to {args.out / 'docs'}")


if __name__ == "__main__":
    main()
