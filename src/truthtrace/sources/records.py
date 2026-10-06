"""Import articles from JSONL or CSV files (exports, fixtures, the offline demo).

Bad rows are reported and skipped; they never abort the import or leave the store half-built.
"""
from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field
from pathlib import Path

from ..models import Article

ENCODINGS = ("utf-8-sig", "cp1252", "latin-1")
ALIASES = {"date": "published", "date published": "published", "date_published": "published",
           "description": "summary", "statement": "claim", "author": "speaker", "verdict": "rating",
           "label": "rating", "link": "url"}


@dataclass
class ImportResult:
    articles: list[Article] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ENCODINGS:
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")  # latin-1 never fails, kept for completeness


def _record_to_article(record: dict, default_source: str) -> Article:
    data = {}
    for key, value in record.items():
        if key is None:
            continue
        name = key.strip().lower()
        data[ALIASES.get(name, name)] = value.strip() if isinstance(value, str) else value
    if not data.get("url"):
        raise ValueError("missing url")
    if not (data.get("title") or data.get("claim")):
        raise ValueError("missing title and claim")
    return Article(url=data["url"], source=data.get("source") or default_source,
                   title=data.get("title") or data["claim"], claim=data.get("claim") or "",
                   speaker=data.get("speaker") or "", rating=data.get("rating") or "",
                   published=data.get("published"), body=data.get("body") or "",
                   summary=data.get("summary") or "")


def load_records(path: Path | str, default_source: str = "import") -> ImportResult:
    path = Path(path)
    text = _read_text(path)
    result = ImportResult()
    if path.suffix.lower() in (".jsonl", ".ndjson"):
        rows = []
        for n, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                rows.append((n, json.loads(line)))
            except json.JSONDecodeError as exc:
                result.errors.append(f"line {n}: invalid JSON ({exc.msg})")
    elif path.suffix.lower() == ".csv":
        rows = list(enumerate(csv.DictReader(io.StringIO(text)), start=2))
    else:
        raise ValueError(f"unsupported file type {path.suffix!r}; use .jsonl or .csv")
    for n, record in rows:
        try:
            if not isinstance(record, dict):
                raise ValueError("record is not an object")
            result.articles.append(_record_to_article(record, default_source))
        except (ValueError, TypeError) as exc:
            result.errors.append(f"line {n}: {exc}")
    return result
