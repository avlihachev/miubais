import json
import os
import sys
import time
import types
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
from retrieval_lab import hybrid, metrics, rerank, store
from retrieval_lab.chunker import chunk, load_documents
from retrieval_lab.embed import FastEmbedder
from retrieval_lab.types import Chunk, Metrics

EMBED_MODEL = "BAAI/bge-small-en-v1.5"
RERANK_MODEL = "Xenova/ms-marco-MiniLM-L-6-v2"
DIMS = 384
K = 10
POOL = 50
FLOORS = {"recall": 0.75, "mrr": 0.60}
NAMES = ("recall", "precision", "mrr", "ndcg")
RECORD = Path(__file__).resolve().parent.parent / "fixtures" / "live_local_models_run.json"
MODEL_DIRS = (
    (
        "models--Qdrant--bge-small-en-v1.5-onnx-Q",
        "models--BAAI--bge-small-en-v1.5",
        "fast-bge-small-en-v1.5",
    ),
    ("models--Xenova--ms-marco-MiniLM-L-6-v2", "fast-ms-marco-MiniLM-L-6-v2"),
)


def models_cached() -> bool:
    try:
        from miubais.requirements import embed_models_cached
    except ImportError:
        override = os.environ.get("FASTEMBED_CACHE_PATH")
        cache = Path(override) if override else Path.home() / ".cache" / "fastembed"
        return all(any((cache / name).is_dir() for name in names) for names in MODEL_DIRS)
    return embed_models_cached()


@pytest.fixture
def workspace() -> Path:
    root = os.environ.get("MIUBAIS_WORKSPACE")
    if not root:
        pytest.fail("set MIUBAIS_WORKSPACE to your workspace (miubais check sets it for you)")
    return Path(root)


@pytest.fixture
def fake_fastembed(monkeypatch):
    calls = {}

    class TextEmbedding:
        def __init__(self, model_name, cache_dir=None, **kwargs):
            calls["embed"] = (model_name, cache_dir)

        def embed(self, documents, **kwargs):
            for i, _ in enumerate(documents):
                yield np.full(DIMS, i + 1, dtype=np.float64)

    class TextCrossEncoder:
        def __init__(self, model_name, cache_dir=None, **kwargs):
            calls["rerank"] = (model_name, cache_dir)

        def rerank(self, query, documents, **kwargs):
            yield from (float(len(d)) for d in documents)

    package = types.ModuleType("fastembed")
    package.TextEmbedding = TextEmbedding
    package.TextCrossEncoder = TextCrossEncoder
    sub = types.ModuleType("fastembed.rerank")
    leaf = types.ModuleType("fastembed.rerank.cross_encoder")
    leaf.TextCrossEncoder = TextCrossEncoder
    package.rerank, sub.cross_encoder = sub, leaf
    monkeypatch.setitem(sys.modules, "fastembed", package)
    monkeypatch.setitem(sys.modules, "fastembed.rerank", sub)
    monkeypatch.setitem(sys.modules, "fastembed.rerank.cross_encoder", leaf)
    return calls


def piece(i: int, text: str) -> Chunk:
    return Chunk("d", f"d#{i:03d}", 0, len(text), "", text)


def table(m: Metrics) -> dict:
    return {
        **{n: round(getattr(m, n), 3) for n in NAMES},
        "by_kind": {
            kind: {n: round(v[n], 3) for n in NAMES} | {"queries": int(v["queries"])}
            for kind, v in m.by_kind.items()
        },
    }


def aggregate(
    fused: Metrics, reranked: Metrics, chunks: int, timings: dict, pool_recall: float
) -> dict:
    return {
        "date": datetime.now(UTC).date().isoformat(),
        "stage": "08-live-local-models",
        "embedder": EMBED_MODEL,
        "reranker": RERANK_MODEL,
        "dims": DIMS,
        "chunks": chunks,
        "queries": reranked.queries,
        "k": K,
        "pool": POOL,
        "mmr_lambda": 0.7,
        "floors": FLOORS,
        "hybrid": table(fused),
        "reranked": table(reranked),
        "seconds": {name: round(value, 1) for name, value in timings.items()},
        "fused_pool_recall_at_50": round(pool_recall, 3),
    }


def problems(record: dict) -> list[str]:
    found = []
    for name, floor in FLOORS.items():
        value = record["reranked"][name]
        if value < floor:
            found.append(f"{name}@{K} {value} below {floor}")
    return found


def save(record: dict, workspace: Path) -> Path:
    path = workspace / "runs" / f"live-{datetime.now(UTC).date().isoformat()}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2) + "\n")
    return path


def test_the_options_name_the_models(monkeypatch, tmp_path):
    monkeypatch.delenv("FASTEMBED_CACHE_PATH", raising=False)
    embedder = FastEmbedder()
    assert embedder.dims == DIMS and EMBED_MODEL in embedder.name
    assert embedder.cache_dir == Path.home() / ".cache" / "fastembed"
    reranker = rerank.CrossEncoderReranker()
    assert reranker.model == RERANK_MODEL
    assert Path(reranker.cache_dir) == Path.home() / ".cache" / "fastembed"
    monkeypatch.setenv("FASTEMBED_CACHE_PATH", str(tmp_path))
    assert FastEmbedder().cache_dir == tmp_path
    assert Path(rerank.CrossEncoderReranker().cache_dir) == tmp_path


def test_nothing_imports_fastembed_before_it_is_needed(monkeypatch):
    for name in [m for m in sys.modules if m == "fastembed" or m.startswith("fastembed.")]:
        monkeypatch.delitem(sys.modules, name)
    monkeypatch.setitem(sys.modules, "fastembed", None)
    embedder = FastEmbedder()
    assert embedder.embed([]).shape == (0, DIMS)
    assert rerank.CrossEncoderReranker().rerank("q", [], 5) == []
    with pytest.raises(ImportError):
        embedder.embed(["x"])


def test_the_embedder_wraps_text_embedding(fake_fastembed, tmp_path):
    vectors = FastEmbedder(cache_dir=tmp_path).embed(["a", "b", "c"])
    assert fake_fastembed["embed"][0] == EMBED_MODEL
    assert Path(fake_fastembed["embed"][1]) == tmp_path
    assert vectors.shape == (3, DIMS) and vectors.dtype == np.float32
    assert vectors[2, 0] == 3.0


def test_the_reranker_wraps_the_cross_encoder(fake_fastembed, tmp_path):
    chunks = [piece(0, "ab"), piece(1, "abcd"), piece(2, "abc")]
    ranked = rerank.CrossEncoderReranker(cache_dir=tmp_path).rerank("q", chunks, 2)
    assert fake_fastembed["rerank"][0] == RERANK_MODEL
    assert [(r.chunk_id, r.rank) for r in ranked] == [("d#001", 1), ("d#002", 2)]


def test_the_aggregate_has_no_per_query_rows():
    by_kind = {"conceptual": {"recall": 0.5, "precision": 0.05, "mrr": 0.4, "ndcg": 0.4}}
    by_kind["conceptual"]["queries"] = 16.0
    weak = Metrics(k=K, queries=48, recall=0.7, precision=0.08, mrr=0.7, ndcg=0.7, by_kind=by_kind)
    record = aggregate(weak, weak, 900, {"index": 12.34}, 0.8)
    assert problems(record) == ["recall@10 0.7 below 0.75"]
    assert record["reranked"]["by_kind"]["conceptual"]["queries"] == 16
    assert record["seconds"] == {"index": 12.3}
    assert "q01" not in json.dumps(record)


def test_the_committed_record_has_exactly_the_written_fields():
    m = Metrics(k=K, queries=48, recall=0.8, precision=0.08, mrr=0.7, ndcg=0.7, by_kind={})
    written = aggregate(m, m, 685, {"index": 1.0}, 0.9)
    committed = json.loads(RECORD.read_text())
    assert committed.keys() == written.keys()
    assert committed["floors"] == written["floors"]


@pytest.mark.live
@pytest.mark.skipif(os.environ.get("MIUBAIS_SKIP_LIVE") == "1", reason="MIUBAIS_SKIP_LIVE=1")
@pytest.mark.skipif(not models_cached(), reason="needs embed-model")
def test_live_local_models_on_the_golden_set(conn, corpus_dir, golden, workspace):
    embedder, reranker = FastEmbedder(), rerank.CrossEncoderReranker()
    chunks = [c for d in load_documents(corpus_dir) for c in chunk(d)]
    started = time.monotonic()
    store.Schema.create(conn, embedder.dims)
    store.upsert(conn, chunks, embedder)
    indexed = time.monotonic()
    fused = metrics.evaluate(conn, embedder, None, golden, k=K)
    searched = time.monotonic()
    reranked = metrics.evaluate(conn, embedder, reranker, golden, k=K)
    done = time.monotonic()
    pool_recall = sum(
        metrics.recall_at_k(
            [h.chunk_id for h in hybrid.search(conn, embedder, q.query, n=POOL, top_k=POOL)],
            metrics.relevant(chunks, q),
            POOL,
        )
        for q in golden
    ) / len(golden)
    timings = {
        "index": indexed - started,
        "hybrid_eval": searched - indexed,
        "rerank_eval": done - searched,
    }
    record = aggregate(fused, reranked, len(chunks), timings, pool_recall)
    print(f"\nlive local models: {json.dumps(record, indent=2)}")
    print(metrics.report(reranked))
    print(f"saved {save(record, workspace)}")
    assert problems(record) == [], problems(record)
