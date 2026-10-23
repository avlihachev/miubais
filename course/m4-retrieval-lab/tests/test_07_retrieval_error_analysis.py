import os
import re
from pathlib import Path

import pytest
import yaml
from retrieval_lab import metrics, rerank, store
from retrieval_lab.chunker import chunk, load_documents
from retrieval_lab.embed import HashEmbedder

FAILURES = ("vocabulary-gap", "chunk-boundary", "ranking", "anchor-ambiguity", "reranker-demotion")
FIXES = (
    "hybrid-weights",
    "smaller-chunks",
    "contextual-chunk-headers",
    "query-rewrite",
    "better-embedder",
)
K = 10
MIN_AGREEMENT = 0.70
MIN_PARAGRAPH_WORDS = 25
QUERY_ID = re.compile(r"^q\d{2}$")
CELL = re.compile(r"(?<!\\)\|")
WORD = re.compile(r"[A-Za-z0-9][\w'-]*")


@pytest.fixture(scope="module")
def key() -> dict[str, dict]:
    raw = yaml.safe_load((Path(__file__).parent / "KEY.yaml").read_text(encoding="utf-8"))
    return raw["failures"]


@pytest.fixture(scope="module")
def analysis() -> str:
    root = os.environ.get("MIUBAIS_WORKSPACE")
    if not root:
        pytest.fail("set MIUBAIS_WORKSPACE to your workspace (miubais check sets it for you)")
    path = Path(root) / "RETRIEVAL_ANALYSIS.md"
    if not path.is_file():
        pytest.fail(f"write {path.name} in your workspace root")
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def failed(conn, corpus_dir, golden) -> list[str]:
    embedder = HashEmbedder()
    chunks = [c for d in load_documents(corpus_dir) for c in chunk(d)]
    store.Schema.create(conn, embedder.dims)
    store.upsert(conn, chunks, embedder)
    reranker = rerank.LexicalReranker()
    missed = []
    for q in golden:
        top = rerank.pipeline(conn, embedder, reranker, q.query, top_k=K)
        if not metrics.relevant(chunks, q) & {r.chunk_id for r in top}:
            missed.append(q.id)
    return missed


def clean(cell: str) -> str:
    return cell.replace("`", "").replace("*", "").strip().lower()


def parse_rows(text: str) -> dict[str, tuple[str, str]]:
    rows = {}
    for line in text.splitlines():
        if not line.lstrip().startswith("|"):
            continue
        cells = [clean(c) for c in CELL.split(line.strip().strip("|"))]
        if len(cells) == 3 and QUERY_ID.match(cells[0]):
            rows[cells[0]] = (cells[1], cells[2])
    return rows


def mentions(text: str, kind: str) -> bool:
    spaced = kind.replace("-", "[- ]")
    return re.search(rf"(?<![\w-]){spaced}(?![\w-])", text.lower()) is not None


def explained_kinds(text: str) -> set[str]:
    found, heading = set(), ""
    for block in re.split(r"\n\s*\n", text):
        lines = [line for line in block.strip().splitlines() if line.strip()]
        if not lines or lines[0].lstrip().startswith("|"):
            continue
        if lines[0].lstrip().startswith("#"):
            heading, lines = lines[0], lines[1:]
        body = " ".join(lines)
        if len(WORD.findall(body)) < MIN_PARAGRAPH_WORDS:
            continue
        found |= {k for k in FAILURES if mentions(body, k) or mentions(heading, k)}
    return found


def agreement(rows: dict[str, tuple[str, str]], key: dict[str, dict]) -> float:
    agreed = sum(1 for qid, entry in key.items() if rows.get(qid, ("", ""))[0] in entry["failure"])
    return agreed / len(key)


def table(answers: dict[str, str], fix: str = "better-embedder") -> str:
    lines = [f"| {qid} | {failure} | {fix} |" for qid, failure in answers.items()]
    return "| query_id | failure | fix |\n|---|---|---|\n" + "\n".join(lines) + "\n"


def test_every_failed_query_has_a_row(analysis, failed):
    missing = sorted(set(failed) - set(parse_rows(analysis)))
    assert not missing, f"add a `| query_id | failure | fix |` row for {missing}"


def test_failures_and_fixes_use_the_vocabulary(analysis):
    rows = parse_rows(analysis)
    bad_failure = {qid: f for qid, (f, _) in rows.items() if f not in FAILURES}
    bad_fix = {qid: fix for qid, (_, fix) in rows.items() if fix not in FIXES}
    assert not bad_failure, f"failure must be one of {list(FAILURES)}: {bad_failure}"
    assert not bad_fix, f"fix must be one of {list(FIXES)}: {bad_fix}"


def test_failures_agree_with_the_key(analysis, key):
    share = agreement(parse_rows(analysis), key)
    assert share >= MIN_AGREEMENT, f"{share:.0%} of the failure kinds agree with the key, need 70%"


def test_one_paragraph_per_failure_kind(analysis):
    used = {failure for failure, _ in parse_rows(analysis).values() if failure in FAILURES}
    missing = sorted(used - explained_kinds(analysis))
    assert not missing, (
        f"write a paragraph of {MIN_PARAGRAPH_WORDS} words or more that names each failure kind "
        f"you used (or sits under a heading that names it): {missing}"
    )


def test_the_key_uses_the_vocabulary(key):
    for qid, entry in key.items():
        assert QUERY_ID.match(qid)
        assert entry["failure"] and set(entry["failure"]) <= set(FAILURES), qid
        assert entry["fix"] in FIXES, qid


def test_a_constant_table_is_rejected(key):
    for failure in FAILURES:
        rows = parse_rows(table(dict.fromkeys(key, failure)))
        assert agreement(rows, key) < MIN_AGREEMENT, failure


def test_a_table_for_other_queries_is_rejected(key):
    answers = {qid: entry["failure"][0] for qid, entry in key.items()}
    shifted = {f"q{int(qid[1:]) + 1:02d}": f for qid, f in answers.items()}
    assert agreement(parse_rows(table(shifted)), key) < MIN_AGREEMENT


def test_four_wrong_is_too_many(key):
    answers = {qid: entry["failure"][0] for qid, entry in key.items()}
    assert agreement(parse_rows(table(answers)), key) == 1.0
    wrong = [qid for qid, entry in key.items() if "ranking" not in entry["failure"]]
    for qid in wrong[:3]:
        answers[qid] = "ranking"
    assert agreement(parse_rows(table(answers)), key) >= MIN_AGREEMENT
    answers[wrong[3]] = "ranking"
    assert agreement(parse_rows(table(answers)), key) < MIN_AGREEMENT


def test_rows_and_paragraphs_are_read_by_shape():
    text = (
        "# Analysis\n\n| query_id | failure | fix |\n|---|---|---|\n"
        "| `q01` | **Vocabulary-gap** | better-embedder |\n| q2 | ranking | x |\n"
        "| q03 | ranking |\n\n## Vocabulary gap\n\n" + "word " * MIN_PARAGRAPH_WORDS + "\n\n"
        "A short ranking note.\n\nThe chunk-boundary case " + "word " * MIN_PARAGRAPH_WORDS + "\n"
    )
    assert parse_rows(text) == {"q01": ("vocabulary-gap", "better-embedder")}
    assert explained_kinds(text) == {"vocabulary-gap", "chunk-boundary"}
    assert not mentions("a reranker-demotion-like case", "reranker-demotion")
