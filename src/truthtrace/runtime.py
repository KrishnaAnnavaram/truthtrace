"""Build the service graph from settings. Heavy objects (models, store, index) are created once."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from .config import Settings
from .embeddings import get_embedder
from .indexing import Indexer
from .llm import LLM, build_llm
from .rerank import Reranker, get_reranker
from .retrieval import HybridRetriever
from .sources import PoliteFetcher
from .storage import Store
from .verify import Verifier


def configure_logging(settings: Settings) -> None:
    logging.basicConfig(level=getattr(logging, settings.log_level, logging.INFO),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@dataclass
class Services:
    settings: Settings
    store: Store
    indexer: Indexer
    retriever: HybridRetriever
    reranker: Reranker
    llm: LLM | None
    verifier: Verifier

    def fetcher(self) -> PoliteFetcher:
        return PoliteFetcher(self.settings.user_agent, min_delay=self.settings.request_delay)


def build_services(settings: Settings, llm: LLM | None = None, *, use_llm_from_settings: bool = True) -> Services:
    store = Store(settings.db_path)
    embedder = get_embedder(settings.embedder)
    reranker = get_reranker(settings.reranker)
    if llm is None and use_llm_from_settings:
        llm = build_llm(settings)
    retriever = HybridRetriever(store, embedder, reranker)
    verifier = Verifier(retriever, reranker, llm, top_k=settings.top_k, match_threshold=settings.match_threshold,
                        abstain_threshold=settings.abstain_threshold, history_turns=settings.history_turns)
    indexer = Indexer(store, embedder, settings.chunk_words, settings.chunk_overlap)
    return Services(settings, store, indexer, retriever, reranker, llm, verifier)
