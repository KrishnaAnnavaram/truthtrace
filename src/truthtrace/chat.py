"""Chat session: one bounded history per session, and each new message is sent exactly once.

The history passed to the verifier holds only *previous* turns; the current message travels
separately. It is capped by turn count and characters, so long chats don't grow the prompt.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .models import VerificationResult
from .verify import Verifier


class BoundedHistory:
    def __init__(self, max_turns: int = 4, max_chars: int = 4000):
        self.max_messages = max(0, 2 * max_turns)
        self.max_chars = max_chars
        self._messages: list[dict[str, str]] = []

    def add(self, role: str, content: str) -> None:
        self._messages.append({"role": role, "content": content})
        while len(self._messages) > self.max_messages:
            self._messages.pop(0)
        while self._messages and sum(len(m["content"]) for m in self._messages) > self.max_chars:
            self._messages.pop(0)

    def messages(self) -> list[dict[str, str]]:
        return [dict(m) for m in self._messages]

    def __len__(self) -> int:
        return len(self._messages)


def summarize(result: VerificationResult) -> str:
    """Short assistant text kept in history (not the whole evidence dump)."""
    if result.mode == "claim":
        return f"{result.label.display}: {result.rationale}"
    return result.rationale


@dataclass
class ChatSession:
    verifier: Verifier
    history: BoundedHistory = field(default_factory=BoundedHistory)
    results: list[VerificationResult] = field(default_factory=list)

    def send(self, message: str) -> VerificationResult:
        result = self.verifier.verify(message, history=self.history.messages())
        self.history.add("user", message)
        self.history.add("assistant", summarize(result))
        self.results.append(result)
        return result
