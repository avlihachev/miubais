import os
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol, runtime_checkable

import numpy as np


@runtime_checkable
class Embedder(Protocol):
    @property
    def dims(self) -> int: ...

    @property
    def name(self) -> str: ...

    def embed(self, texts: Sequence[str]) -> np.ndarray: ...


class HashEmbedder:
    def __init__(self, dims: int = 256) -> None:
        raise NotImplementedError

    @property
    def dims(self) -> int:
        raise NotImplementedError

    @property
    def name(self) -> str:
        raise NotImplementedError

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        raise NotImplementedError


def default_cache_dir() -> Path:
    override = os.environ.get("FASTEMBED_CACHE_PATH")
    return Path(override) if override else Path.home() / ".cache" / "fastembed"


class FastEmbedder:
    def __init__(
        self, model: str = "BAAI/bge-small-en-v1.5", cache_dir: Path | None = None
    ) -> None:
        self.model = model
        self.cache_dir = Path(cache_dir) if cache_dir is not None else default_cache_dir()

    @property
    def dims(self) -> int:
        return 384

    @property
    def name(self) -> str:
        return f"fastembed:{self.model}"

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        raise NotImplementedError("FastEmbedder is written in stage 08")
