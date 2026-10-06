"""Hybrid retrieval: BM25 + dense vectors, fused with reciprocal rank fusion, reranked, one hit per article.

In-memory structures are built once and refreshed only when the store's index version changes,
so a chat turn costs one query embedding and a few dot products.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import date

from .bm25 import BM25
from .embeddings import Embedder, unpack
from .models import Evidence
from .rerank import Reranker
from .storage import ChunkRow, Store

try:
    import numpy as _np
except ImportError:  # pragma: no cover
    _np = None

RRF_K = 60


@dataclass
class _Snapshot:
    version: int
    chunks: list[ChunkRow]
    bm25: BM25
    vectors: object  # numpy matrix or list of lists (rows aligned with chunks; None rows have no vector)
    has_vector: list[bool]
    published: dict[int, date | None]


class HybridRetriever:
    def __init__(self, store: Store, embedder: Embedder, reranker: Reranker, candidates: int = 40):
        self.store, self.embedder, self.reranker = store, embedder, reranker
        self.candidates = candidates
        self._snapshot: _Snapshot | None = None
        self._lock = threading.Lock()
        self.loads = 0  # how many times the in-memory index was (re)built

    def _load(self) -> _Snapshot:
        version = self.store.index_version()
        with self._lock:
            if self._snapshot is not None and self._snapshot.version == version:
                return self._snapshot
            chunks = self.store.all_chunks(self.embedder.name)
            has_vector = [c.vector is not None for c in chunks]
            rows = [unpack(c.vector) if c.vector is not None else [0.0] * self.embedder.dim for c in chunks]
            vectors = _np.asarray(rows, dtype="float32") if (_np is not None and rows) else rows
            self._snapshot = _Snapshot(version, chunks, BM25([c.text for c in chunks]), vectors, has_vector,
                                       self.store.published_map())
            self.loads += 1
            return self._snapshot

    def _dense_top(self, snap: _Snapshot, query: str, k: int) -> list[tuple[int, float]]:
        if not snap.chunks:
            return []
        q = self.embedder.embed([query])[0]
        if _np is not None and not isinstance(snap.vectors, list):
            sims = snap.vectors @ _np.asarray(q, dtype="float32")
            order = _np.argsort(-sims)[: k * 2]
            pairs = [(int(i), float(sims[i])) for i in order]
        else:
            pairs = sorted(((i, sum(a * b for a, b in zip(row, q))) for i, row in enumerate(snap.vectors)),
                           key=lambda p: p[1], reverse=True)[: k * 2]
        return [(i, s) for i, s in pairs if snap.has_vector[i] and s > 0][:k]

    def search(self, query: str, k: int = 5, *, before: date | None = None,
               since: date | None = None) -> list[Evidence]:
        """Return up to ``k`` evidence items (distinct articles), best first.

        ``before``/``since`` restrict by publication date (used for time-split evaluation).
        """
        snap = self._load()
        if not query.strip() or not snap.chunks:
            return []
        fused: dict[int, float] = {}
        for ranking in (snap.bm25.top(query, self.candidates), self._dense_top(snap, query, self.candidates)):
            for rank, (i, _) in enumerate(ranking):
                fused[i] = fused.get(i, 0.0) + 1.0 / (RRF_K + rank + 1)

        def in_window(article_id: int) -> bool:
            published = snap.published.get(article_id)
            if before and (published is None or published >= before):
                return False
            if since and (published is None or published < since):
                return False
            return True

        best_chunk: dict[int, tuple[float, int]] = {}  # article_id -> (score, chunk index)
        for i, score in fused.items():
            article_id = snap.chunks[i].article_id
            if not in_window(article_id):
                continue
            if article_id not in best_chunk or score > best_chunk[article_id][0]:
                best_chunk[article_id] = (score, i)
        ranked = sorted(best_chunk.items(), key=lambda kv: kv[1][0], reverse=True)[: self.candidates]
        articles = self.store.get_many([a for a, _ in ranked])

        candidates = []
        for article_id, (score, i) in ranked:
            stored = articles.get(article_id)
            if stored is None:
                continue
            candidates.append((stored, snap.chunks[i], score))
        if not candidates:
            return []

        passages = [c.text for _, c, _ in candidates]
        claims = [s.article.claim or s.article.title for s, _, _ in candidates]
        passage_scores = self.reranker.score(query, passages)
        claim_scores = self.reranker.score(query, claims)
        scored = [(max(p, c), item) for p, c, item in zip(passage_scores, claim_scores, candidates)]
        scored.sort(key=lambda x: (x[0], x[1][2]), reverse=True)

        evidence = []
        for n, (relevance, (stored, chunk, score)) in enumerate(scored[:k], start=1):
            a = stored.article
            evidence.append(Evidence(
                id=f"E{n}", article_id=stored.id, url=a.url, source=a.source, title=a.title, claim=a.claim,
                speaker=a.speaker, label=a.label, published=a.published, passage=chunk.text,
                score=round(score, 5), relevance=round(relevance, 4)))
        return evidence
