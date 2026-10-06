"""Problems 2, 5 and 11: verdicts dropped, mismatched date columns, aggressive scraping."""
import json

import pytest

from truthtrace.errors import FetchBlocked
from truthtrace.ingest import ingest_sources, run_every
from truthtrace.labels import Label
from truthtrace.sources import factcheck_org, politifact
from truthtrace.sources.http import PoliteFetcher
from truthtrace.sources.records import load_records
from truthtrace.sources.rss import parse_feed
from truthtrace.storage import Store

PF_URL = "https://www.politifact.com/factchecks/2024/may/02/sam-patel/bridge-closure/"
CLAIM_REVIEW = {
    "@context": "https://schema.org", "@type": "ClaimReview", "datePublished": "2024-05-02",
    "claimReviewed": "The Riverton bridge will be closed for two years.",
    "itemReviewed": {"@type": "Claim", "author": {"@type": "Person", "name": "Sam Patel"}},
    "reviewRating": {"@type": "Rating", "alternateName": "False"},
}
PF_PAGE = f"""<html><head>
<script type="application/ld+json">{json.dumps({"@graph": [CLAIM_REVIEW]})}</script>
<meta property="og:description" content="A synthetic test page.">
</head><body><h1 class="c-title">Bridge will not close for two years</h1>
<article class="m-textblock"><p>The schedule closes the bridge for <b>14 weeks</b>.</p><p>Lanes stay open.</p></article>
</body></html>"""
PF_PAGE_NO_JSONLD = """<html><body><h1>Headline</h1>
<div class="m-statement__quote"><a href="#">Taxes went up 300% last year.</a></div>
<a class="m-statement__name" href="#">Jo Example</a>
<div class="m-statement__meter"><div class="c-image"><img src="x.jpg" alt="pants-fire"></div></div>
<meta property="article:published_time" content="2023-11-05T10:00:00Z">
<article class="m-textblock"><p>Body text.</p></article></body></html>"""
FC_URL = "https://www.factcheck.org/2024/06/a-test-article/"
FC_PAGE = """<html><head><meta property="article:published_time" content="2024-06-10T08:00:00+00:00">
<meta property="og:description" content="Summary of the test article."></head><body>
<h1 class="entry-title">A Test Article</h1>
<div class="entry-content"><p>First paragraph.</p><div class="note"><p>Second paragraph.</p></div></div>
</body></html>"""
RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>One</title><link>https://www.politifact.com/factchecks/2024/may/02/sam-patel/bridge-closure/</link>
<pubDate>Thu, 02 May 2024 10:00:00 -0400</pubDate></item>
<item><title>Two</title><link>https://www.politifact.com/factchecks/2024/may/03/jo-example/taxes/</link></item>
<item><title>Not a fact-check</title><link>https://www.politifact.com/article/2024/may/04/news/</link></item>
</channel></rss>"""


def test_politifact_keeps_claim_speaker_rating_and_date():
    article = politifact.parse_article(PF_PAGE, PF_URL)
    assert article.claim == "The Riverton bridge will be closed for two years."
    assert article.speaker == "Sam Patel"
    assert article.rating == "False" and article.label == Label.FALSE
    assert article.published.isoformat() == "2024-05-02"
    assert "14 weeks" in article.body and article.title.startswith("Bridge will not close")


def test_politifact_html_fallback_without_jsonld():
    article = politifact.parse_article(PF_PAGE_NO_JSONLD, PF_URL)
    assert article.claim == "Taxes went up 300% last year."
    assert article.speaker == "Jo Example"
    assert article.label == Label.PANTS_ON_FIRE
    assert article.published.isoformat() == "2023-11-05"


def test_factcheck_org_keeps_full_body_and_date():
    article = factcheck_org.parse_article(FC_PAGE, FC_URL)
    assert article.body == "First paragraph.\n\nSecond paragraph."
    assert article.published.isoformat() == "2024-06-10"
    assert article.label is None and article.summary == "Summary of the test article."


def test_rss_parsing():
    items = parse_feed(RSS)
    assert [i.title for i in items] == ["One", "Two", "Not a fact-check"]
    assert items[0].published.isoformat() == "2024-05-02"


def test_record_import_maps_both_date_columns_and_reports_bad_rows(tmp_path):
    path = tmp_path / "mixed.csv"
    path.write_bytes(
        "url,Title,Date Published,Description,verdict\n"
        "https://example.org/a,Caf\xe9 claim,\"September 3, 2024\",Text,mostly-true\n"
        ",Missing url,2024-01-01,Text,false\n"
        "https://example.org/b,Second,2024-02-03,Text,half-true\n".encode("cp1252"))
    result = load_records(path)
    assert [a.url for a in result.articles] == ["https://example.org/a", "https://example.org/b"]
    assert result.articles[0].title == "Caf\xe9 claim"
    assert result.articles[0].published.isoformat() == "2024-09-03"
    assert result.articles[0].label == Label.MOSTLY_TRUE
    assert len(result.errors) == 1 and "missing url" in result.errors[0]


class FakeWeb:
    def __init__(self, pages, robots="User-agent: *\nAllow: /\n"):
        self.pages, self.robots = pages, robots
        self.requests = []

    def __call__(self, url, headers):
        self.requests.append((url, headers["User-Agent"]))
        if url.endswith("/robots.txt"):
            return (200, self.robots.encode()) if self.robots is not None else (404, b"")
        if url in self.pages:
            return 200, self.pages[url]
        return 404, b""


def fetcher(web, sleeps=None, clock=None):
    sleeps = [] if sleeps is None else sleeps
    return PoliteFetcher("truthtrace/0.1 (+https://example.org)", min_delay=5, opener=web,
                         sleep=sleeps.append, clock=clock or (lambda: 0.0))


def test_browser_user_agents_are_refused():
    with pytest.raises(ValueError):
        PoliteFetcher("Mozilla/5.0 (Windows NT 10.0)")


def test_robots_txt_is_respected():
    web = FakeWeb({"https://site.test/private/x": b"secret"}, robots="User-agent: *\nDisallow: /private/\n")
    f = fetcher(web)
    with pytest.raises(FetchBlocked):
        f.get("https://site.test/private/x")
    assert [u for u, _ in web.requests] == ["https://site.test/robots.txt"]  # the page itself was never requested
    assert all(ua.startswith("truthtrace/") for _, ua in web.requests)


def test_per_host_delay_is_enforced():
    web = FakeWeb({"https://site.test/a": b"a", "https://site.test/b": b"b"})
    sleeps = []
    f = fetcher(web, sleeps)
    f.get("https://site.test/a")
    f.get("https://site.test/b")
    assert len(sleeps) == 2 and all(s == pytest.approx(5) for s in sleeps)  # robots->a and a->b


def test_ingest_is_incremental_and_capped(tmp_path):
    feed = politifact.FEEDS[0]
    second = "https://www.politifact.com/factchecks/2024/may/03/jo-example/taxes/"
    web = FakeWeb({feed: RSS, PF_URL: PF_PAGE.encode(), second: PF_PAGE_NO_JSONLD.encode()})
    store = Store(tmp_path / "db.sqlite")

    report = ingest_sources(store, fetcher(web), sources=["politifact"], max_items=1)
    assert report.discovered == 2 and report.inserted == 1 and report.fetched == 1  # capped at 1 page

    report = ingest_sources(store, fetcher(web), sources=["politifact"], max_items=10)
    assert report.skipped_known == 1 and report.inserted == 1

    pages_before = len([u for u, _ in web.requests if "/factchecks/20" in u])
    report = ingest_sources(store, fetcher(web), sources=["politifact"], max_items=10)
    assert report.skipped_known == 2 and report.fetched == 0
    assert len([u for u, _ in web.requests if "/factchecks/20" in u]) == pages_before
    assert store.count() == 2


def test_scheduler_refuses_sub_hourly_runs():
    with pytest.raises(ValueError):
        run_every(5 / 60, lambda: None, runs=1)
    sleeps = []
    assert run_every(24, lambda: None, runs=2, sleep=sleeps.append) == 2 and sleeps == [24 * 3600]
