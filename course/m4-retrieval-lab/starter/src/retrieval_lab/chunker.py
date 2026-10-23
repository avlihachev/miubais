from pathlib import Path

from retrieval_lab.types import Chunk, Document


def load_documents(corpus_dir: Path) -> list[Document]:
    raise NotImplementedError


def chunk(doc: Document, *, max_chars: int = 1200, overlap: int = 1) -> list[Chunk]:
    raise NotImplementedError
