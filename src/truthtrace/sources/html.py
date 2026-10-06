"""Minimal HTML helpers built on the standard library (no BeautifulSoup needed).

Fact-check pages publish schema.org ``ClaimReview`` JSON-LD, which is the most stable way to read
the claim, the speaker, the rating and the date. The helpers below extract that, plus meta tags
and paragraph text inside a container identified by CSS class.
"""
from __future__ import annotations

import html as htmllib
import json
import re
from html.parser import HTMLParser
from typing import Any, Iterator

_JSONLD = re.compile(r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>", re.S | re.I)
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


def _walk(node: Any) -> Iterator[dict[str, Any]]:
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


def jsonld_objects(page: str) -> list[dict[str, Any]]:
    """All JSON-LD objects on the page, flattened (``@graph`` and nested objects included)."""
    objects: list[dict[str, Any]] = []
    for block in _JSONLD.findall(page or ""):
        try:
            data = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        objects.extend(_walk(data))
    return objects


def find_typed(page: str, type_name: str) -> list[dict[str, Any]]:
    out = []
    for obj in jsonld_objects(page):
        types = obj.get("@type")
        types = types if isinstance(types, list) else [types]
        if type_name in types:
            out.append(obj)
    return out


def meta_content(page: str, name: str) -> str:
    """Value of ``<meta property=name>`` or ``<meta name=name>``."""
    pattern = re.compile(r"<meta\s+[^>]*(?:property|name)=[\"']" + re.escape(name) + r"[\"'][^>]*>", re.I)
    match = pattern.search(page or "")
    if not match:
        return ""
    content = re.search(r"content=[\"']([^\"']*)[\"']", match.group(0), re.I)
    return htmllib.unescape(content.group(1)).strip() if content else ""


class _ContainerText(HTMLParser):
    """Collect text of ``<p>`` (and optionally other) elements inside a container with a CSS class."""

    def __init__(self, container_class: str, container_tag: str | None, text_tags: tuple[str, ...]):
        super().__init__(convert_charrefs=True)
        self.container_class, self.container_tag, self.text_tags = container_class, container_tag, text_tags
        self.depth = 0  # >0 while inside the container
        self.capture = 0  # >0 while inside a text tag within the container
        self.current: list[str] = []
        self.blocks: list[str] = []
        self.attrs_seen: list[dict[str, str]] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in VOID:
            if self.depth:
                self.attrs_seen.append({"tag": tag, **{k: v or "" for k, v in attrs.items()}})
            return
        classes = (attrs.get("class") or "").split()
        if self.depth:
            self.depth += 1
            if tag in self.text_tags:
                self.capture += 1
        elif self.container_class in classes and (self.container_tag in (None, tag)):
            self.depth = 1
            if tag in self.text_tags:
                self.capture += 1

    def handle_endtag(self, tag):
        if tag in VOID or not self.depth:
            return
        if tag in self.text_tags and self.capture:
            self.capture -= 1
            if not self.capture:
                text = " ".join("".join(self.current).split())
                if text:
                    self.blocks.append(text)
                self.current = []
        self.depth -= 1

    def handle_data(self, data):
        if self.capture:
            self.current.append(data)


def container_text(page: str, container_class: str, *, tag: str | None = None,
                   text_tags: tuple[str, ...] = ("p",)) -> list[str]:
    """Text blocks inside the first-level containers that carry ``container_class``."""
    parser = _ContainerText(container_class, tag, text_tags)
    parser.feed(page or "")
    parser.close()
    return parser.blocks


def container_attrs(page: str, container_class: str, void_tag: str = "img") -> list[dict[str, str]]:
    """Attributes of void elements (e.g. ``<img alt=...>``) inside a container."""
    parser = _ContainerText(container_class, None, ())
    parser.feed(page or "")
    parser.close()
    return [a for a in parser.attrs_seen if a.get("tag") == void_tag]


def first_heading(page: str, tag: str = "h1") -> str:
    match = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", page or "", re.S | re.I)
    if not match:
        return ""
    return " ".join(htmllib.unescape(re.sub(r"<[^>]+>", " ", match.group(1))).split())
