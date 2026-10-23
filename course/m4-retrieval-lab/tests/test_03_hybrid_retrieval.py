import re

import numpy as np
import pytest
from retrieval_lab import hybrid, store
from retrieval_lab.chunker import chunk, load_documents
from retrieval_lab.embed import HashEmbedder
from retrieval_lab.types import Hit

HOSTILE = [
    '"exact phrase" -term OR x',
    'prompt "caching',
    "it's a cache' OR '1'='1",
    "a & b | !c <-> (d:*)",
    "the of and",
]
LEXICAL_TEXT_ONLY = "q40"


def norm(text: str) -> str:
    return " ".join(text.split()).casefold()


@pytest.fixture(scope="module")
def indexed(conn, corpus_dir):
    embedder = HashEmbedder()
    chunks = [c for d in load_documents(corpus_dir) for c in chunk(d)]
    store.Schema.create(conn, embedder.dims)
    store.upsert(conn, chunks, embedder)
    return embedder, {c.chunk_id: c for c in chunks}


def relevant(chunks: dict, q) -> set[str]:
    anchor = norm(q.anchor)
    return {cid for cid, c in chunks.items() if c.doc_id == q.doc_id and anchor in norm(c.text)}


def recall_at_10(ids: list[str], rel: set[str]) -> float:
    return len(rel & set(ids[:10])) / len(rel)


def mean_recall(conn, indexed, golden) -> dict[str, float]:
    embedder, chunks = indexed
    totals = {"vector": 0.0, "text": 0.0, "fused": 0.0}
    for q in golden:
        rel = relevant(chunks, q)
        totals["vector"] += recall_at_10(
            [h.chunk_id for h in hybrid.vector_search(conn, embedder, q.query)], rel
        )
        totals["text"] += recall_at_10([h.chunk_id for h in hybrid.text_search(conn, q.query)], rel)
        totals["fused"] += recall_at_10(
            [r.chunk_id for r in hybrid.search(conn, embedder, q.query)], rel
        )
    return {side: total / len(golden) for side, total in totals.items()}


def hits(*ids: str) -> list[Hit]:
    return [Hit(cid, 1.0 / rank, rank) for rank, cid in enumerate(ids, 1)]


def test_vector_search_ranks_by_cosine(conn, indexed):
    embedder, chunks = indexed
    query = "reciprocal rank fusion of full text and vector lists"
    found = hybrid.vector_search(conn, embedder, query, n=50)
    assert len(found) == 50
    assert [h.rank for h in found] == list(range(1, 51))
    scores = [h.score for h in found]
    assert scores == sorted(scores, reverse=True)
    qvec = embedder.embed([query])[0]
    for h in found[:5]:
        expected = float(np.dot(qvec, embedder.embed([chunks[h.chunk_id].text])[0]))
        assert h.score == pytest.approx(expected, abs=1e-4)


def test_text_search_ranks_by_ts_rank_cd(conn, indexed):
    found = hybrid.text_search(conn, "Mme. Sofronie hair goods", n=20)
    assert 0 < len(found) <= 20
    assert [h.rank for h in found] == list(range(1, len(found) + 1))
    scores = [h.score for h in found]
    assert scores == sorted(scores, reverse=True)
    assert all(0 < s < 1 for s in scores)
    assert found[0].chunk_id.startswith("gift-of-the-magi#")


@pytest.mark.parametrize("query", HOSTILE)
def test_operators_and_quotes_never_raise(conn, indexed, query):
    embedder, _ = indexed
    assert isinstance(hybrid.text_search(conn, query), list)
    fused = hybrid.search(conn, embedder, query, top_k=10)
    assert len(fused) == 10
    assert any(r.ranks[0] is not None for r in fused)


@pytest.mark.parametrize("query", ["", "-", "  "])
def test_a_query_without_words_returns_nothing(conn, indexed, query):
    embedder, _ = indexed
    assert hybrid.vector_search(conn, embedder, query) == []
    assert hybrid.text_search(conn, query) == []
    assert hybrid.search(conn, embedder, query) == []


def test_a_negated_term_excludes_chunks(conn, indexed):
    _, chunks = indexed
    mentions = re.compile(r"\bbreakpoints?\b", re.IGNORECASE)
    plain = hybrid.text_search(conn, "prompt caching breakpoints", n=50)
    assert any(mentions.search(chunks[h.chunk_id].text) for h in plain[:10])
    negated = hybrid.text_search(conn, "prompt caching -breakpoints", n=50)
    assert negated
    assert not any(mentions.search(chunks[h.chunk_id].text) for h in negated)
    assert all(
        "prompt" in chunks[h.chunk_id].text.lower() or "cach" in chunks[h.chunk_id].text.lower()
        for h in negated
    )
    assert len(hybrid.text_search(conn, "-breakpoints", n=1000)) == 0
    phrase = hybrid.text_search(conn, 'cache -"cache breakpoint"', n=50)
    assert phrase
    assert not any("cache breakpoint" in norm(chunks[h.chunk_id].text) for h in phrase)


def test_rrf_scores_are_reciprocal_ranks():
    fused = hybrid.rrf([hits("a", "b", "c"), hits("c", "d")], k=60)
    scores = {r.chunk_id: r.score for r in fused}
    assert scores["c"] == pytest.approx(1 / 63 + 1 / 61)
    assert scores["a"] == pytest.approx(1 / 61)
    assert scores["d"] == pytest.approx(1 / 62)
    assert [r.chunk_id for r in fused] == ["c", "a", "b", "d"]
    assert [r.rank for r in fused] == [1, 2, 3, 4]
    assert fused[0].ranks == (3, 1)
    assert fused[1].ranks == (1, None)


def test_rrf_breaks_ties_by_chunk_id():
    fused = hybrid.rrf([hits("z", "m"), hits("a", "y")])
    assert [r.chunk_id for r in fused] == ["a", "z", "m", "y"]


def test_rrf_fuses_by_rank_not_by_score():
    filler = [f"v{i:02d}" for i in range(1, 30)]
    vector = [Hit(cid, 0.001, rank) for rank, cid in enumerate([*filler, "loud"], 1)]
    vector[-1] = Hit("loud", 999.0, 30)
    text = [Hit("quiet", 0.0001, 1)]
    fused = hybrid.rrf([vector, text], k=60)
    order = [r.chunk_id for r in fused]
    assert order.index("quiet") < order.index("loud")
    both = hybrid.rrf([hits(*filler, "twice"), hits(*filler, "twice"), [Hit("first", 0.0, 1)]])
    scores = {r.chunk_id: r.score for r in both}
    assert scores["twice"] == pytest.approx(2 / 90)
    assert scores["first"] == pytest.approx(1 / 61)
    order = [r.chunk_id for r in both]
    assert order.index("twice") < order.index("first")


def test_search_returns_top_k_fused(conn, indexed):
    embedder, _ = indexed
    fused = hybrid.search(conn, embedder, "prompt caching breakpoints", n=50, top_k=10)
    assert len(fused) == 10
    assert [r.rank for r in fused] == list(range(1, 11))
    assert [r.score for r in fused] == sorted((r.score for r in fused), reverse=True)


def test_a_lexical_query_needs_full_text(conn, indexed, golden):
    embedder, chunks = indexed
    q = next(q for q in golden if q.id == LEXICAL_TEXT_ONLY)
    assert q.kind == "lexical"
    rel = relevant(chunks, q)
    text_ids = [h.chunk_id for h in hybrid.text_search(conn, q.query)]
    vector_ids = [h.chunk_id for h in hybrid.vector_search(conn, embedder, q.query)]
    assert rel & set(text_ids[:10])
    assert not rel & set(vector_ids[:10])
    assert rel & {r.chunk_id for r in hybrid.search(conn, embedder, q.query, top_k=10)}


def test_fusion_beats_either_side_on_the_golden_set(conn, indexed, golden):
    recall = mean_recall(conn, indexed, golden)
    print(f"recall@10 {recall}")
    assert recall["fused"] >= recall["vector"]
    assert recall["fused"] >= recall["text"]
    assert recall["fused"] > min(recall["vector"], recall["text"])
