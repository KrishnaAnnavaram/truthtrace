"""Problems 3, 7 and 8: invented confidence, per-query model loading, duplicated queries in prompts."""
import pytest

from truthtrace.chat import BoundedHistory, ChatSession
from truthtrace.embeddings import get_embedder
from truthtrace.labels import Label
from truthtrace.llm import FakeLLM
from truthtrace.models import Article
from truthtrace.verify import classify_query

from conftest import make_services


class StubLLM:
    name = "stub"

    def __init__(self, response):
        self.response, self.calls = response, []

    def complete_json(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


@pytest.mark.parametrize("text, mode, query", [
    ("Solar jobs doubled in Westland", "claim", "Solar jobs doubled in Westland"),
    ("Is it true that solar jobs doubled?", "claim", "solar jobs doubled"),
    ("Fact check: the bridge closes for two years", "claim", "the bridge closes for two years"),
    ("Who checked the bridge claim?", "question", "Who checked the bridge claim?"),
    ("What did the library article find", "question", "What did the library article find"),
])
def test_classify_query(text, mode, query):
    assert classify_query(text) == (mode, query)


def test_matching_claim_returns_the_expert_rating(services):
    result = services.verifier.verify("Maple Hollow cut its library budget by 40 percent")
    assert result.method == "matched_fact_check" and result.label == Label.MOSTLY_FALSE
    assert result.citations[0].url == "https://example.org/fc/library"
    assert "%" not in result.rationale and "100" not in result.rationale  # no invented confidence


def test_negated_claim_is_not_given_the_original_rating(services):
    result = services.verifier.verify("Maple Hollow did not cut its library budget by 40 percent")
    assert result.method == "abstained" and result.label == Label.UNVERIFIABLE
    assert any("negated" in n for n in result.notes)


def test_different_numbers_block_a_direct_match(services):
    result = services.verifier.verify("Maple Hollow cut its library budget by 15 percent this year")
    assert result.method != "matched_fact_check"
    assert any("numbers differ" in n for n in result.notes)


def test_unrelated_claim_abstains(services):
    result = services.verifier.verify("Penguins can fly over the Sahara")
    assert result.abstained and result.label == Label.UNVERIFIABLE and not result.citations


def test_conflicting_fact_checks_are_not_resolved_silently(tmp_path):
    services = make_services(tmp_path)
    twin = Article(url="https://example.org/fc/solar-2", source="demo", title="Solar jobs, again",
                   claim="Solar jobs in Westland doubled over the last five years.", rating="false",
                   published="2025-01-01")
    article_id, _ = services.store.upsert_article(twin)
    services.indexer.sync_article(article_id, twin)
    services.indexer.embed_pending()
    result = services.verifier.verify("Solar jobs in Westland doubled over the last five years")
    assert result.abstained and any("disagree" in n for n in result.notes)


def test_llm_verdict_must_be_on_scale_and_cited(tmp_path):
    bad_label = StubLLM({"label": "True (100%)", "rationale": "Sure.", "citations": ["E1"]})
    services = make_services(tmp_path, llm=bad_label)
    result = services.verifier.verify("Pedestrian lanes on the Riverton bridge stay open")
    assert bad_label.calls and result.abstained

    uncited = StubLLM({"label": "true", "rationale": "Trust me.", "citations": ["E9"]})
    services = make_services(tmp_path / "b", llm=uncited)
    result = services.verifier.verify("Pedestrian lanes on the Riverton bridge stay open")
    assert result.abstained and any("unknown evidence" in n for n in result.notes)

    good = StubLLM({"label": "true", "rationale": "E1 says the lanes stay open.", "citations": ["E1"]})
    services = make_services(tmp_path / "c", llm=good)
    result = services.verifier.verify("Pedestrian lanes on the Riverton bridge stay open")
    assert result.method == "llm_judgement" and result.label == Label.TRUE and result.citations


def test_llm_errors_degrade_to_abstention(tmp_path):
    class Broken:
        name = "broken"

        def complete_json(self, **kwargs):
            raise TimeoutError("provider down")

    services = make_services(tmp_path, llm=Broken())
    result = services.verifier.verify("Pedestrian lanes on the Riverton bridge stay open")
    assert result.abstained and "llm error" in result.notes


def test_models_and_index_load_once(services):
    assert get_embedder("hashing") is get_embedder("hashing")
    for q in ["bridge", "library budget", "solar jobs", "inspections"]:
        services.retriever.search(q)
    assert services.retriever.loads == 1
    services.store.upsert_article(Article(url="https://example.org/new", source="demo", title="New one"))
    services.retriever.search("new one")
    assert services.retriever.loads == 2  # reloaded only because the index changed


def test_query_is_sent_once_and_history_is_bounded(tmp_path):
    llm = FakeLLM()
    services = make_services(tmp_path, llm=llm)
    chat = ChatSession(services.verifier, BoundedHistory(max_turns=2))
    for i in range(5):
        chat.send(f"What did inspectors find about bridge decks, round {i}?")
    prompt = llm.calls[-1]["user"]
    assert prompt.count("round 4") == 1  # the current question appears exactly once
    assert "round 0" not in prompt and "round 1" not in prompt  # old turns were dropped
    assert len(chat.history) == 4


def test_questions_without_llm_return_related_evidence(services):
    result = services.verifier.verify("What do bridge inspectors publish?")
    assert result.mode == "question" and result.method == "evidence_only" and result.citations
