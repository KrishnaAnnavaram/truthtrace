"""RSS 2.0 / Atom feed parsing. Feeds are the polite way to discover new fact-checks."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date

from ..dates import parse_date

ATOM = "{http://www.w3.org/2005/Atom}"


@dataclass
class FeedItem:
    url: str
    title: str
    published: date | None


def _text(node) -> str:
    return " ".join((node.text or "").split()) if node is not None else ""


def parse_feed(xml_bytes: bytes) -> list[FeedItem]:
    root = ET.fromstring(xml_bytes)
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
    seen, unique = set(), []
    for item in items:
        if item.url not in seen:
            seen.add(item.url)
            unique.append(item)
    return unique
