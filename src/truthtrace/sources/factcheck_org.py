"""FactCheck.org adapter. FactCheck.org writes long-form articles without a rating scale, so the
rating is usually empty and the article body is used as evidence. When a page does carry
ClaimReview JSON-LD, its claim and rating are kept."""
from __future__ import annotations

import re

from ..errors import ParseError
from ..models import Article
from .html import container_text, find_typed, first_heading, meta_content

NAME = "factcheck.org"
FEEDS = ("https://www.factcheck.org/feed/",)
ARTICLE_URL = re.compile(r"^https://www\.factcheck\.org/\d{4}/\d{2}/[^/]+/?$")


def is_article_url(url: str) -> bool:
    return bool(ARTICLE_URL.match(url))


def parse_article(page: str, url: str) -> Article:
    title = first_heading(page) or meta_content(page, "og:title")
    if not title:
        raise ParseError(f"no title found on {url}")
    paragraphs = container_text(page, "entry-content")
    claim = rating = speaker = ""
    reviews = find_typed(page, "ClaimReview")
    if reviews:
        review = reviews[0]
        claim = str(review.get("claimReviewed", ""))
        rating = str((review.get("reviewRating") or {}).get("alternateName", ""))
        author = (review.get("itemReviewed") or {}).get("author") or {}
        speaker = str(author.get("name", "")) if isinstance(author, dict) else ""
    published = meta_content(page, "article:published_time")
    if not published:
        match = re.search(r"<time[^>]+datetime=[\"']([^\"']+)[\"']", page, re.I)
        published = match.group(1) if match else ""
    summary = meta_content(page, "og:description") or (paragraphs[0] if paragraphs else "")
    return Article(url=url, source=NAME, title=title, claim=claim, speaker=speaker, rating=rating,
                   published=published, body="\n\n".join(paragraphs), summary=summary)
