"""Labels, dates, text helpers, BM25, config."""
from datetime import date

import pytest

from truthtrace.bm25 import BM25
from truthtrace.config import Settings
from truthtrace.dates import parse_date
from truthtrace.errors import ConfigError
from truthtrace.labels import Label, normalize_rating
from truthtrace.llm import FakeLLM, build_llm
from truthtrace.rerank import LexicalReranker
from truthtrace.text import has_negation, numbers_in


@pytest.mark.parametrize("raw, label", [
    ("pants-fire", Label.PANTS_ON_FIRE), ("Pants on Fire!", Label.PANTS_ON_FIRE), ("barely-true", Label.MOSTLY_FALSE),
    ("Mostly True", Label.MOSTLY_TRUE), ("half-true", Label.HALF_TRUE), ("FALSE", Label.FALSE),
    ("full-flop", None), ("", None), ("misleading", None),
])
def test_normalize_rating(raw, label):
    assert normalize_rating(raw) == label


def test_coarse_groups():
    assert Label.MOSTLY_TRUE.coarse == "supported" and Label.PANTS_ON_FIRE.coarse == "refuted"
    assert Label.HALF_TRUE.coarse == "mixed"


@pytest.mark.parametrize("text, expected", [
    ("2024-05-02T10:00:00Z", date(2024, 5, 2)), ("September 3, 2024", date(2024, 9, 3)),
    ("Sept. 3, 2024", date(2024, 9, 3)), ("Thu, 02 May 2024 10:00:00 -0400", date(2024, 5, 2)),
    ("stated on May 2, 2024 in a post", date(2024, 5, 2)), ("9/3/2024", date(2024, 9, 3)),
    ("No date found", None), (None, None),
])
def test_parse_date(text, expected):
    assert parse_date(text) == expected


def test_negation_and_numbers():
    assert has_negation("The bridge will not close") and has_negation("They didn't")
    assert not has_negation("The bridge will close")
    assert numbers_in("Up 1,000 jobs or 40.5%") == {"1000", "40.5"}


def test_bm25_prefers_matching_documents():
    bm = BM25(["solar jobs doubled", "bridge closed for weeks", "library budget cut"])
    assert bm.top("bridge closure", 1)[0][0] == 1


def test_lexical_reranker_bounds():
    r = LexicalReranker()
    same, other = r.score("solar jobs doubled", ["solar jobs doubled", "penguins fly"])
    assert same == pytest.approx(1.0) and other == 0.0


def test_settings_from_env_and_validation():
    s = Settings.from_env({"TRUTHTRACE_LLM_PROVIDER": "fake", "TRUTHTRACE_TOP_K": "3", "GOOGLE_API_KEY": "placeholder"})
    assert s.llm_provider == "fake" and s.top_k == 3 and "placeholder" not in repr(s)
    assert isinstance(build_llm(s), FakeLLM)
    assert build_llm(Settings()) is None  # default: no LLM, verdicts only from matched fact-checks
    with pytest.raises(ConfigError):
        Settings.from_env({"TRUTHTRACE_REQUEST_DELAY": "0.1"})  # too aggressive
    with pytest.raises(ConfigError):
        Settings.from_env({"TRUTHTRACE_CHUNK_WORDS": "100", "TRUTHTRACE_CHUNK_OVERLAP": "150"})
    with pytest.raises(ConfigError, match="GOOGLE_API_KEY"):
        build_llm(Settings(llm_provider="gemini"))
    assert "Mozilla" not in Settings().user_agent
