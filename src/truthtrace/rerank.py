"""Rerankers score (query, passage) pairs in [0, 1]. Scores also drive claim matching and abstention."""
from __future__ import annotations

import math
from functools import lru_cache
from typing import Protocol, runtime_checkable

from .errors import ConfigError, MissingDependency
from .text import content_terms


@runtime_checkable
class Reranker(Protocol):
    name: str

    def score(self, query: str, passages: list[str]) -> list[float]:
        ...


class LexicalReranker:
    """F1 overlap of stemmed content words (plus bigrams), bounded to [0, 1]. No model needed."""

    name = "lexical"

    @staticmethod
    def _terms(text: str) -> set[str]:
        terms = content_terms(text)
        return set(terms) | {f"{a} {b}" for a, b in zip(terms, terms[1:])}

    def score(self, query: str, passages: list[str]) -> list[float]:
        q = self._terms(query)
        out = []
        for passage in passages:
            p = self._terms(passage)
            common = len(q & p)
            if not common:
                out.append(0.0)
                continue
            precision, recall = common / len(p), common / len(q)
            # recall matters more: a long passage that covers the whole query is a good match
            out.append(round(5 * precision * recall / (4 * precision + recall), 4))
        return out


class CrossEncoderReranker:
    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as exc:
            raise MissingDependency("sentence-transformers", "embeddings") from exc
        self._model = CrossEncoder(model_name)
        self.name = f"cross-encoder:{model_name}"

    def score(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        logits = self._model.predict([(query, p) for p in passages])
        return [1 / (1 + math.exp(-float(x))) for x in logits]


@lru_cache(maxsize=4)
def get_reranker(spec: str) -> Reranker:
    if spec == "lexical":
        return LexicalReranker()
    if spec.startswith("cross-encoder:"):
        return CrossEncoderReranker(spec.split(":", 1)[1])
    raise ConfigError(f"unknown reranker {spec!r}; use 'lexical' or 'cross-encoder:<model>'")
