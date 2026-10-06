"""PolitiFact adapter: discovers fact-checks via RSS and keeps the claim, speaker and rating.

Primary source of truth is the page's schema.org ClaimReview JSON-LD; the visible statement
block is a fallback when JSON-LD is missing.
"""
from __future__ import annotations

import re

from ..errors import ParseError
from ..models import Article
from .html import container_attrs, container_text, find_typed, first_heading, meta_content

NAME = "politifact"
FEEDS = ("https://www.politifact.com/rss/factchecks/",)
ARTICLE_URL = re.compile(r"^https://www\.politifact\.com/factchecks/\d{4}/[a-z]{3}/\d{1,2}/[^/]+/[^/]+/?$")


def is_article_url(url: str) -> bool:
    return bool(ARTICLE_URL.match(url))


def _author_name(node) -> str:
    if isinstance(node, list):
        node = node[0] if node else {}
    if isinstance(node, dict):
        return str(node.get("name", ""))
    return str(node or "")


def parse_article(page: str, url: str) -> Article:
    reviews = find_typed(page, "ClaimReview")
    claim = speaker = rating = published = ""
    if reviews:
        review = reviews[0]
        claim = str(review.get("claimReviewed", ""))
        rating_node = review.get("reviewRating") or {}
        rating = str(rating_node.get("alternateName") or rating_node.get("name") or "")
        item = review.get("itemReviewed") or {}
        speaker = _author_name(item.get("author")) if isinstance(item, dict) else ""
        published = str(review.get("datePublished", ""))
    if not claim:
        quote = container_text(page, "m-statement__quote", text_tags=("div", "a", "p"))
        claim = quote[0] if quote else ""
    if not rating:
        images = container_attrs(page, "m-statement__meter")
        rating = images[0].get("alt", "") if images else ""
    if not speaker:
        names = container_text(page, "m-statement__name", text_tags=("a",))
        speaker = names[0] if names else ""
    if not published:
        published = meta_content(page, "article:published_time")
    body = "\n\n".join(container_text(page, "m-textblock", tag="article"))
    title = first_heading(page) or meta_content(page, "og:title")
    if not (claim or title):
        raise ParseError(f"no claim or title found on {url}")
    return Article(url=url, source=NAME, title=title or claim, claim=claim, speaker=speaker, rating=rating,
                   published=published, body=body, summary=meta_content(page, "og:description"))
