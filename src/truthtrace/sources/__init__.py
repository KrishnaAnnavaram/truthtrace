"""Source adapters, a polite fetcher, feed parsing and file import."""
from . import factcheck_org, politifact
from .http import PoliteFetcher
from .records import ImportResult, load_records
from .rss import FeedItem, parse_feed

ADAPTERS = {politifact.NAME: politifact, factcheck_org.NAME: factcheck_org}

__all__ = ["ADAPTERS", "FeedItem", "ImportResult", "PoliteFetcher", "factcheck_org", "load_records",
           "parse_feed", "politifact"]
