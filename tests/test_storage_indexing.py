"""Problems 1, 6, 9 and 10: duplicate appends, truncated embeddings, indexer crash paths, pickle storage."""
from pathlib import Path

import pytest

from truthtrace import indexing
from truthtrace.ingest import import_file
from truthtrace.models import Article
from truthtrace.storage import Store
from truthtrace.text import chunk_words

from conftest import ARTICLES, make_services


def test_reindexing_is_idempotent(tmp_path):
    services = make_services(tmp_path)
    articles, chunks, version = services.store.count(), services.store.chunk_count(), services.store.index_version()
    for _ in range(3):  # the old scheduler appended everything every five minutes
        for a in ARTICLES:
            services.store.upsert_article(a)
        report = services.indexer.rebuild()
        assert report.chunks_changed == 0 and report.embedded == 0
    assert (services.store.count(), services.store.chunk_count(), services.store.index_version()) == \
        (articles, chunks, version)


def test_results_are_distinct_articles(services):
    results = services.retriever.search("bridge closed two years", k=5)
    urls = [e.url for e in results]
    assert len(urls) == len(set(urls))


def test_updated_article_is_rechunked_in_place(tmp_path):
    services = make_services(tmp_path)
    changed = Article(**{**ARTICLES[0].to_dict(), "body": "A completely rewritten body about library hours."})
    article_id, status = services.store.upsert_article(changed)
    assert status == "updated"
    services.indexer.sync_article(article_id, changed)
    assert services.indexer.embed_pending() >= 1
    assert services.store.count() == len(ARTICLES)
    hits = services.retriever.search("rewritten library hours", k=1)
    assert hits[0].url == ARTICLES[0].url


def test_long_articles_are_chunked_and_the_end_is_searchable(tmp_path):
    filler = " ".join(f"filler{i}" for i in range(900))
    article = Article(url="https://example.org/long", source="demo", title="Long article",
                      body=filler + " The decisive detail is that the aqueduct reopened in October.")
    services = make_services(tmp_path)
    article_id, _ = services.store.upsert_article(article)
    services.indexer.sync_article(article_id, article)
    services.indexer.embed_pending()
    hits = services.retriever.search("aqueduct reopened", k=1)
    assert hits[0].url == article.url and "aqueduct" in hits[0].passage


def test_chunk_words_overlap_and_limits():
    words = [f"w{i}" for i in range(500)]
    chunks = chunk_words(" ".join(words), size=180, overlap=40)
    assert all(len(c.split()) <= 180 for c in chunks)
    assert chunks[1].split()[0] == "w140" and chunks[-1].split()[-1] == "w499"
    with pytest.raises(ValueError):
        chunk_words("x", 10, 10)


def test_one_bad_article_does_not_stop_the_rebuild(tmp_path, monkeypatch):
    services = make_services(tmp_path)
    real = indexing.article_chunks

    def flaky(article_id, article, *args):
        if "bridge" in article.url:
            raise RuntimeError("boom")
        return real(article_id, article, *args)

    monkeypatch.setattr(indexing, "article_chunks", flaky)
    report = services.indexer.rebuild()
    assert report.articles == len(ARTICLES) - 1 and len(report.errors) == 1


def test_import_with_bad_rows_keeps_good_rows(tmp_path):
    path = tmp_path / "rows.jsonl"
    path.write_text('{"url": "https://example.org/x", "title": "Good row", "rating": "true"}\n'
                    'this is not json\n'
                    '{"title": "no url"}\n', encoding="utf-8")
    services = make_services(tmp_path)
    report = import_file(path, services.store, services.indexer)
    assert report.inserted == 1 and report.failed == 2 and len(report.errors) == 2
    assert services.store.by_url("https://example.org/x") is not None


def test_storage_is_sqlite_with_transactions_and_no_pickle(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    with pytest.raises(RuntimeError):
        with store.transaction() as conn:
            conn.execute("INSERT INTO meta (key, value) VALUES ('k', 'v')")
            raise RuntimeError("crash mid-write")
    assert store.get_meta("k") is None  # rolled back, nothing half-written
    assert not list(Path(tmp_path).glob("*.pkl"))
    assert store._query("PRAGMA journal_mode")[0][0] == "wal"


def test_url_is_unique(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    a = ARTICLES[0]
    first = store.upsert_article(a)
    assert store.upsert_article(a) == (first[0], "unchanged")
    assert store.count() == 1
