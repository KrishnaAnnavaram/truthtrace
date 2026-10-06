"""Command-line entry point: ``truthtrace {ingest,import,index,check,eval,stats,demo,ui}``."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date
from importlib import resources
from pathlib import Path

from .config import Settings, load_dotenv_if_present
from .errors import ConfigError, TruthTraceError
from .evaluation import evaluate, load_liar_tsv, time_split_examples
from .ingest import import_file, ingest_sources, run_every
from .llm import FakeLLM
from .models import VerificationResult
from .runtime import Services, build_services, configure_logging
from .sources import ADAPTERS

DEMO_CLAIMS = (
    "Maple Hollow cut its library budget by 40 percent",
    "The Riverton bridge will be closed for two years",
    "Lakeside did not remove 50,000 voters from the rolls",
    "Is it true that bus ridership in Maple Hollow recovered?",
    "The moon landing was staged",
)


def _settings(args) -> Settings:
    load_dotenv_if_present()
    settings = Settings.from_env()
    if getattr(args, "db", None):
        settings = settings.with_overrides(db_path=Path(args.db))
    return settings


def print_result(result: VerificationResult, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(result.to_dict(), indent=2, default=str))
        return
    print(f"\n> {result.query}")
    if result.mode == "claim":
        print(f"  verdict: {result.label.display}  [{result.method}]")
    print(f"  {result.rationale}")
    for e in result.citations:
        when = e.published.isoformat() if e.published else "undated"
        rating = f", rated {e.label.display}" if e.label else ""
        print(f"  - [{e.id}] {e.title} ({e.source}, {when}{rating}) {e.url}")
    for note in result.notes:
        print(f"  note: {note}")


def cmd_ingest(args) -> int:
    s = _settings(args)
    services = build_services(s, use_llm_from_settings=False)
    sources = list(ADAPTERS) if args.source == "all" else [args.source]

    def job():
        report = ingest_sources(services.store, services.fetcher(), services.indexer, sources=sources,
                                max_items=args.max_items or s.max_items)
        print(json.dumps(report.to_dict(), indent=2))

    if args.every:
        run_every(args.every, job)
    else:
        job()
    return 0


def cmd_import(args) -> int:
    services = build_services(_settings(args), use_llm_from_settings=False)
    report = import_file(args.path, services.store, services.indexer, source=args.source)
    print(json.dumps(report.to_dict(), indent=2))
    return 0 if not report.errors else 1


def cmd_index(args) -> int:
    services = build_services(_settings(args), use_llm_from_settings=False)
    print(json.dumps(services.indexer.rebuild().to_dict(), indent=2))
    return 0


def cmd_check(args) -> int:
    services = build_services(_settings(args))
    for claim in args.claims:
        print_result(services.verifier.verify(claim), args.json)
    return 0


def cmd_eval(args) -> int:
    services = build_services(_settings(args))
    if args.liar:
        examples, before = load_liar_tsv(args.liar), None
    else:
        before = date.fromisoformat(args.cutoff)
        examples = time_split_examples(services.store, before)
    if args.limit:
        examples = examples[: args.limit]
    if not examples:
        print("no evaluation examples found", file=sys.stderr)
        return 1
    print(json.dumps(evaluate(services.verifier, examples, before=before).to_dict(), indent=2))
    return 0


def cmd_stats(args) -> int:
    services = build_services(_settings(args), use_llm_from_settings=False)
    print(json.dumps({"articles": services.store.count(), "chunks": services.store.chunk_count(),
                      "index_version": services.store.index_version(), "db": str(services.settings.db_path)}))
    return 0


def run_demo(db_path: Path) -> Services:
    """Load the bundled fictional fact-checks into ``db_path`` and return services with the fake LLM."""
    settings = Settings(db_path=db_path, llm_provider="fake")
    services = build_services(settings, llm=FakeLLM())
    with resources.as_file(resources.files("truthtrace").joinpath("demo", "factchecks.jsonl")) as path:
        import_file(path, services.store, services.indexer, source="demo")
    return services


def cmd_demo(args) -> int:
    db = Path(args.db) if args.db else Path("data") / "demo.db"
    services = run_demo(db)
    print(f"demo database: {db} ({services.store.count()} fictional fact-checks)")
    for claim in args.claims or DEMO_CLAIMS:
        print_result(services.verifier.verify(claim))
    return 0


def cmd_ui(args) -> int:
    app = Path(__file__).with_name("ui") / "streamlit_app.py"
    return subprocess.call([sys.executable, "-m", "streamlit", "run", str(app)])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="truthtrace", description="RAG fact-checker grounded in fact-checks.")
    parser.add_argument("--db", help="SQLite database path (default: TRUTHTRACE_DB_PATH or data/truthtrace.db)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("ingest", help="fetch new fact-checks from source feeds (polite, incremental)")
    p.add_argument("--source", choices=["all", *ADAPTERS], default="all")
    p.add_argument("--max-items", type=int, help="maximum article pages to fetch in this run")
    p.add_argument("--every", type=float, help="repeat every N hours (minimum 1)")
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("import", help="import articles from a .jsonl or .csv file")
    p.add_argument("path")
    p.add_argument("--source", default="import")
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("index", help="(re)build chunks and embeddings; safe to run repeatedly")
    p.set_defaults(func=cmd_index)

    p = sub.add_parser("check", help="check one or more claims or questions")
    p.add_argument("claims", nargs="+")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("eval", help="evaluate on a time split of stored claims or a LIAR TSV")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--cutoff", help="YYYY-MM-DD: test on claims published on/after this date")
    group.add_argument("--liar", help="path to a LIAR-format TSV file")
    p.add_argument("--limit", type=int)
    p.set_defaults(func=cmd_eval)

    p = sub.add_parser("stats", help="database statistics")
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("demo", help="offline demo on bundled fictional fact-checks")
    p.add_argument("claims", nargs="*")
    p.set_defaults(func=cmd_demo)

    p = sub.add_parser("ui", help="start the Streamlit chat UI")
    p.set_defaults(func=cmd_ui)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        configure_logging(_settings(args))
        return args.func(args)
    except (ConfigError, TruthTraceError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
