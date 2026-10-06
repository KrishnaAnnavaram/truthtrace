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
ARTICLE_URL = re.compile(r"^https://(?:www\.)?politifact\.com/factchecks/\d{4}/[a-z]{3}/\d{1,2}/[^/]+/[^/]+/?$")


def is_article_url(url: str) -> bool:
    return bool(ARTICLE_URL.match(url))


def _author_name(node) -> str:
    if isinstance(node, list):
        node = node[0] if node else {}
    if isinstance(node, dict):
        return str(node.get("name", ""))
    return str(node or "")


def _first_text(page: str, classes: tuple[str, ...], text_tags: tuple[str, ...]) -> str:
    """Text of the first container (in page order) that carries one of ``classes``."""
    for css_class in classes:
        blocks = container_text(page, css_class, text_tags=text_tags)
        if blocks:
            return blocks[0]
    return ""


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
    # HTML fallbacks: the older "m-statement" layout first, then the 2026 "pf-statement" layout.
    if not claim:
        claim = _first_text(page, ("m-statement__quote", "pf-statement-quote"), ("div", "a", "p"))
    if not rating:
        for meter in ("m-statement__meter", "pf-statement-meter"):
            images = container_attrs(page, meter)
            if images and images[0].get("alt"):
                rating = images[0]["alt"]
                break
    if not speaker:
        speaker = _first_text(page, ("m-statement__name", "pf-statement-person"), ("a",))
    if not published:
        published = meta_content(page, "article:published_time")
    body = "\n\n".join(container_text(page, "m-textblock"))
    title = first_heading(page) or meta_content(page, "og:title")
    if not (claim or title):
        raise ParseError(f"no claim or title found on {url}")
    return Article(url=url, source=NAME, title=title or claim, claim=claim, speaker=speaker, rating=rating,
                   published=published, body=body, summary=meta_content(page, "og:description"))
