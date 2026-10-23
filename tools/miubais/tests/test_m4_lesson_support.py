import hashlib
import math

import numpy as np
import pytest
from miubais.paths import course_dir, repo_root

LAB = course_dir() / "m4-retrieval-lab"


@pytest.fixture
def lessons(monkeypatch):
    monkeypatch.syspath_prepend(str(LAB / "starter" / "src"))
    monkeypatch.syspath_prepend(str(LAB / "lesson_support" / "src"))
    import retrieval_lab_lessons

    return retrieval_lab_lessons


DOC = "# T\n\nintro\n\n## A\n\none\n\n```\nx\n\n# not a heading\n```\n\ntwo\n\nthree\n"


def test_toy_chunk_sections_fences_and_offsets(lessons):
    chunks = lessons.toy_chunk("d", DOC, max_chars=12, overlap=1)
    assert [c.heading_path for c in chunks] == ["T", "T > A", "T > A", "T > A"]
    assert all(DOC[c.start_char : c.end_char] == c.text for c in chunks)
    assert [c.chunk_id for c in chunks] == [f"d#{i:03d}" for i in range(4)]
    assert chunks[2].text == "```\nx\n\n# not a heading\n```"
    assert chunks[3].text == "two\n\nthree"


def test_toy_chunk_overlap_carries_one_block(lessons):
    text = "aaaa\n\nbbbb\n\ncccc\n\ndddd\n"
    with_overlap = [c.text for c in lessons.toy_chunk("d", text, max_chars=10, overlap=1)]
    without = [c.text for c in lessons.toy_chunk("d", text, max_chars=10, overlap=0)]
    assert with_overlap == ["aaaa\n\nbbbb", "bbbb\n\ncccc", "cccc\n\ndddd"]
    assert without == ["aaaa\n\nbbbb", "cccc\n\ndddd"]


def test_toy_chunk_unclosed_fence_runs_to_the_end(lessons):
    chunks = lessons.toy_chunk("d", "p\n\n```\ncode\n\nmore\n", max_chars=1200)
    assert len(chunks) == 1 and chunks[0].text.endswith("more")


def test_hash_embed_follows_the_pinned_recipe(lessons):
    assert lessons.hash_tokens("Ab cde") == ["ab", "cde", "ab cde", "cde"]
    vec = lessons.hash_embed("Ab cde", dims=16)
    expected = np.zeros(16)
    for token in ["ab", "cde", "ab cde", "cde"]:
        h = int.from_bytes(hashlib.blake2b(token.encode(), digest_size=8).digest(), "big")
        expected[h % 16] += -1 if h >> 63 else 1
    assert np.allclose(vec, expected / np.linalg.norm(expected))
    assert not lessons.hash_embed("").any()
    assert lessons.cosine(vec, vec) == pytest.approx(1.0)


def test_rrf_is_rank_based_and_score_sum_is_not(lessons):
    fused = dict(lessons.rrf([["a", "b"], ["b"]], k=60))
    assert fused["b"] == pytest.approx(1 / 62 + 1 / 61) and fused["a"] == pytest.approx(1 / 61)
    assert lessons.rrf([["z"], ["a"]])[0][0] == "a"
    summed = lessons.score_sum([[("a", 0.9)], [("b", 0.3), ("a", 0.1)]])
    assert summed[0] == ("a", 1.0)


def test_metrics_by_hand(lessons):
    ranked, rel = ["x", "a", "y", "b"], {"a", "b", "c"}
    assert lessons.recall_at_k(ranked, rel, 4) == pytest.approx(2 / 3)
    assert lessons.precision_at_k(ranked, rel, 4) == 0.5
    assert lessons.reciprocal_rank(ranked, rel) == 0.5
    dcg = 1 / math.log2(3) + 1 / math.log2(5)
    assert lessons.ndcg_at_k(ranked, rel, 4) == pytest.approx(dcg / lessons.ideal_dcg(3))
    assert lessons.ndcg_at_k(["a"], {"a"}, 10) == 1.0
    assert lessons.ndcg_at_k(["x"], set(), 10) == 0.0


def test_toy_mmr_drops_the_near_duplicate(lessons):
    vectors = np.array([[1.0, 0.0], [0.99, 0.1], [0.0, 1.0]])
    assert lessons.toy_mmr([1.0, 0.95, 0.6], vectors, lam=1.0, top_k=2) == [0, 1]
    assert lessons.toy_mmr([1.0, 0.95, 0.6], vectors, lam=0.7, top_k=2) == [0, 2]


def test_toy_check_counts_uncited_invalid_and_refusal(lessons):
    found = lessons.toy_check("A [1]. B.\n[2] C [9].", sources=5)
    assert found["cited"] == [1, 2] and found["invalid"] == [9]
    assert found["uncited"] == 1 and not found["refused"]
    refusal = lessons.toy_check("I cannot answer from the sources.", sources=3)
    assert refusal["uncited"] == 0 and refusal["refused"]


def test_live_summaries_are_aggregates(lessons):
    models = lessons.live_models_summary(LAB / "fixtures" / "live_local_models_run.json")
    assert models["reranked"]["recall"] == pytest.approx(0.781)
    assert models["pool_recall"] == pytest.approx(0.875)
    answers = lessons.live_answer_summary(LAB / "fixtures" / "live_answer_run.json")
    assert answers["answers"] == 3 and answers["cite_relevant"] == 3
    assert answers["kinds"] == ["conceptual", "factual", "lexical"]
    assert not any(str(v).startswith("q") for v in answers.values())


def test_corpus_size_counts_the_fixture(lessons):
    size = lessons.corpus_size(repo_root() / "fixtures" / "corpus")
    assert size["documents"] == 32 and size["tokens_estimate"] == size["chars"] // 4
