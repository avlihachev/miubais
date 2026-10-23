from dataclasses import dataclass, field
from typing import Literal

Kind = Literal["factual", "conceptual", "lexical"]


@dataclass(frozen=True)
class Document:
    doc_id: str
    title: str
    text: str


@dataclass(frozen=True)
class Chunk:
    doc_id: str
    chunk_id: str
    start_char: int
    end_char: int
    heading_path: str
    text: str


@dataclass(frozen=True)
class Hit:
    chunk_id: str
    score: float
    rank: int


@dataclass(frozen=True)
class Ranked:
    chunk_id: str
    score: float
    rank: int
    ranks: tuple[int | None, ...] = ()


@dataclass(frozen=True)
class GoldenQuery:
    id: str
    query: str
    doc_id: str
    anchor: str
    kind: Kind


@dataclass(frozen=True)
class Metrics:
    k: int
    queries: int
    recall: float
    precision: float
    mrr: float
    ndcg: float
    by_kind: dict[str, dict[str, float]] = field(default_factory=dict)


@dataclass(frozen=True)
class Draft:
    prompt: str
    citations: tuple[str, ...]
    refused: bool = False


@dataclass(frozen=True)
class Faithfulness:
    cited: list[int]
    uncited_claims: int
    refused: bool


@dataclass(frozen=True)
class Answer:
    text: str
    faithfulness: Faithfulness
    cost_usd: float
