from collections.abc import Callable, Sequence

import psycopg

from retrieval_lab.embed import Embedder
from retrieval_lab.rerank import Reranker
from retrieval_lab.types import Answer, Chunk, Draft, Faithfulness

REFUSAL = "I cannot answer from the sources"
SUPPORT_FLOOR = 4.0
MODEL = "claude-opus-5-5"
MAX_TURNS = 1
MAX_BUDGET_USD = 0.05


def sources(
    conn: psycopg.Connection,
    embedder: Embedder,
    reranker: Reranker,
    query: str,
    *,
    top_k: int = 5,
) -> tuple[list[Chunk], list[float]]:
    raise NotImplementedError


def assemble(
    query: str,
    chunks: Sequence[Chunk],
    *,
    scores: Sequence[float] | None = None,
    min_support: int = 1,
    floor: float = SUPPORT_FLOOR,
) -> Draft:
    raise NotImplementedError


def invalid_citations(text: str, citations: Sequence[str]) -> list[int]:
    raise NotImplementedError


def check(text: str, citations: Sequence[str]) -> Faithfulness:
    raise NotImplementedError


def run(
    query: str,
    draft: Draft,
    *,
    query_fn: Callable | None = None,
    model: str | None = None,
) -> Answer:
    raise NotImplementedError
