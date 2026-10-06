"""Chunk articles and keep their vectors in sync (idempotent: run it as often as you like)."""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field

from .embeddings import Embedder, pack
from .models import Article
from .storage import ChunkRow, Store
from .text import chunk_words, content_hash

log = logging.getLogger(__name__)


@dataclass
class IndexReport:
    articles: int = 0
    chunks_changed: int = 0
    chunks_removed: int = 0
    embedded: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def article_chunks(article_id: int, article: Article, size: int = 180, overlap: int = 40) -> list[ChunkRow]:
    """One "claim" chunk (claim, speaker, rating, title) plus overlapping body windows.

    Each body window is prefixed with the title so it stays meaningful on its own.
    """
    head_parts = [article.title]
    if article.claim:
        head_parts.append(f"Claim: {article.claim}")
    if article.speaker:
        head_parts.append(f"Speaker: {article.speaker}")
    if article.rating:
        head_parts.append(f"Rating: {article.rating}")
    if article.summary:
        head_parts.append(article.summary)
    head = " | ".join(head_parts)
    rows = [ChunkRow(f"{article_id}:claim:0", article_id, "claim", 0, head, content_hash(head))]
    for n, window in enumerate(chunk_words(article.body, size, overlap)):
        text = f"{article.title}: {window}"
        rows.append(ChunkRow(f"{article_id}:body:{n}", article_id, "body", n, text, content_hash(text)))
    return rows


class Indexer:
    def __init__(self, store: Store, embedder: Embedder, chunk_size: int = 180, overlap: int = 40,
                 batch_size: int = 64):
        self.store, self.embedder = store, embedder
        self.chunk_size, self.overlap, self.batch_size = chunk_size, overlap, batch_size

    def sync_article(self, article_id: int, article: Article) -> tuple[int, int]:
        return self.store.sync_chunks(article_id, article_chunks(article_id, article, self.chunk_size, self.overlap))

    def embed_pending(self) -> int:
        done = 0
        while True:
            pending = self.store.chunks_missing_vectors(self.embedder.name, limit=self.batch_size)
            if not pending:
                return done
            vectors = self.embedder.embed([c.text for c in pending])
            self.store.set_vectors(self.embedder.name, [(c.chunk_id, pack(v)) for c, v in zip(pending, vectors)])
            done += len(pending)

    def rebuild(self) -> IndexReport:
        """Re-chunk every article (only changed chunks are rewritten) and embed what is missing.

        A failure on one article is recorded and the rest continue.
        """
        report = IndexReport()
        for stored in self.store.articles():
            try:
                changed, removed = self.sync_article(stored.id, stored.article)
                report.chunks_changed += changed
                report.chunks_removed += removed
                report.articles += 1
            except Exception as exc:  # noqa: BLE001 - keep indexing the other articles
                log.warning("indexing article %s failed: %s", stored.id, type(exc).__name__)
                report.errors.append(f"{stored.article.url}: {exc}")
        report.embedded = self.embed_pending()
        return report
