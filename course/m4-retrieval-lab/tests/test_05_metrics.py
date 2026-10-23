import re

import pytest
from retrieval_lab import hybrid, metrics, rerank, store
from retrieval_lab.chunker import chunk, load_documents
from retrieval_lab.embed import HashEmbedder
from retrieval_lab.types import Chunk, GoldenQuery

PINNED = {"recall": 0.729, "precision": 0.077, "mrr": 0.536, "ndcg": 0.583}
FLOORS = {"recall": 0.70, "mrr": 0.50, "ndcg": 0.55}
PINNED_HYBRID = {"recall": 0.656, "mrr": 0.406, "ndcg": 0.468}
PINNED_RECALL_BY_KIND = {"lexical": 1.0, "factual": 0.938, "conceptual": 0.25}
RECALL_AT_50 = 0.792
FAILED = ["q01", "q07", "q08", "q14", "q17", "q24", "q29", "q31", "q35", "q37", "q39", "q42", "q44"]
TOLERANCE = 0.02


def piece(doc_id: str, index: int, text: str) -> Chunk:
    return Chunk(doc_id, f"{doc_id}#{index:03d}", 0, len(text), "", text)


@pytest.fixture(scope="module")
def indexed(conn, corpus_dir):
    embedder = HashEmbedder()
    chunks = [c for d in load_documents(corpus_dir) for c in chunk(d)]
    store.Schema.create(conn, embedder.dims)
    store.upsert(conn, chunks, embedder)
    return embedder, chunks


@pytest.fixture(scope="module")
def measured(conn, indexed, golden):
    return metrics.evaluate(conn, indexed[0], rerank.LexicalReranker(), golden, k=10)


def test_relevance_is_the_anchor_inside_the_query_document():
    q = GoldenQuery("q", "?", "a", "Hair  Goods\nof all", "factual")
    chunks = [
        piece("a", 0, "Mme. Sofronie. HAIR goods OF ALL kinds."),
        piece("a", 1, "nothing here"),
        piece("b", 0, "hair goods of all kinds"),
    ]
    assert metrics.relevant(chunks, q) == {"a#000"}


def test_recall_precision_mrr_by_hand():
    retrieved = ["a", "x", "b", "y"]
    rel = {"a", "b", "c"}
    assert metrics.recall_at_k(retrieved, rel, 4) == pytest.approx(2 / 3)
    assert metrics.recall_at_k(retrieved, rel, 1) == pytest.approx(1 / 3)
    assert metrics.precision_at_k(retrieved, rel, 4) == pytest.approx(0.5)
    assert metrics.precision_at_k(retrieved, rel, 10) == pytest.approx(0.2)
    assert metrics.mrr(retrieved, rel) == 1.0
    assert metrics.mrr(["x", "y", "b"], rel) == pytest.approx(1 / 3)
    assert metrics.mrr(["x", "y"], rel) == 0.0


def test_ndcg_by_hand():
    assert metrics.ndcg_at_k(["a", "x", "b", "y"], {"a", "b", "c"}, 4) == pytest.approx(
        0.703918, abs=1e-6
    )
    assert metrics.ndcg_at_k(["x", "a"], {"a"}, 10) == pytest.approx(0.630930, abs=1e-6)
    assert metrics.ndcg_at_k(["x", "y"], {"a"}, 10) == 0.0


def test_ndcg_ideal_runs_over_min_k_and_relevant_total():
    assert metrics.ndcg_at_k(["a", "x", "y"], {"a"}, 10) == 1.0
    assert metrics.ndcg_at_k(["a", "b"], {"a", "b", "c", "d"}, 2) == 1.0


def test_hybrid_candidate_pool_bounds_recall(conn, indexed, golden):
    embedder, chunks = indexed
    pool = sum(
        metrics.recall_at_k(
            [r.chunk_id for r in hybrid.search(conn, embedder, q.query, n=50, top_k=50)],
            metrics.relevant(chunks, q),
            50,
        )
        for q in golden
    ) / len(golden)
    assert pool == pytest.approx(RECALL_AT_50, abs=TOLERANCE)


def test_reference_meets_the_floors_and_the_pinned_numbers(measured):
    print(metrics.report(measured))
    for name, value in PINNED.items():
        assert getattr(measured, name) == pytest.approx(value, abs=TOLERANCE), name
    for name, floor in FLOORS.items():
        assert getattr(measured, name) >= floor, name


def test_hybrid_alone_matches_the_pinned_numbers(conn, indexed, golden):
    hybrid_only = metrics.evaluate(conn, indexed[0], None, golden, k=10)
    for name, value in PINNED_HYBRID.items():
        assert getattr(hybrid_only, name) == pytest.approx(value, abs=TOLERANCE), name


def test_recall_by_kind_matches_the_pinned_numbers(measured):
    for kind, value in PINNED_RECALL_BY_KIND.items():
        assert measured.by_kind[kind]["recall"] == pytest.approx(value, abs=TOLERANCE), kind


def test_metrics_split_by_kind(measured):
    assert measured.k == 10 and measured.queries == 48
    assert set(measured.by_kind) == {"conceptual", "factual", "lexical"}
    assert all(v["queries"] == 16 for v in measured.by_kind.values())
    assert measured.by_kind["lexical"]["recall"] > measured.by_kind["conceptual"]["recall"]
    mean = sum(v["mrr"] for v in measured.by_kind.values()) / 3
    assert mean == pytest.approx(measured.mrr)


def test_report_prints_every_metric_and_kind(measured):
    text = metrics.report(measured)
    for word in ("recall", "precision", "mrr", "ndcg", "conceptual", "factual", "lexical"):
        assert word in text
    assert f"{measured.mrr:.3f}" in text


def test_cli_prints_the_report(pg_dsn, corpus_dir, capsys):
    argv = ["--corpus", str(corpus_dir), "--k", "10", "--dsn", pg_dsn, "--schema", "lab_cli"]
    assert metrics.main(argv) == 0
    out = capsys.readouterr().out
    assert "metrics at k=10" in out
    assert re.search(r"^all\s+48\s", out, re.MULTILINE)


def test_cli_lists_the_failed_queries(pg_dsn, corpus_dir, capsys):
    argv = ["--corpus", str(corpus_dir), "--dsn", pg_dsn, "--schema", "lab_cli", "--failures"]
    assert metrics.main(argv) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    rows = [re.fullmatch(r"(q\d\d), (factual|conceptual|lexical), (\d+|none)", ln) for ln in lines]
    assert all(rows), lines
    assert [r.group(1) for r in rows] == FAILED
    assert all(r.group(3) == "none" or int(r.group(3)) > 10 for r in rows)
