"""truthtrace: a retrieval-augmented fact-checker grounded in professional fact-checks.

Pipeline: ingest (polite, incremental) -> SQLite store (upsert by URL) -> chunk + embed (upsert by
chunk id) -> hybrid retrieval + rerank -> verdict (matched fact-check, LLM judgement with
citations, or abstain).
"""

__version__ = "0.1.0"
