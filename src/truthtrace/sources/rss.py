"""RSS 2.0 / Atom feed parsing. Feeds are the polite way to discover new fact-checks.

Some real feeds are not well-formed XML (blank lines before the XML declaration, or namespace
prefixes such as ``content:`` that are never declared). For RSS 2.0 a tolerant fallback then reads
the ``<item>`` blocks directly, so one sloppy feed does not stop ingestion.
"""
from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date

from ..dates import parse_date

ATOM = "{http://www.w3.org/2005/Atom}"
_ITEM = re.compile(r"<item\b[^>]*>(.*?)</item>", re.S | re.I)
_BULKY = re.compile(r"<(content:encoded|description)\b[^>]*>.*?</\1>", re.S | re.I)
_CDATA = re.compile(r"^<!\[CDATA\[(.*)\]\]>$", re.S)


@dataclass
class FeedItem:
    url: str
    title: str
    published: date | None


def _text(node) -> str:
    return " ".join((node.text or "").split()) if node is not None else ""


def _items_from_tree(root: ET.Element) -> list[FeedItem]:
    items: list[FeedItem] = []
    for item in root.iter("item"):  # RSS 2.0
        url = _text(item.find("link")) or _text(item.find("guid"))
        if url:
            items.append(FeedItem(url, _text(item.find("title")), parse_date(_text(item.find("pubDate")))))
    for entry in root.iter(f"{ATOM}entry"):  # Atom
        link = entry.find(f"{ATOM}link")
        url = link.get("href", "") if link is not None else ""
        if url:
            when = _text(entry.find(f"{ATOM}published")) or _text(entry.find(f"{ATOM}updated"))
            items.append(FeedItem(url, _text(entry.find(f"{ATOM}title")), parse_date(when)))
    return items


def _tag_text(block: str, name: str) -> str:
    match = re.search(rf"<{name}\b[^>]*>(.*?)</{name}>", block, re.S | re.I)
    if not match:
        return ""
    value = match.group(1).strip()
    cdata = _CDATA.match(value)
    return " ".join(html.unescape(cdata.group(1) if cdata else value).split())


def _items_from_text(text: str) -> list[FeedItem]:
    """Tolerant RSS 2.0 reader for feeds that are not well-formed XML."""
    items: list[FeedItem] = []
    for block in _ITEM.findall(text):
        block = _BULKY.sub(" ", block)  # long HTML bodies can contain anything; ignore them
        url = _tag_text(block, "link") or _tag_text(block, "guid")
        if url:
            items.append(FeedItem(url, _tag_text(block, "title"), parse_date(_tag_text(block, "pubDate"))))
    return items


def parse_feed(xml_bytes: bytes) -> list[FeedItem]:
    try:
        items = _items_from_tree(ET.fromstring(xml_bytes.lstrip()))
    except ET.ParseError:
        items = _items_from_text(xml_bytes.decode("utf-8", errors="replace"))
        if not items:
            raise  # not a feed at all (for example an HTML error page)
    seen, unique = set(), []
    for item in items:
        if item.url not in seen:
            seen.add(item.url)
            unique.append(item)
    return unique
