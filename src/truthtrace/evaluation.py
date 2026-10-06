"""Evaluation: verdict quality, abstention, retrieval recall@k and citation support.

The default test set is time-split: labelled fact-checks published on or after a cutoff are the
test claims, and retrieval is restricted to articles published *before* the cutoff, so a test
claim can never retrieve its own fact-check. The LIAR TSV format is also supported.
"""
from __future__ import annotations

import csv
import io
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Iterable

from .labels import Label, normalize_rating
from .models import VerificationResult
from .storage import Store
from .verify import Verifier

COARSE_CLASSES = ("supported", "mixed", "refuted")
VERDICT_METHODS = ("matched_fact_check", "llm_judgement")


@dataclass
class Example:
    claim: str
    gold: Label
    relevant_urls: frozenset[str] = frozenset()


def time_split_examples(store: Store, cutoff: date, limit: int | None = None) -> list[Example]:
    """Labelled claims published on/after ``cutoff``. Their own URLs are never retrievable
    because evaluation searches only articles published before the cutoff."""
    examples = [Example(s.article.claim, s.label) for s in store.articles(since=cutoff, labelled_only=True)
                if s.article.claim and s.label is not None]
    return examples[:limit] if limit else examples


LIAR_COLUMNS = ("id", "label", "statement", "subject", "speaker")


def load_liar_tsv(path: Path | str) -> list[Example]:
    """Read a LIAR-format TSV (id, label, statement, subject, speaker, ...)."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    examples = []
    for row in csv.reader(io.StringIO(text), delimiter="\t"):
        if len(row) < 3:
            continue
        label = normalize_rating(row[1])
        if label is not None and row[2].strip():
            examples.append(Example(row[2].strip(), label))
    return examples


def macro_f1(gold: list[str], pred: list[str], classes: Iterable[str]) -> float:
    scores = []
    for c in classes:
        tp = sum(1 for g, p in zip(gold, pred) if g == c and p == c)
        fp = sum(1 for g, p in zip(gold, pred) if g != c and p == c)
        fn = sum(1 for g, p in zip(gold, pred) if g == c and p != c)
        if tp + fp + fn == 0:
            continue
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        scores.append(2 * precision * recall / (precision + recall) if precision + recall else 0.0)
    return sum(scores) / len(scores) if scores else 0.0


def recall_at_k(retrieved: list[list[str]], relevant: list[frozenset[str]], k: int) -> float | None:
    pairs = [(r, rel) for r, rel in zip(retrieved, relevant) if rel]
    if not pairs:
        return None
    return sum(1 for r, rel in pairs if set(r[:k]) & rel) / len(pairs)


def citation_support(results: list[VerificationResult]) -> float | None:
    """Share of verdicts whose cited evidence exists in the retrieved set and, when the cited
    fact-check has a rating, points the same way (supported/mixed/refuted) as the verdict."""
    judged = [r for r in results if r.method in VERDICT_METHODS]
    if not judged:
        return None
    good = 0
    for r in judged:
        retrieved = {e.id for e in r.evidence}
        cited_ok = r.citations and all(c.id in retrieved for c in r.citations)
        rated = [c.label for c in r.citations if c.label is not None]
        direction_ok = not rated or any(l.coarse == r.label.coarse for l in rated)
        good += bool(cited_ok and direction_ok)
    return good / len(judged)


@dataclass
class EvalReport:
    n: int
    coverage: float  # share of claims that received a verdict (matched fact-check or LLM judgement)
    accuracy_answered: float | None  # exact 6-way label accuracy on answered claims
    coarse_accuracy_answered: float | None
    coarse_macro_f1_answered: float | None
    coarse_accuracy_overall: float  # abstentions count as wrong
    recall_at_k: float | None
    citation_support: float | None
    methods: dict[str, int] = field(default_factory=dict)
    confusion: dict[str, dict[str, int]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def evaluate(verifier: Verifier, examples: list[Example], *, before: date | None = None, k: int = 5) -> EvalReport:
    results = [verifier.verify(ex.claim, before=before) for ex in examples]
    # Only a verdict counts as an answer. A test claim that reads like a question gets an evidence-only
    # or an LLM answer without a label, and that is not a verdict.
    answered = [(ex, r) for ex, r in zip(examples, results) if r.method in VERDICT_METHODS]
    gold_coarse = [ex.gold.coarse for ex, _ in answered]
    pred_coarse = [r.label.coarse for _, r in answered]
    confusion: dict[str, dict[str, int]] = {}
    for ex, r in zip(examples, results):
        row = confusion.setdefault(ex.gold.coarse, {})
        row[r.label.coarse] = row.get(r.label.coarse, 0) + 1
    n = len(examples)
    return EvalReport(
        n=n,
        coverage=len(answered) / n if n else 0.0,
        accuracy_answered=(sum(ex.gold == r.label for ex, r in answered) / len(answered)) if answered else None,
        coarse_accuracy_answered=(sum(g == p for g, p in zip(gold_coarse, pred_coarse)) / len(answered))
        if answered else None,
        coarse_macro_f1_answered=macro_f1(gold_coarse, pred_coarse, COARSE_CLASSES) if answered else None,
        coarse_accuracy_overall=(sum(g == p for g, p in zip(gold_coarse, pred_coarse)) / n) if n else 0.0,
        recall_at_k=recall_at_k([[e.url for e in r.evidence] for r in results],
                                [ex.relevant_urls for ex in examples], k),
        citation_support=citation_support(results),
        methods=dict(Counter(r.method for r in results)),
        confusion=confusion,
    )
