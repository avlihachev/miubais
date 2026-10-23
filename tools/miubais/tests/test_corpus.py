import os
import re
import subprocess
import sys
from collections import Counter

import pytest
import yaml
from miubais.paths import repo_root

CORPUS = repo_root() / "fixtures" / "corpus"
STORIES = {"gift-of-the-magi", "yellow-wallpaper", "tell-tale-heart"}
KINDS = {"factual", "conceptual", "lexical"}


def documents() -> dict[str, str]:
    paths = sorted(CORPUS.glob("docs/*.md")) + sorted(CORPUS.glob("stories/*.txt"))
    return {path.stem: path.read_text(encoding="utf-8") for path in paths}


def golden() -> list[dict]:
    return yaml.safe_load((CORPUS / "golden.yaml").read_text(encoding="utf-8"))["queries"]


def norm(text: str) -> str:
    return " ".join(text.split()).casefold()


@pytest.mark.skipif(
    os.environ.get("MIUBAIS_REFRESH_CORPUS") != "1",
    reason="rebuilds from live lessons; set MIUBAIS_REFRESH_CORPUS=1 when refreshing the snapshot",
)
def test_snapshot_is_reproducible(tmp_path):
    subprocess.run(
        [sys.executable, str(CORPUS / "build_snapshot.py"), "--out", str(tmp_path)],
        check=True,
        capture_output=True,
    )
    built = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*") if p.is_file())
    committed = sorted(p.relative_to(CORPUS) for p in CORPUS.glob("docs/*.md"))
    assert built == sorted([*committed, CORPUS.joinpath("MANIFEST.md").relative_to(CORPUS)])
    for rel in built:
        assert (tmp_path / rel).read_bytes() == (CORPUS / rel).read_bytes(), rel


def test_document_count_and_split():
    docs = documents()
    assert len(docs) == 32
    assert STORIES <= set(docs)
    assert sum(1 for d in docs if d.endswith("-07-interview-angle")) == 5
    for module in ("m0", "m1", "m2", "m3", "m5", "m7"):
        assert sum(1 for d in docs if re.match(rf"{module}-0[1-4]-", d)) == 4, module


def test_no_frontmatter_and_every_doc_has_a_title():
    for path in sorted(CORPUS.glob("docs/*.md")):
        text = path.read_text(encoding="utf-8")
        assert not text.startswith("---"), path.name
        assert text.startswith("# "), path.name
        assert not re.search(r"^verified_on:", text, re.MULTILINE), path.name


def test_manifest_lists_every_file():
    manifest = (CORPUS / "MANIFEST.md").read_text(encoding="utf-8")
    assert "course snapshot 2026-10-17" in manifest
    for path in sorted(CORPUS.glob("docs/*.md")) + sorted(CORPUS.glob("stories/*.txt")):
        assert f"| {path.relative_to(CORPUS).as_posix()} |" in manifest, path.name


def test_licenses_name_three_ebooks():
    licenses = (CORPUS / "LICENSES.md").read_text(encoding="utf-8")
    for number in ("#7256", "#1952", "#2148"):
        assert number in licenses
    assert "This eBook is for the use of anyone anywhere" in licenses
    for text in (CORPUS / "stories").glob("*.txt"):
        assert "gutenberg" not in text.read_text(encoding="utf-8").casefold(), text.name


def test_golden_shape():
    queries = golden()
    assert [q["id"] for q in queries] == [f"q{n:02d}" for n in range(1, 49)]
    for q in queries:
        assert set(q) == {"id", "query", "doc_id", "anchor", "kind"}, q["id"]
        assert q["kind"] in KINDS, q["id"]
        assert 6 <= len(q["anchor"].split()) <= 20, q["id"]


def test_golden_split_and_kinds():
    queries = golden()
    on_stories = [q for q in queries if q["doc_id"] in STORIES]
    assert len(queries) - len(on_stories) == 36
    assert len(on_stories) == 12
    counts = Counter(q["kind"] for q in queries)
    assert all(counts[kind] >= 10 for kind in KINDS), counts


def test_every_anchor_occurs_exactly_once_in_its_document():
    docs = {doc_id: norm(text) for doc_id, text in documents().items()}
    for q in golden():
        assert q["doc_id"] in docs, q["id"]
        assert docs[q["doc_id"]].count(norm(q["anchor"])) == 1, q["id"]


def test_no_two_queries_share_an_anchor():
    anchors = Counter(norm(q["anchor"]) for q in golden())
    assert max(anchors.values()) == 1
