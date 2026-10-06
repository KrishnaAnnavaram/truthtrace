"""Okapi BM25 over chunk texts (pure Python)."""
from __future__ import annotations

import math
from collections import Counter

from .text import content_terms


class BM25:
    def __init__(self, documents: list[str], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.docs = [Counter(content_terms(d)) for d in documents]
        self.lengths = [sum(c.values()) for c in self.docs]
        self.avg_len = (sum(self.lengths) / len(self.lengths)) if self.lengths else 0.0
        df: Counter = Counter()
        for doc in self.docs:
            df.update(doc.keys())
        n = len(self.docs)
        self.idf = {term: math.log(1 + (n - f + 0.5) / (f + 0.5)) for term, f in df.items()}
        self.postings: dict[str, list[int]] = {}
        for i, doc in enumerate(self.docs):
            for term in doc:
                self.postings.setdefault(term, []).append(i)

    def scores(self, query: str) -> dict[int, float]:
        """Scores for documents that share at least one term with the query."""
        out: dict[int, float] = {}
        for term in set(content_terms(query)):
            idf = self.idf.get(term)
            if idf is None:
                continue
            for i in self.postings[term]:
                tf = self.docs[i][term]
                norm = tf + self.k1 * (1 - self.b + self.b * self.lengths[i] / (self.avg_len or 1))
                out[i] = out.get(i, 0.0) + idf * tf * (self.k1 + 1) / norm
        return out

    def top(self, query: str, k: int) -> list[tuple[int, float]]:
        return sorted(self.scores(query).items(), key=lambda kv: kv[1], reverse=True)[:k]
