"""Runtime configuration from environment variables (an optional .env file is loaded if present)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Mapping

from .errors import ConfigError

LLM_PROVIDERS = ("none", "fake", "gemini", "openai")
DEFAULT_MODELS = {"gemini": "gemini-2.0-flash", "openai": "gpt-4o-mini", "fake": "fake", "none": ""}


def load_dotenv_if_present(path: str | os.PathLike = ".env") -> bool:
    env_file = Path(path)
    if not env_file.is_file():
        return False
    try:
        from dotenv import load_dotenv
    except ImportError:
        return False
    load_dotenv(env_file, override=False)
    return True


def _num(env: Mapping[str, str], key: str, default, cast, low, high):
    raw = env.get(key, "").strip()
    if not raw:
        return default
    try:
        value = cast(raw)
    except ValueError as exc:
        raise ConfigError(f"{key}={raw!r} is not a valid {cast.__name__}") from exc
    if not low <= value <= high:
        raise ConfigError(f"{key}={value} must be between {low} and {high}")
    return value


@dataclass(frozen=True)
class Settings:
    db_path: Path = Path("data/truthtrace.db")
    llm_provider: str = "none"
    llm_model: str = ""
    google_api_key: str | None = field(default=None, repr=False)
    openai_api_key: str | None = field(default=None, repr=False)
    embedder: str = "hashing"
    reranker: str = "lexical"
    top_k: int = 5
    match_threshold: float = 0.6
    abstain_threshold: float = 0.2
    chunk_words: int = 180
    chunk_overlap: int = 40
    contact_url: str = "https://github.com/KrishnaAnnavaram/truthtrace"
    request_delay: float = 5.0
    max_items: int = 50
    ingest_interval_hours: float = 24.0
    history_turns: int = 4
    log_level: str = "INFO"

    @property
    def user_agent(self) -> str:
        """An honest User-Agent that names the tool and how to reach its maintainer."""
        return f"truthtrace/0.1 (+{self.contact_url})"

    @property
    def model_name(self) -> str:
        return self.llm_model or DEFAULT_MODELS[self.llm_provider]

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        env = os.environ if env is None else env
        provider = env.get("TRUTHTRACE_LLM_PROVIDER", "").strip().lower() or "none"
        if provider not in LLM_PROVIDERS:
            raise ConfigError(f"TRUTHTRACE_LLM_PROVIDER must be one of {LLM_PROVIDERS}, got {provider!r}")
        settings = cls(
            db_path=Path(env.get("TRUTHTRACE_DB_PATH", "").strip() or cls.db_path),
            llm_provider=provider,
            llm_model=env.get("TRUTHTRACE_LLM_MODEL", "").strip(),
            google_api_key=env.get("GOOGLE_API_KEY", "").strip() or None,
            openai_api_key=env.get("OPENAI_API_KEY", "").strip() or None,
            embedder=env.get("TRUTHTRACE_EMBEDDER", "").strip() or cls.embedder,
            reranker=env.get("TRUTHTRACE_RERANKER", "").strip() or cls.reranker,
            top_k=_num(env, "TRUTHTRACE_TOP_K", cls.top_k, int, 1, 20),
            match_threshold=_num(env, "TRUTHTRACE_MATCH_THRESHOLD", cls.match_threshold, float, 0.0, 1.0),
            abstain_threshold=_num(env, "TRUTHTRACE_ABSTAIN_THRESHOLD", cls.abstain_threshold, float, 0.0, 1.0),
            chunk_words=_num(env, "TRUTHTRACE_CHUNK_WORDS", cls.chunk_words, int, 50, 400),
            chunk_overlap=_num(env, "TRUTHTRACE_CHUNK_OVERLAP", cls.chunk_overlap, int, 0, 200),
            contact_url=env.get("TRUTHTRACE_CONTACT_URL", "").strip() or cls.contact_url,
            # Never hammer the sources: at least 2 s between requests, at most one run per hour.
            request_delay=_num(env, "TRUTHTRACE_REQUEST_DELAY", cls.request_delay, float, 2.0, 120.0),
            max_items=_num(env, "TRUTHTRACE_MAX_ITEMS", cls.max_items, int, 1, 500),
            ingest_interval_hours=_num(env, "TRUTHTRACE_INGEST_INTERVAL_HOURS", cls.ingest_interval_hours,
                                       float, 1.0, 24 * 30),
            history_turns=_num(env, "TRUTHTRACE_HISTORY_TURNS", cls.history_turns, int, 0, 20),
            log_level=env.get("TRUTHTRACE_LOG_LEVEL", "").strip().upper() or "INFO",
        )
        if settings.chunk_overlap >= settings.chunk_words:
            raise ConfigError("TRUTHTRACE_CHUNK_OVERLAP must be smaller than TRUTHTRACE_CHUNK_WORDS")
        return settings

    def with_overrides(self, **changes) -> "Settings":
        return replace(self, **changes)

    def api_key_for(self, provider: str) -> str:
        key = {"gemini": self.google_api_key, "openai": self.openai_api_key}.get(provider)
        if not key:
            name = "GOOGLE_API_KEY" if provider == "gemini" else "OPENAI_API_KEY"
            raise ConfigError(f"{name} is not set (needed for TRUTHTRACE_LLM_PROVIDER={provider}). "
                              "Set it in your environment or .env, or use the 'none' or 'fake' provider.")
        return key
