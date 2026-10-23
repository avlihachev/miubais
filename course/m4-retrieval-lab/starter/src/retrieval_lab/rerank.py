from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

import numpy as np
import psycopg

from retrieval_lab.embed import Embedder
from retrieval_lab.types import Chunk, Ranked


class Reranker(Protocol):
    def rerank(self, query: str, chunks: Sequence[Chunk], top_k: int) -> list[Ranked]: ...


class LexicalReranker:
    def __init__(self, k1: float = 1.2, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b

    def rerank(self, query: str, chunks: Sequence[Chunk], top_k: int) -> list[Ranked]:
        raise NotImplementedError


class CrossEncoderReranker:
    def __init__(
        self, model: str = "Xenova/ms-marco-MiniLM-L-6-v2", cache_dir: Path | None = None
    ) -> None:
        self.model = model
        self.cache_dir = cache_dir

    def rerank(self, query: str, chunks: Sequence[Chunk], top_k: int) -> list[Ranked]:
        raise NotImplementedError


def mmr(
    query_vec: np.ndarray,
    candidates: Sequence[Ranked],
    embeddings: dict[str, np.ndarray],
    *,
    lam: float = 0.7,
    top_k: int,
) -> list[Ranked]:
    raise NotImplementedError


def fetch(
    conn: psycopg.Connection, chunk_ids: Sequence[str]
) -> dict[str, tuple[Chunk, np.ndarray]]:
    raise NotImplementedError


def pipeline(
    conn: psycopg.Connection,
    embedder: Embedder,
    reranker: Reranker,
    query: str,
    *,
    n: int = 50,
    top_k: int = 10,
    mmr_lambda: float = 0.7,
) -> list[Ranked]:
    raise NotImplementedError
