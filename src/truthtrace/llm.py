"""LLM providers behind one small interface (JSON in, JSON out, temperature 0)."""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Protocol, runtime_checkable

from .config import Settings
from .errors import ConfigError, MissingDependency, TransientError
from .text import has_negation

log = logging.getLogger(__name__)


@runtime_checkable
class LLM(Protocol):
    name: str

    def complete_json(self, *, task: str, system: str, user: str, schema: dict[str, Any],
                      max_tokens: int = 800) -> dict[str, Any]:
        ...


def _parse_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")
    return data


def _retry(call, attempts: int = 3, base_delay: float = 2.0):
    for attempt in range(1, attempts + 1):
        try:
            return call()
        except TransientError:
            if attempt == attempts:
                raise
            time.sleep(base_delay * 2 ** (attempt - 1))
    raise AssertionError("unreachable")  # pragma: no cover


class GeminiLLM:
    def __init__(self, api_key: str, model: str = "gemini-2.0-flash"):
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise MissingDependency("google-genai", "gemini") from exc
        self._client, self._types = genai.Client(api_key=api_key), types
        self.model, self.name = model, f"gemini:{model}"

    def complete_json(self, *, task, system, user, schema, max_tokens=800):
        config = self._types.GenerateContentConfig(
            system_instruction=system, temperature=0.0, max_output_tokens=max_tokens,
            response_mime_type="application/json")

        def call():
            try:
                return self._client.models.generate_content(model=self.model, contents=user, config=config)
            except Exception as exc:  # the SDK raises several error types; retry only server-side ones
                if any(code in str(exc) for code in ("429", "500", "503", "UNAVAILABLE", "RESOURCE_EXHAUSTED")):
                    raise TransientError(str(exc)[:200]) from exc
                raise

        response = _retry(call)
        log.info("LLM %s done", task)
        return _parse_json(response.text)


class OpenAILLM:
    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        try:
            import openai
        except ImportError as exc:
            raise MissingDependency("openai", "openai") from exc
        self._openai = openai
        self._client = openai.OpenAI(api_key=api_key, max_retries=0)
        self.model, self.name = model, f"openai:{model}"

    def complete_json(self, *, task, system, user, schema, max_tokens=800):
        transient = (self._openai.RateLimitError, self._openai.APIConnectionError,
                     self._openai.APITimeoutError, self._openai.InternalServerError)

        def call():
            try:
                return self._client.chat.completions.create(
                    model=self.model, temperature=0, max_completion_tokens=max_tokens,
                    messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                    response_format={"type": "json_schema",
                                     "json_schema": {"name": task, "schema": schema, "strict": True}})
            except transient as exc:
                raise TransientError(type(exc).__name__) from exc

        response = _retry(call)
        log.info("LLM %s: %s completion tokens", task, getattr(response.usage, "completion_tokens", "?"))
        return _parse_json(response.choices[0].message.content or "")


_EVIDENCE_LINE = re.compile(r"^\[(E\d+)\][^\n]*?rating: ([^\n|]*)", re.M)


class FakeLLM:
    """Deterministic stand-in used by tests and the offline demo.

    For claims it adopts the rating of the first rated evidence item and cites it; for questions
    it quotes the first evidence passage. It never sees the network.
    """

    name = "fake"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def complete_json(self, *, task, system, user, schema, max_tokens=800):
        self.calls.append({"task": task, "system": system, "user": user})
        rated = [(eid, r.strip()) for eid, r in _EVIDENCE_LINE.findall(user) if r.strip() not in ("", "none")]
        ids = re.findall(r"^\[(E\d+)\]", user, re.M)
        if task == "judge_claim":
            if not rated:
                return {"label": "unverifiable", "rationale": "None of the evidence rates this claim.",
                        "citations": []}
            eid, rating = rated[0]
            claim = re.search(r"Claim to check:\n(.+)", user)
            checked = re.search(rf"^\[{eid}\][^\n]*\nclaim checked: (.+)$", user, re.M)
            if claim and checked and has_negation(claim.group(1)) != has_negation(checked.group(1)):
                return {"label": "unverifiable", "citations": [eid],
                        "rationale": f"[{eid}] checked the opposite statement, so its rating does not transfer."}
            label = rating.lower().replace(" ", "_")
            return {"label": label, "rationale": f"The closest fact-check [{eid}] rated a related claim {rating}.",
                    "citations": [eid]}
        if task == "answer_question":
            if not ids:
                return {"answer": "I could not find fact-checks about that.", "citations": []}
            return {"answer": f"According to the fact-check [{ids[0]}], see the cited article for details.",
                    "citations": [ids[0]]}
        raise ValueError(f"FakeLLM does not know task {task!r}")


def build_llm(settings: Settings) -> LLM | None:
    provider = settings.llm_provider
    if provider == "none":
        return None
    if provider == "fake":
        return FakeLLM()
    if provider == "gemini":
        return GeminiLLM(settings.api_key_for("gemini"), settings.model_name)
    if provider == "openai":
        return OpenAILLM(settings.api_key_for("openai"), settings.model_name)
    raise ConfigError(f"unknown LLM provider {provider!r}")
