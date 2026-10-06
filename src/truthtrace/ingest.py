"""Incremental, polite ingestion from source feeds, plus file import and a scheduler loop."""
from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from .errors import FetchBlocked, ParseError, TransientError
from .indexing import Indexer
from .sources import ADAPTERS, PoliteFetcher, load_records, parse_feed
from .storage import Store

log = logging.getLogger(__name__)


@dataclass
class IngestReport:
    discovered: int = 0
    skipped_known: int = 0
    fetched: int = 0
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    blocked: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _record(report: IngestReport, status: str) -> None:
    setattr(report, status, getattr(report, status) + 1)


def ingest_sources(store: Store, fetcher: PoliteFetcher, indexer: Indexer | None = None, *,
                   sources: Iterable[str] = tuple(ADAPTERS), max_items: int = 50,
                   refresh_known: bool = False) -> IngestReport:
    """Discover new fact-checks through RSS and store them. Known URLs are not re-fetched
    (unless ``refresh_known``), and at most ``max_items`` article pages are requested per run."""
    report = IngestReport()
    known = store.known_urls()
    budget = max_items
    for name in sources:
        adapter = ADAPTERS[name]
        for feed_url in adapter.FEEDS:
            try:
                items = parse_feed(fetcher.get(feed_url))
            except (FetchBlocked, TransientError, ValueError) as exc:
                report.errors.append(f"{feed_url}: {exc}")
                continue
            except Exception as exc:  # noqa: BLE001 - malformed XML etc.
                report.errors.append(f"{feed_url}: unreadable feed ({type(exc).__name__})")
                continue
            for item in items:
                if not adapter.is_article_url(item.url):
                    continue
                report.discovered += 1
                if item.url in known and not refresh_known:
                    report.skipped_known += 1
                    continue
                if budget <= 0:
                    continue
                budget -= 1
                try:
                    page = fetcher.get(item.url).decode("utf-8", errors="replace")
                    report.fetched += 1
                    article = adapter.parse_article(page, item.url)
                    if article.published is None:
                        article.published = item.published
                    article_id, status = store.upsert_article(article)
                    _record(report, status)
                    known.add(item.url)
                    if indexer and status != "unchanged":
                        indexer.sync_article(article_id, article)
                except FetchBlocked as exc:
                    report.blocked += 1
                    report.errors.append(str(exc))
                except (ParseError, TransientError) as exc:
                    report.failed += 1
                    report.errors.append(f"{item.url}: {exc}")
    if indexer:
        indexer.embed_pending()
    return report


def import_file(path: Path | str, store: Store, indexer: Indexer | None = None,
                source: str = "import") -> IngestReport:
    """Load a JSONL/CSV export. Bad rows are listed in ``errors``; good rows are upserted."""
    result = load_records(path, default_source=source)
    report = IngestReport(discovered=len(result.articles) + len(result.errors), failed=len(result.errors),
                          errors=list(result.errors))
    for article in result.articles:
        article_id, status = store.upsert_article(article)
        _record(report, status)
        if indexer and status != "unchanged":
            indexer.sync_article(article_id, article)
    if indexer:
        indexer.embed_pending()
    return report


def run_every(interval_hours: float, job: Callable[[], object], *, runs: int | None = None,
              sleep: Callable[[float], None] = time.sleep) -> int:
    """Run ``job`` every ``interval_hours`` (minimum one hour). Returns the number of runs."""
    if interval_hours < 1:
        raise ValueError("ingestion must not run more often than once per hour")
    done = 0
    while runs is None or done < runs:
        try:
            job()
        except Exception:  # noqa: BLE001 - a failed run must not stop the schedule
            log.exception("scheduled ingestion failed")
        done += 1
        if runs is None or done < runs:
            sleep(interval_hours * 3600)
    return done
