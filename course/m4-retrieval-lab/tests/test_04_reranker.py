import sys

import numpy as np
import pytest
from retrieval_lab import hybrid, metrics, rerank, store
from retrieval_lab.chunker import chunk, load_documents
from retrieval_lab.embed import HashEmbedder
from retrieval_lab.types import Chunk, Ranked

PARAGRAPHS = [
    "Prompt caching stores the processed prefix of a request so the next call reuses it.",
    "A cache hit is billed at a tenth of the base input price for the cached tokens.",
    "Writing the cache costs a quarter more than plain input tokens for the default lifetime.",
    "The default lifetime is five minutes and every hit refreshes it.",
]


def doc_chunk(cid: str, text: str) -> Chunk:
    return Chunk(
        doc_id="d", chunk_id=cid, start_char=0, end_char=len(text), heading_path="", text=text
    )


@pytest.fixture(scope="module")
def indexed(conn, corpus_dir):
    embedder = HashEmbedder()
    chunks = [c for d in load_documents(corpus_dir) for c in chunk(d)]
    store.Schema.create(conn, embedder.dims)
    store.upsert(conn, chunks, embedder)
    return embedder, chunks


def test_lexical_reranker_scores_bm25_over_the_candidates():
    chunks = [
        doc_chunk("c1", "Cache cache miss"),
        doc_chunk("c2", "cache hit"),
        doc_chunk("c3", "cold start"),
    ]
    ranked = rerank.LexicalReranker().rerank("cache MISS?", chunks, top_k=3)
    assert [r.chunk_id for r in ranked] == ["c1", "c2", "c3"]
    assert [r.rank for r in ranked] == [1, 2, 3]
    assert ranked[0].score == pytest.approx(1.47637, abs=1e-4)
    assert ranked[1].score == pytest.approx(0.49918, abs=1e-4)
    assert ranked[2].score == 0.0


def test_lexical_reranker_weights_rare_terms_and_keeps_input_order_on_ties():
    chunks = [
        doc_chunk("a", "the cache and the prompt"),
        doc_chunk("b", "the breakpoint and the prompt"),
        doc_chunk("c", "the cache and the prompt"),
        doc_chunk("d", "the cache and the prompt"),
    ]
    ranked = rerank.LexicalReranker().rerank("cache breakpoint", chunks, top_k=2)
    assert [r.chunk_id for r in ranked] == ["b", "a"]
    assert len(rerank.LexicalReranker().rerank("x", [], top_k=5)) == 0


def test_mmr_drops_a_near_duplicate():
    embedder = HashEmbedder()
    first = " ".join(PARAGRAPHS[:3])
    overlapping = " ".join(PARAGRAPHS[1:4])
    other = "Reciprocal rank fusion adds one over sixty plus the rank from each list."
    texts = {"doc#000": first, "doc#001": overlapping, "other#000": other}
    vectors = dict(zip(texts, embedder.embed(list(texts.values())), strict=True))
    assert float(vectors["doc#000"] @ vectors["doc#001"]) > 0.6
    candidates = [
        Ranked("doc#000", 9.0, 1),
        Ranked("doc#001", 8.0, 2),
        Ranked("other#000", 7.0, 3),
    ]
    query = embedder.embed(["prompt caching price"])[0]
    plain = rerank.mmr(query, candidates, vectors, lam=1.0, top_k=2)
    assert [r.chunk_id for r in plain] == ["doc#000", "doc#001"]
    diverse = rerank.mmr(query, candidates, vectors, lam=0.7, top_k=2)
    assert [r.chunk_id for r in diverse] == ["doc#000", "other#000"]
    assert [r.rank for r in diverse] == [1, 2]
    assert diverse[1].score == 7.0


def test_mmr_falls_back_to_query_cosine_when_scores_tie():
    vectors = {"a": np.array([1.0, 0.0]), "b": np.array([0.0, 1.0])}
    tied = [Ranked("a", 0.0, 1), Ranked("b", 0.0, 2)]
    picked = rerank.mmr(np.array([0.1, 1.0]), tied, vectors, top_k=1)
    assert [r.chunk_id for r in picked] == ["b"]
    assert rerank.mmr(np.array([1.0, 0.0]), [], vectors, top_k=3) == []
    logits = [Ranked("a", -1.0, 1), Ranked("b", -4.0, 2)]
    assert [r.chunk_id for r in rerank.mmr(np.array([0.0, 1.0]), logits, vectors, top_k=1)] == ["a"]


def test_cross_encoder_imports_fastembed_only_when_it_ranks(monkeypatch):
    monkeypatch.setitem(sys.modules, "fastembed", None)
    monkeypatch.setitem(sys.modules, "fastembed.rerank.cross_encoder", None)
    reranker = rerank.CrossEncoderReranker()
    assert reranker.model == "Xenova/ms-marco-MiniLM-L-6-v2"
    assert reranker.rerank("q", [], top_k=3) == []
    with pytest.raises(ImportError):
        reranker.rerank("q", [doc_chunk("a", "text")], top_k=1)


def test_pipeline_reranks_the_fused_pool(conn, indexed):
    embedder, _ = indexed
    query = "how long does a prompt cache entry live"
    pool = {r.chunk_id for r in hybrid.search(conn, embedder, query, n=50, top_k=50)}
    ranked = rerank.pipeline(conn, embedder, rerank.LexicalReranker(), query, top_k=10)
    assert len(ranked) == 10
    assert [r.rank for r in ranked] == list(range(1, 11))
    assert {r.chunk_id for r in ranked} <= pool
    longer = rerank.pipeline(conn, embedder, rerank.LexicalReranker(), query, top_k=20)
    assert [r.chunk_id for r in longer[:10]] == [r.chunk_id for r in ranked]


def test_reranking_and_mmr_do_not_lose_mrr(conn, indexed, golden):
    embedder, _ = indexed
    reranker = rerank.LexicalReranker()
    hybrid_only = metrics.evaluate(conn, embedder, None, golden, k=10)
    reranked = metrics.evaluate(conn, embedder, reranker, golden, k=10, mmr_lambda=1.0)
    diverse = metrics.evaluate(conn, embedder, reranker, golden, k=10)
    print(f"mrr hybrid {hybrid_only.mrr:.3f} rerank {reranked.mrr:.3f} +mmr {diverse.mrr:.3f}")
    assert reranked.mrr > hybrid_only.mrr
    assert diverse.mrr >= hybrid_only.mrr
    assert diverse.recall >= hybrid_only.recall
