"""Claim verification: matched fact-check first, then cited LLM judgement, otherwise abstain.

Decision order for a claim:
1. Retrieve evidence. If nothing is relevant enough, abstain.
2. If a retrieved fact-check's *claim* closely matches the user's claim (same polarity, same
   numbers) and strongly matching fact-checks don't disagree, return that expert rating.
3. Otherwise, if an LLM is configured, ask it for a label with citations; reject output whose
   label is off-scale or whose citations don't point at the evidence.
4. Otherwise abstain and show the related fact-checks.
"""
from __future__ import annotations

import logging
import re
from datetime import date
from functools import lru_cache
from importlib import resources
from string import Template
from typing import Any

from .labels import SCALE, Label
from .llm import LLM
from .models import Evidence, VerificationResult
from .rerank import Reranker
from .retrieval import HybridRetriever
from .text import has_negation, numbers_in

log = logging.getLogger(__name__)

JUDGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "label": {"type": "string", "enum": [l.value for l in SCALE] + [Label.UNVERIFIABLE.value]},
        "rationale": {"type": "string"},
        "citations": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["label", "rationale", "citations"],
    "additionalProperties": False,
}
ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"answer": {"type": "string"}, "citations": {"type": "array", "items": {"type": "string"}}},
    "required": ["answer", "citations"],
    "additionalProperties": False,
}

_QUESTION_START = re.compile(
    r"^(who|whom|whose|what|when|where|why|how|which|is|are|was|were|do|does|did|can|could|should|has|"
    r"have|had|will|would)\b", re.I)
_CLAIM_WRAPPER = re.compile(
    r"^(?:is it (?:true|correct|accurate) that|is it true|fact[- ]?check:?|true or false:?|verify:?|"
    r"check:?|claim:?)\s*", re.I)


@lru_cache(maxsize=None)
def _template(name: str) -> Template:
    return Template(resources.files("truthtrace").joinpath("prompts", f"{name}.txt").read_text(encoding="utf-8"))


def classify_query(text: str) -> tuple[str, str]:
    """Return ``("claim" | "question", text to search with)``.

    "Is it true that X?" and "Fact check: X" are claims about X. Other wh-/yes-no questions are
    questions. Everything else is treated as a claim.
    """
    raw = " ".join((text or "").split())
    lowered = raw.lower()
    if re.match(r"^(is it (true|correct|accurate) that|fact[- ]?check|true or false|verify|check|claim)\b", lowered):
        return "claim", _CLAIM_WRAPPER.sub("", raw).rstrip("?").strip()
    if raw.endswith("?") or _QUESTION_START.match(raw):
        return "question", raw
    return "claim", raw


def claim_match(query: str, evidence: Evidence, reranker: Reranker) -> tuple[float, list[str]]:
    """Similarity between the user's claim and a fact-checked claim, plus reasons it can't be reused."""
    if not evidence.claim:
        return 0.0, ["the article has no single checked claim"]
    similarity = reranker.score(query, [evidence.claim])[0]
    problems = []
    if has_negation(query) != has_negation(evidence.claim):
        problems.append("one statement is negated and the other is not")
    q_numbers, c_numbers = numbers_in(query), numbers_in(evidence.claim)
    if q_numbers and c_numbers and q_numbers != c_numbers:
        problems.append(f"the numbers differ ({', '.join(sorted(q_numbers))} vs {', '.join(sorted(c_numbers))})")
    return similarity, problems


def format_evidence(evidence: list[Evidence]) -> str:
    blocks = []
    for e in evidence:
        when = e.published.isoformat() if e.published else "unknown date"
        rating = e.label.display if e.label else "none"
        lines = [f"[{e.id}] source: {e.source} | published: {when} | rating: {rating}"]
        if e.claim:
            lines.append(f"claim checked: {e.claim}" + (f" (said by {e.speaker})" if e.speaker else ""))
        lines.append(f"title: {e.title}")
        lines.append(f"passage: {e.passage}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


class Verifier:
    def __init__(self, retriever: HybridRetriever, reranker: Reranker, llm: LLM | None = None, *,
                 top_k: int = 5, match_threshold: float = 0.6, abstain_threshold: float = 0.2,
                 history_turns: int = 4):
        self.retriever, self.reranker, self.llm = retriever, reranker, llm
        self.top_k = top_k
        self.match_threshold, self.abstain_threshold = match_threshold, abstain_threshold
        self.history_turns = history_turns

    def verify(self, text: str, *, history: list[dict[str, str]] | None = None,
               before: date | None = None) -> VerificationResult:
        mode, query = classify_query(text)
        if not query:
            return VerificationResult(text, mode, Label.UNVERIFIABLE, "abstained", "Please enter a claim to check.")
        evidence = self.retriever.search(query, self.top_k, before=before)
        relevant = [e for e in evidence if e.relevance >= self.abstain_threshold]
        if not relevant:
            return VerificationResult(
                text, mode, Label.UNVERIFIABLE, "abstained",
                "I couldn't find a fact-check that addresses this. That does not mean it is true or false.",
                evidence=evidence, notes=["no evidence above the relevance threshold"])
        if mode == "question":
            return self._answer(text, query, relevant, history or [])
        return self._judge(text, query, relevant)

    # -- claims --------------------------------------------------------------------------------------
    def _judge(self, text: str, query: str, evidence: list[Evidence]) -> VerificationResult:
        notes: list[str] = []
        matches = []
        for e in evidence:
            if e.label is None:
                continue
            similarity, problems = claim_match(query, e, self.reranker)
            if similarity >= self.match_threshold * 0.8:
                matches.append((similarity, e, problems))
            if problems and similarity >= self.match_threshold:
                notes.append(f"{e.id} looks similar but {'; '.join(problems)}")
        coarse = {e.label.coarse for _, e, problems in matches if not problems}
        conflict = "supported" in coarse and "refuted" in coarse
        if conflict:
            notes.append("closely matching fact-checks disagree")

        usable = [(s, e) for s, e, problems in matches if not problems and s >= self.match_threshold]
        if usable and not conflict:
            similarity, best = max(usable, key=lambda p: p[0])
            when = f" on {best.published:%B} {best.published.day}, {best.published.year}" if best.published else ""
            who = f" (said by {best.speaker})" if best.speaker else ""
            rationale = (f"{best.source} rated a closely matching claim{who} as \"{best.label.display}\"{when}: "
                         f"\"{best.claim.rstrip('.')}\". Read the linked article for the full reasoning.")
            return VerificationResult(text, "claim", best.label, "matched_fact_check", rationale,
                                      citations=[best], evidence=evidence,
                                      notes=notes + [f"claim similarity {similarity:.2f}"])

        if self.llm is not None:
            return self._llm_judgement(text, query, evidence, notes)
        return VerificationResult(
            text, "claim", Label.UNVERIFIABLE, "abstained",
            "No fact-check rates this exact claim. The related fact-checks below may help.",
            evidence=evidence, notes=notes)

    def _llm_judgement(self, text: str, query: str, evidence: list[Evidence],
                       notes: list[str]) -> VerificationResult:
        system = _template("judge_system").substitute()
        user = _template("judge_user").substitute(claim=query, evidence=format_evidence(evidence))
        try:
            data = self.llm.complete_json(task="judge_claim", system=system, user=user, schema=JUDGE_SCHEMA)
        except Exception as exc:  # noqa: BLE001 - never fail a user request because of the LLM
            log.warning("LLM judgement failed: %s", type(exc).__name__)
            return VerificationResult(text, "claim", Label.UNVERIFIABLE, "abstained",
                                      "The verifier is unavailable right now; showing related fact-checks.",
                                      evidence=evidence, notes=notes + ["llm error"])
        by_id = {e.id: e for e in evidence}
        try:
            label = Label(str(data.get("label", "")).strip().lower())
        except ValueError:
            label = None
        citations = [by_id[c] for c in dict.fromkeys(data.get("citations") or []) if c in by_id]
        rationale = str(data.get("rationale", "")).strip()
        invalid_ids = [c for c in data.get("citations") or [] if c not in by_id]
        if invalid_ids:
            notes.append(f"dropped citations to unknown evidence {invalid_ids}")
        if label is None or not rationale or (label != Label.UNVERIFIABLE and not citations):
            return VerificationResult(text, "claim", Label.UNVERIFIABLE, "abstained",
                                      "The model's answer was not properly grounded in the evidence, so I "
                                      "won't give a verdict.", evidence=evidence,
                                      notes=notes + ["llm output failed validation"])
        method = "abstained" if label == Label.UNVERIFIABLE else "llm_judgement"
        return VerificationResult(text, "claim", label, method, rationale, citations=citations,
                                  evidence=evidence, notes=notes)

    # -- questions -----------------------------------------------------------------------------------
    def _answer(self, text: str, query: str, evidence: list[Evidence],
                history: list[dict[str, str]]) -> VerificationResult:
        if self.llm is None:
            titles = "; ".join(f"{e.title} ({e.source})" for e in evidence[:3])
            return VerificationResult(text, "question", Label.UNVERIFIABLE, "evidence_only",
                                      f"Related fact-checks: {titles}.", citations=evidence[:3], evidence=evidence)
        recent = history[-2 * self.history_turns:] if self.history_turns else []
        history_text = "\n".join(f"{m['role']}: {m['content']}" for m in recent) or "(none)"
        system = _template("answer_system").substitute()
        user = _template("answer_user").substitute(history=history_text, question=query,
                                                   evidence=format_evidence(evidence))
        try:
            data = self.llm.complete_json(task="answer_question", system=system, user=user, schema=ANSWER_SCHEMA)
        except Exception as exc:  # noqa: BLE001
            log.warning("LLM answer failed: %s", type(exc).__name__)
            data = {}
        by_id = {e.id: e for e in evidence}
        citations = [by_id[c] for c in dict.fromkeys(data.get("citations") or []) if c in by_id]
        answer = str(data.get("answer", "")).strip()
        if not answer or not citations:
            return VerificationResult(text, "question", Label.UNVERIFIABLE, "evidence_only",
                                      "I can't answer that from the fact-checks I have; here are related ones.",
                                      citations=evidence[:3], evidence=evidence)
        return VerificationResult(text, "question", Label.UNVERIFIABLE, "llm_answer", answer,
                                  citations=citations, evidence=evidence)
