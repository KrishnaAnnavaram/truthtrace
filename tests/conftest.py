from __future__ import annotations

import pytest

from truthtrace.config import Settings
from truthtrace.llm import FakeLLM
from truthtrace.models import Article
from truthtrace.runtime import build_services

# Tiny synthetic fact-checks about fictional places and people (written for these tests).
ARTICLES = [
    Article(url="https://example.org/fc/library", source="demo", title="Library budget claim",
            claim="Maple Hollow cut its library budget by 40 percent this year.", speaker="Dana Reyes",
            rating="mostly-false", published="2024-03-12",
            body="Budget documents show the library line fell 15 percent. The larger figure counts a one-time grant."),
    Article(url="https://example.org/fc/bridge", source="demo", title="Bridge closure claim",
            claim="The Riverton bridge will be closed to all traffic for two years.", speaker="Sam Patel",
            rating="false", published="2024-05-02",
            body="The schedule closes the bridge to cars for 14 weeks. Pedestrian lanes stay open."),
    Article(url="https://example.org/fc/solar", source="demo", title="Solar jobs claim",
            claim="Solar jobs in Westland doubled over the last five years.", speaker="Ada Rivera",
            rating="true", published="2024-06-18",
            body="Labor department data show solar jobs rose from 6,100 to 12,400 between 2019 and 2024."),
    Article(url="https://example.org/fc/explainer", source="demo", title="How bridge inspections work",
            body="Inspectors rate each bridge deck every two years and publish the reports online.",
            published="2024-07-01"),
]


def make_services(tmp_path, llm=None, **overrides):
    settings = Settings(db_path=tmp_path / "tt.db", llm_provider="none", **overrides)
    services = build_services(settings, llm=llm, use_llm_from_settings=False)
    for article in ARTICLES:
        article_id, _ = services.store.upsert_article(article)
        services.indexer.sync_article(article_id, article)
    services.indexer.embed_pending()
    return services


@pytest.fixture
def services(tmp_path):
    return make_services(tmp_path)


@pytest.fixture
def services_llm(tmp_path):
    return make_services(tmp_path, llm=FakeLLM())
