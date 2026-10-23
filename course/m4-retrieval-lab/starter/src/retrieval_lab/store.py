from collections.abc import Sequence
from dataclasses import dataclass

import psycopg

from retrieval_lab.embed import Embedder
from retrieval_lab.types import Chunk


class DimsMismatch(ValueError):
    pass


@dataclass(frozen=True)
class Schema:
    dims: int

    @classmethod
    def create(cls, conn: psycopg.Connection, dims: int) -> "Schema":
        raise NotImplementedError


def upsert(
    conn: psycopg.Connection, chunks: Sequence[Chunk], embedder: Embedder, batch: int = 64
) -> int:
    raise NotImplementedError


def count(conn: psycopg.Connection) -> int:
    raise NotImplementedError
