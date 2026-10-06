"""Data objects shared across ingestion, retrieval and verification."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

from .dates import parse_date
from .labels import Label, normalize_rating
from .text import content_hash, normalize_space


@dataclass
class Article:
    """One fact-check article. Every source produces exactly these fields (no per-source columns)."""

    url: str
    source: str
    title: str
    claim: str = ""
    speaker: str = ""
    rating: str = ""  # the source's own wording, e.g. "pants-fire"
    published: date | None = None
    body: str = ""
    summary: str = ""

    def __post_init__(self):
        self.url = self.url.strip()
        self.title = normalize_space(self.title)
        self.claim = normalize_space(self.claim)
        self.speaker = normalize_space(self.speaker)
        self.rating = normalize_space(self.rating)
        self.summary = normalize_space(self.summary)
        self.body = (self.body or "").strip()
        if not isinstance(self.published, date):
            self.published = parse_date(self.published)

    @property
    def label(self) -> Label | None:
        return normalize_rating(self.rating)

    @property
    def content_hash(self) -> str:
        return content_hash(self.title, self.claim, self.speaker, self.rating, self.summary, self.body)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["published"] = self.published.isoformat() if self.published else None
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Article":
        return cls(**{k: data.get(k) or ("" if k != "published" else None) for k in cls.__dataclass_fields__})


@dataclass
class Evidence:
    """A retrieved article with the best-matching passage and its scores."""

    id: str  # "E1", "E2"... stable within one answer, used for citations
    article_id: int
    url: str
    source: str
    title: str
    claim: str
    speaker: str
    label: Label | None
    published: date | None
    passage: str
    score: float  # fused retrieval score
    relevance: float  # reranker score in [0, 1]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["label"] = self.label.value if self.label else None
        data["published"] = self.published.isoformat() if self.published else None
        return data


@dataclass
class VerificationResult:
    query: str
    mode: str  # "claim" | "question"
    label: Label
    method: str  # "matched_fact_check" | "llm_judgement" | "llm_answer" | "evidence_only" | "abstained"
    rationale: str
    citations: list[Evidence] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def abstained(self) -> bool:
        return self.method == "abstained"

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query, "mode": self.mode, "label": self.label.value, "label_display": self.label.display,
            "method": self.method, "rationale": self.rationale,
            "citations": [e.to_dict() for e in self.citations],
            "evidence": [e.to_dict() for e in self.evidence], "notes": list(self.notes),
        }
