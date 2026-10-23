from collections.abc import Sequence

import psycopg

from retrieval_lab.embed import Embedder
from retrieval_lab.types import Hit, Ranked


def vector_search(
    conn: psycopg.Connection, embedder: Embedder, query: str, n: int = 50
) -> list[Hit]:
    raise NotImplementedError


def text_search(conn: psycopg.Connection, query: str, n: int = 50) -> list[Hit]:
    raise NotImplementedError


def rrf(lists: Sequence[Sequence[Hit]], k: int = 60) -> list[Ranked]:
    raise NotImplementedError


def search(
    conn: psycopg.Connection, embedder: Embedder, query: str, n: int = 50, top_k: int = 10
) -> list[Ranked]:
    raise NotImplementedError
