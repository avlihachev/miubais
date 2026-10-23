import hashlib
import itertools
import json
import os
import re
import subprocess
import sys
from dataclasses import replace

import numpy as np
import pytest
from retrieval_lab import store
from retrieval_lab.chunker import chunk, load_documents
from retrieval_lab.embed import Embedder, FastEmbedder, HashEmbedder

TEXTS = ["Reciprocal rank fusion merges ranked lists.", "The old man had an evil eye."]


def spec_vector(text: str, dims: int = 256) -> np.ndarray:
    words = re.findall(r"\w+", text.lower())
    grams = words + [f"{a} {b}" for a, b in itertools.pairwise(words)]
    grams += [w[i : i + 3] for w in words for i in range(len(w) - 2)]
    vec = np.zeros(dims)
    for gram in grams:
        h = int.from_bytes(hashlib.blake2b(gram.encode(), digest_size=8).digest(), "big")
        vec[h % dims] += -1.0 if h >> 63 else 1.0
    return vec / np.linalg.norm(vec)


@pytest.fixture(scope="module")
def sample_chunks(corpus_dir):
    docs = {d.doc_id: d for d in load_documents(corpus_dir)}
    return chunk(docs["m0-03-prompt-caching"]) + chunk(docs["tell-tale-heart"])


@pytest.fixture
def fresh(conn):
    conn.execute("DROP TABLE IF EXISTS chunks")
    return conn


def test_hash_embedder_shape_and_unit_norm():
    embedder = HashEmbedder()
    assert isinstance(embedder, Embedder)
    assert embedder.dims == 256
    assert embedder.name
    vectors = embedder.embed(TEXTS)
    assert vectors.shape == (2, 256)
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-5)


def test_hash_embedder_follows_the_pinned_recipe():
    vectors = HashEmbedder().embed(TEXTS)
    for text, vec in zip(TEXTS, vectors, strict=True):
        assert np.allclose(vec, spec_vector(text), atol=1e-6), text
    assert np.allclose(HashEmbedder(dims=64).embed(TEXTS[:1])[0], spec_vector(TEXTS[0], 64))


def test_hash_embedder_is_deterministic_across_calls_and_processes():
    embedder = HashEmbedder()
    first = embedder.embed(TEXTS)
    assert np.array_equal(first, embedder.embed(TEXTS))
    assert np.array_equal(first, HashEmbedder().embed(TEXTS))
    assert not np.allclose(first[0], first[1])
    code = (
        "import json, sys; from retrieval_lab.embed import HashEmbedder; "
        "print(json.dumps(HashEmbedder().embed(json.loads(sys.argv[1])).tolist()))"
    )
    for seed in ("1", "2"):
        env = {**os.environ, "PYTHONHASHSEED": seed}
        out = subprocess.run(
            [sys.executable, "-c", code, json.dumps(TEXTS)],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        ).stdout
        assert np.allclose(np.array(json.loads(out)), first, atol=1e-7), seed


def test_fast_embedder_is_lazy_and_names_its_model(monkeypatch, tmp_path):
    monkeypatch.delenv("FASTEMBED_CACHE_PATH", raising=False)
    embedder = FastEmbedder()
    assert "BAAI/bge-small-en-v1.5" in embedder.name
    assert embedder.dims == 384
    assert str(embedder.cache_dir).endswith(os.path.join(".cache", "fastembed"))
    assert FastEmbedder(cache_dir=tmp_path).cache_dir == tmp_path


def test_schema_creates_the_table_and_indexes(fresh):
    store.Schema.create(fresh, 256)
    store.Schema.create(fresh, 256)
    columns = dict(
        fresh.execute(
            "SELECT column_name, data_type FROM information_schema.columns"
            " WHERE table_name = 'chunks' AND table_schema = current_schema()"
        ).fetchall()
    )
    assert set(columns) == {
        "chunk_id", "doc_id", "heading_path", "start_char", "end_char", "text", "tsv", "embedding",
    }  # fmt: skip
    assert columns["tsv"] == "tsvector"
    indexes = " ".join(
        row[0]
        for row in fresh.execute(
            "SELECT indexdef FROM pg_indexes"
            " WHERE tablename = 'chunks' AND schemaname = current_schema()"
        ).fetchall()
    )
    assert "hnsw" in indexes and "vector_cosine_ops" in indexes
    assert "gin" in indexes and "(tsv)" in indexes


def test_upsert_is_idempotent_and_fills_tsv(fresh, sample_chunks):
    embedder = HashEmbedder()
    store.Schema.create(fresh, embedder.dims)
    store.upsert(fresh, sample_chunks, embedder)
    store.upsert(fresh, sample_chunks, embedder, batch=7)
    assert store.count(fresh) == len(sample_chunks)
    hits = fresh.execute(
        "SELECT count(*) FROM chunks WHERE tsv @@ websearch_to_tsquery('english', 'vulture eye')"
    ).fetchone()[0]
    assert hits >= 1
    changed = replace(sample_chunks[0], text="replaced text")
    store.upsert(fresh, [changed], embedder)
    assert store.count(fresh) == len(sample_chunks)
    row = fresh.execute(
        "SELECT text FROM chunks WHERE chunk_id = %s", [changed.chunk_id]
    ).fetchone()
    assert row[0] == "replaced text"


def test_stored_embedding_matches_the_embedder(fresh, sample_chunks):
    embedder = HashEmbedder()
    store.Schema.create(fresh, embedder.dims)
    store.upsert(fresh, sample_chunks[:3], embedder)
    stored = fresh.execute(
        "SELECT embedding FROM chunks WHERE chunk_id = %s", [sample_chunks[1].chunk_id]
    ).fetchone()[0]
    assert np.allclose(stored.to_numpy(), embedder.embed([sample_chunks[1].text])[0], atol=1e-6)


def test_dims_mismatch_raises(fresh, sample_chunks):
    store.Schema.create(fresh, 256)
    with pytest.raises(ValueError):
        store.Schema.create(fresh, 384)
    with pytest.raises(ValueError):
        store.upsert(fresh, sample_chunks[:2], HashEmbedder(dims=64))
    assert store.count(fresh) == 0
