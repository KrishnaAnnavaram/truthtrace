"""Text embedders. Models are created once per process and reused (``get_embedder`` is cached)."""
from __future__ import annotations

import math
import zlib
from array import array
from functools import lru_cache
from typing import Protocol, runtime_checkable

from .errors import ConfigError, MissingDependency
from .text import stem, tokenize


@runtime_checkable
class Embedder(Protocol):
    name: str
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one L2-normalised vector per text."""
        ...


def _normalise(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vector))
    return [v / norm for v in vector] if norm else vector


class HashingEmbedder:
    """Dependency-free embedder: signed feature hashing of stemmed unigrams and bigrams.

    It captures lexical overlap only (no synonyms), which is enough for offline demos and tests.
    Use a sentence-transformers model for real deployments.
    """

    def __init__(self, dim: int = 512):
        self.dim = dim
        self.name = f"hashing-{dim}"

    def _features(self, text: str) -> list[str]:
        tokens = [stem(t) for t in tokenize(text)]
        return tokens + [f"{a}_{b}" for a, b in zip(tokens, tokens[1:])]

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            vector = [0.0] * self.dim
            for feature in self._features(text):
                h = zlib.crc32(feature.encode("utf-8"))
                vector[h % self.dim] += 1.0 if (h >> 16) & 1 else -1.0
            vectors.append(_normalise(vector))
        return vectors


class SentenceTransformerEmbedder:
    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5"):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise MissingDependency("sentence-transformers", "embeddings") from exc
        self._model = SentenceTransformer(model_name)
        self.dim = int(self._model.get_sentence_embedding_dimension())
        self.name = f"st:{model_name}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = self._model.encode(list(texts), normalize_embeddings=True, show_progress_bar=False)
        return [list(map(float, v)) for v in vectors]


@lru_cache(maxsize=4)
def get_embedder(spec: str) -> Embedder:
    """``"hashing"`` or ``"sentence-transformers:<model>"``. Cached: each model loads once."""
    if spec == "hashing" or spec.startswith("hashing:"):
        dim = int(spec.split(":", 1)[1]) if ":" in spec else 512
        return HashingEmbedder(dim)
    if spec.startswith("sentence-transformers:"):
        return SentenceTransformerEmbedder(spec.split(":", 1)[1])
    raise ConfigError(f"unknown embedder {spec!r}; use 'hashing' or 'sentence-transformers:<model>'")


def pack(vector: list[float]) -> bytes:
    return array("f", vector).tobytes()


def unpack(blob: bytes) -> list[float]:
    values = array("f")
    values.frombytes(blob)
    return values.tolist()
