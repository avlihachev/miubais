import hashlib
import itertools
import json
import math
import re
from collections.abc import Sequence
from pathlib import Path

import numpy as np
from retrieval_lab.types import Chunk

HEADING = re.compile(r"^(#{1,6}) +(\S.*?)\s*$")
FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
WORD = re.compile(r"\w+")
MARK = re.compile(r"\[(\d+)\]")
SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
REFUSAL = "I cannot answer from the sources"
CHARS_PER_TOKEN = 4


def corpus_size(corpus_dir) -> dict:
    root = Path(corpus_dir)
    files = sorted(root.glob("docs/*.md")) + sorted(root.glob("stories/*.txt"))
    texts = [f.read_text(encoding="utf-8") for f in files]
    chars = sum(len(t) for t in texts)
    return {
        "documents": len(files),
        "chars": chars,
        "words": sum(len(t.split()) for t in texts),
        "tokens_estimate": chars // CHARS_PER_TOKEN,
        "largest": max(len(t) for t in texts),
    }


def _blocks(text: str) -> list[tuple[int, int, int, str]]:
    found: list[tuple[int, int, int, str]] = []
    para: list[int] | None = None
    fence: list | None = None
    pos = 0
    for line in text.splitlines(keepends=True):
        start, pos = pos, pos + len(line)
        end = start + len(line.rstrip("\r\n"))
        bare = line.strip()
        if fence:
            marker = fence[0]
            fence[2] = end
            if bare and set(bare) == {marker[0]} and len(bare) >= len(marker):
                found.append((fence[1], end, 0, ""))
                fence = None
            continue
        opened = FENCE.match(line)
        heading = HEADING.match(line.rstrip("\r\n"))
        if para and (not bare or opened or heading):
            found.append((para[0], para[1], 0, ""))
            para = None
        if opened:
            fence = [opened.group(1), start, end]
        elif heading:
            found.append((start, end, len(heading.group(1)), heading.group(2)))
        elif bare:
            para = [para[0] if para else start, end]
    if fence:
        found.append((fence[1], fence[2], 0, ""))
    if para:
        found.append((para[0], para[1], 0, ""))
    return found


def _sections(text: str) -> list[tuple[str, list[tuple[int, int]]]]:
    result: list[tuple[str, list[tuple[int, int]]]] = []
    open_headings: list[tuple[int, str]] = []
    path, spans = "", []
    for start, end, level, title in _blocks(text):
        if level:
            if spans:
                result.append((path, spans))
            open_headings = [h for h in open_headings if h[0] < level] + [(level, title)]
            path, spans = " > ".join(t for _, t in open_headings), []
        spans.append((start, end))
    if spans:
        result.append((path, spans))
    return result


def toy_chunk(doc_id: str, text: str, *, max_chars: int = 1200, overlap: int = 1) -> list[Chunk]:
    chunks: list[Chunk] = []
    for path, spans in _sections(text):
        first = 0
        while first < len(spans):
            last = first
            while last + 1 < len(spans) and spans[last + 1][1] - spans[first][0] <= max_chars:
                last += 1
            start, end = spans[first][0], spans[last][1]
            chunks.append(
                Chunk(doc_id, f"{doc_id}#{len(chunks):03d}", start, end, path, text[start:end])
            )
            if last + 1 >= len(spans):
                break
            nxt = max(first + 1, last + 1 - overlap)
            while nxt <= last and spans[last + 1][1] - spans[nxt][0] > max_chars:
                nxt += 1
            first = nxt
    return chunks


def hash_tokens(text: str) -> list[str]:
    words = WORD.findall(text.lower())
    pairs = [f"{a} {b}" for a, b in itertools.pairwise(words)]
    grams = [w[i : i + 3] for w in words for i in range(len(w) - 2)]
    return words + pairs + grams


def hash_embed(text: str, dims: int = 256) -> np.ndarray:
    vec = np.zeros(dims, dtype=np.float32)
    for token in hash_tokens(text):
        h = int.from_bytes(hashlib.blake2b(token.encode(), digest_size=8).digest(), "big")
        vec[h % dims] += -1.0 if h >> 63 else 1.0
    norm = float(np.linalg.norm(vec))
    return vec / norm if norm else vec


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    return float(np.dot(a, b) / (na * nb)) if na and nb else 0.0


def rrf(lists: Sequence[Sequence[str]], k: int = 60) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for ranking in lists:
        for rank, item in enumerate(ranking, 1):
            scores[item] = scores.get(item, 0.0) + 1 / (k + rank)
    return sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))


def score_sum(lists: Sequence[Sequence[tuple[str, float]]]) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for ranking in lists:
        for item, score in ranking:
            scores[item] = scores.get(item, 0.0) + score
    return sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))


def recall_at_k(ranked: Sequence[str], relevant: set[str], k: int) -> float:
    return len(relevant & set(ranked[:k])) / len(relevant) if relevant else 0.0


def precision_at_k(ranked: Sequence[str], relevant: set[str], k: int) -> float:
    return len(relevant & set(ranked[:k])) / k


def reciprocal_rank(ranked: Sequence[str], relevant: set[str]) -> float:
    return next((1 / i for i, item in enumerate(ranked, 1) if item in relevant), 0.0)


def dcg_at_k(ranked: Sequence[str], relevant: set[str], k: int) -> float:
    return sum(1 / math.log2(i + 1) for i, item in enumerate(ranked[:k], 1) if item in relevant)


def ideal_dcg(n: int) -> float:
    return sum(1 / math.log2(i + 1) for i in range(1, n + 1))


def ndcg_at_k(ranked: Sequence[str], relevant: set[str], k: int) -> float:
    ideal = ideal_dcg(min(k, len(relevant)))
    return dcg_at_k(ranked, relevant, k) / ideal if ideal else 0.0


def toy_mmr(
    relevance: Sequence[float], vectors: np.ndarray, *, lam: float = 0.7, top_k: int
) -> list[int]:
    unit = vectors / np.linalg.norm(vectors, axis=1, keepdims=True)
    picked: list[int] = []
    left = list(range(len(relevance)))
    while left and len(picked) < top_k:

        def value(i: int) -> float:
            overlap = max((float(unit[i] @ unit[j]) for j in picked), default=0.0)
            return lam * relevance[i] - (1 - lam) * overlap

        best = max(left, key=lambda i: (value(i), -i))
        picked.append(best)
        left.remove(best)
    return picked


def toy_check(text: str, sources: int) -> dict:
    sentences: list[str] = []
    for part in SENTENCE.split(text.strip()):
        lead = re.match(r"((?:\[\d+\]\s*)+)(.*)", part, re.DOTALL)
        if lead and sentences:
            sentences[-1] += " " + lead.group(1).strip()
            part = lead.group(2)
        if part.strip(" .,;:"):
            sentences.append(part.strip())
    cited, invalid, uncited = set(), set(), 0
    for sentence in sentences:
        if sentence.rstrip(".") == REFUSAL:
            continue
        marks = {int(n) for n in MARK.findall(sentence)}
        good = {n for n in marks if 1 <= n <= sources}
        cited |= good
        invalid |= marks - good
        uncited += not good
    return {
        "sentences": len(sentences),
        "cited": sorted(cited),
        "invalid": sorted(invalid),
        "uncited": uncited,
        "refused": REFUSAL in text,
    }


def live_models_summary(path) -> dict:
    record = json.loads(Path(path).read_text())

    def row(part: dict) -> dict:
        return {name: part[name] for name in ("recall", "precision", "mrr", "ndcg")}

    return {
        "embedder": record["embedder"],
        "reranker": record["reranker"],
        "chunks": record["chunks"],
        "queries": record["queries"],
        "k": record["k"],
        "pool": record["pool"],
        "hybrid": row(record["hybrid"]),
        "reranked": row(record["reranked"]),
        "recall_by_kind": {
            kind: (record["hybrid"]["by_kind"][kind]["recall"], values["recall"])
            for kind, values in record["reranked"]["by_kind"].items()
        },
        "pool_recall": record["fused_pool_recall_at_50"],
        "index_seconds": record["seconds"]["index"],
        "rerank_seconds": record["seconds"]["rerank_eval"],
    }


def live_answer_summary(path) -> dict:
    record = json.loads(Path(path).read_text())
    answers = record["answers"]
    return {
        "model": record["model"],
        "limit_usd": record["limit_usd"],
        "support_floor": record["support_floor"],
        "answers": len(answers),
        "kinds": sorted(a["kind"] for a in answers),
        "refused": sum(a["refused"] for a in answers),
        "cite_relevant": sum(a["cites_relevant"] for a in answers),
        "citations": sum(a["cited"] for a in answers),
        "invalid": sum(a["invalid_citations"] for a in answers),
        "uncited": sum(a["uncited_claims"] for a in answers),
        "cost_usd": record["cost_usd"],
        "max_total_usd": record["max_total_usd"],
    }
