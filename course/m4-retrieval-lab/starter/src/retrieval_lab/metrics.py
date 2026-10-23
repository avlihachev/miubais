import sys
from collections.abc import Sequence

import psycopg

from retrieval_lab.embed import Embedder
from retrieval_lab.rerank import Reranker
from retrieval_lab.types import Chunk, GoldenQuery, Metrics

DEFAULT_DSN = "postgresql://postgres:miubais@127.0.0.1:5433/postgres"


def relevant(chunks: Sequence[Chunk], golden_query: GoldenQuery) -> set[str]:
    raise NotImplementedError


def recall_at_k(retrieved: Sequence[str], relevant_ids: set[str], k: int) -> float:
    raise NotImplementedError


def precision_at_k(retrieved: Sequence[str], relevant_ids: set[str], k: int) -> float:
    raise NotImplementedError


def mrr(retrieved: Sequence[str], relevant_ids: set[str]) -> float:
    raise NotImplementedError


def ndcg_at_k(retrieved: Sequence[str], relevant_ids: set[str], k: int) -> float:
    raise NotImplementedError


def evaluate(
    conn: psycopg.Connection,
    embedder: Embedder,
    reranker: Reranker | None,
    golden: Sequence[GoldenQuery],
    *,
    k: int = 10,
    n: int = 50,
    mmr_lambda: float = 0.7,
) -> Metrics:
    raise NotImplementedError


def report(m: Metrics) -> str:
    raise NotImplementedError


def main(argv: Sequence[str] | None = None) -> int:
    raise NotImplementedError


if __name__ == "__main__":
    sys.exit(main())
