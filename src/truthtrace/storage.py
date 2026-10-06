"""SQLite storage for articles, chunks and vectors.

- Articles are keyed by URL (UNIQUE) and carry a content hash: re-ingesting the same page is a
  no-op, a changed page is updated in place. Nothing is ever appended twice.
- Chunks are keyed by a stable ``chunk_id``; vectors are recomputed only when chunk text or the
  embedding model changes.
- Every write is a transaction and the database runs in WAL mode, so readers (the UI) never see a
  half-written index. No pickle files anywhere.
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterator

from .labels import Label
from .models import Article

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id           INTEGER PRIMARY KEY,
    url          TEXT NOT NULL UNIQUE,
    source       TEXT NOT NULL,
    title        TEXT NOT NULL,
    claim        TEXT NOT NULL DEFAULT '',
    speaker      TEXT NOT NULL DEFAULT '',
    rating       TEXT NOT NULL DEFAULT '',
    label        TEXT,
    published    TEXT,
    summary      TEXT NOT NULL DEFAULT '',
    body         TEXT NOT NULL DEFAULT '',
    content_hash TEXT NOT NULL,
    scraped_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_articles_published ON articles(published);
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id   TEXT PRIMARY KEY,
    article_id INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL,
    ord        INTEGER NOT NULL,
    text       TEXT NOT NULL,
    text_hash  TEXT NOT NULL,
    embedder   TEXT,
    vector     BLOB
);
CREATE INDEX IF NOT EXISTS idx_chunks_article ON chunks(article_id);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class ChunkRow:
    chunk_id: str
    article_id: int
    kind: str  # "claim" | "body"
    ord: int
    text: str
    text_hash: str
    vector: bytes | None = None


@dataclass
class StoredArticle:
    id: int
    article: Article

    @property
    def label(self) -> Label | None:
        return self.article.label


class Store:
    def __init__(self, path: Path | str):
        self.path = Path(path) if str(path) != ":memory:" else path
        if isinstance(self.path, Path):
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        if isinstance(self.path, Path):
            self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.executescript(SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")

    def _query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    # -- articles ------------------------------------------------------------------------------------
    def upsert_article(self, article: Article) -> tuple[int, str]:
        """Insert or update by URL. Returns ``(article_id, "inserted" | "updated" | "unchanged")``."""
        digest = article.content_hash
        label = article.label.value if article.label else None
        published = article.published.isoformat() if article.published else None
        with self.transaction() as conn:
            row = conn.execute("SELECT id, content_hash FROM articles WHERE url = ?", (article.url,)).fetchone()
            if row and row["content_hash"] == digest:
                return row["id"], "unchanged"
            values = (article.source, article.title, article.claim, article.speaker, article.rating, label,
                      published, article.summary, article.body, digest)
            if row:
                conn.execute(
                    "UPDATE articles SET source=?, title=?, claim=?, speaker=?, rating=?, label=?, published=?, "
                    "summary=?, body=?, content_hash=?, updated_at=? WHERE id=?", values + (_now(), row["id"]))
                self._bump_version(conn)
                return row["id"], "updated"
            cur = conn.execute(
                "INSERT INTO articles (source, title, claim, speaker, rating, label, published, summary, body, "
                "content_hash, url, scraped_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                values + (article.url, _now(), _now()))
            self._bump_version(conn)
            return int(cur.lastrowid), "inserted"

    @staticmethod
    def _to_article(row: sqlite3.Row) -> StoredArticle:
        return StoredArticle(row["id"], Article(
            url=row["url"], source=row["source"], title=row["title"], claim=row["claim"],
            speaker=row["speaker"], rating=row["rating"], published=row["published"],
            summary=row["summary"], body=row["body"]))

    def get(self, article_id: int) -> StoredArticle | None:
        rows = self._query("SELECT * FROM articles WHERE id = ?", (article_id,))
        return self._to_article(rows[0]) if rows else None

    def get_many(self, ids: list[int]) -> dict[int, StoredArticle]:
        if not ids:
            return {}
        marks = ",".join("?" * len(ids))
        return {r["id"]: self._to_article(r) for r in self._query(f"SELECT * FROM articles WHERE id IN ({marks})",
                                                                     tuple(ids))}

    def by_url(self, url: str) -> StoredArticle | None:
        rows = self._query("SELECT * FROM articles WHERE url = ?", (url,))
        return self._to_article(rows[0]) if rows else None

    def known_urls(self) -> set[str]:
        return {r["url"] for r in self._query("SELECT url FROM articles")}

    def articles(self, *, before: date | None = None, since: date | None = None,
                 labelled_only: bool = False) -> list[StoredArticle]:
        sql, params = "SELECT * FROM articles WHERE 1=1", []
        if before:
            sql += " AND published < ?"
            params.append(before.isoformat())
        if since:
            sql += " AND published >= ?"
            params.append(since.isoformat())
        if labelled_only:
            sql += " AND label IS NOT NULL"
        return [self._to_article(r) for r in self._query(sql + " ORDER BY published, id", tuple(params))]

    def published_map(self) -> dict[int, date | None]:
        return {r["id"]: (date.fromisoformat(r["published"]) if r["published"] else None)
                for r in self._query("SELECT id, published FROM articles")}

    def count(self) -> int:
        return self._query("SELECT COUNT(*) AS n FROM articles")[0]["n"]

    # -- chunks --------------------------------------------------------------------------------------
    def sync_chunks(self, article_id: int, chunks: list[ChunkRow]) -> tuple[int, int]:
        """Make the article's chunks exactly ``chunks``. Returns ``(added_or_changed, removed)``.

        Unchanged chunks keep their vectors; changed ones lose them and get re-embedded later.
        """
        changed = removed = 0
        with self.transaction() as conn:
            existing = {r["chunk_id"]: r["text_hash"] for r in
                        conn.execute("SELECT chunk_id, text_hash FROM chunks WHERE article_id = ?", (article_id,))}
            wanted = {c.chunk_id for c in chunks}
            for chunk_id in set(existing) - wanted:
                conn.execute("DELETE FROM chunks WHERE chunk_id = ?", (chunk_id,))
                removed += 1
            for c in chunks:
                if existing.get(c.chunk_id) == c.text_hash:
                    continue
                conn.execute(
                    "INSERT INTO chunks (chunk_id, article_id, kind, ord, text, text_hash, embedder, vector) "
                    "VALUES (?,?,?,?,?,?,NULL,NULL) ON CONFLICT(chunk_id) DO UPDATE SET kind=excluded.kind, "
                    "ord=excluded.ord, text=excluded.text, text_hash=excluded.text_hash, embedder=NULL, vector=NULL",
                    (c.chunk_id, article_id, c.kind, c.ord, c.text, c.text_hash))
                changed += 1
            if changed or removed:
                self._bump_version(conn)
        return changed, removed

    def chunks_missing_vectors(self, embedder: str, limit: int = 256) -> list[ChunkRow]:
        rows = self._query("SELECT * FROM chunks WHERE vector IS NULL OR embedder IS NOT ? LIMIT ?", (embedder, limit))
        return [ChunkRow(r["chunk_id"], r["article_id"], r["kind"], r["ord"], r["text"], r["text_hash"]) for r in rows]

    def set_vectors(self, embedder: str, vectors: list[tuple[str, bytes]]) -> None:
        with self.transaction() as conn:
            conn.executemany("UPDATE chunks SET embedder = ?, vector = ? WHERE chunk_id = ?",
                             [(embedder, blob, cid) for cid, blob in vectors])
            self._bump_version(conn)

    def all_chunks(self, embedder: str | None = None) -> list[ChunkRow]:
        rows = self._query("SELECT * FROM chunks ORDER BY article_id, kind, ord")
        return [ChunkRow(r["chunk_id"], r["article_id"], r["kind"], r["ord"], r["text"], r["text_hash"],
                         r["vector"] if embedder is None or r["embedder"] == embedder else None) for r in rows]

    def chunk_count(self) -> int:
        return self._query("SELECT COUNT(*) AS n FROM chunks")[0]["n"]

    # -- versioning ----------------------------------------------------------------------------------
    @staticmethod
    def _bump_version(conn: sqlite3.Connection) -> None:
        conn.execute("INSERT INTO meta (key, value) VALUES ('index_version', '1') ON CONFLICT(key) "
                     "DO UPDATE SET value = CAST(value AS INTEGER) + 1")

    def index_version(self) -> int:
        rows = self._query("SELECT value FROM meta WHERE key = 'index_version'")
        return int(rows[0]["value"]) if rows else 0

    def set_meta(self, key: str, value: str) -> None:
        with self.transaction() as conn:
            conn.execute("INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = ?",
                         (key, value, value))

    def get_meta(self, key: str) -> str | None:
        rows = self._query("SELECT value FROM meta WHERE key = ?", (key,))
        return rows[0]["value"] if rows else None
