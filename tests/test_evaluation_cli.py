"""Problems 4 and 12: no evaluation, and docs that didn't match the code."""
import json
from datetime import date

from truthtrace.cli import build_parser, main
from truthtrace.evaluation import Example, evaluate, load_liar_tsv, macro_f1, recall_at_k, time_split_examples
from truthtrace.labels import Label
from truthtrace.models import Article

from conftest import make_services


def test_macro_f1_and_recall():
    assert macro_f1(["a", "b"], ["a", "b"], ["a", "b"]) == 1.0
    assert macro_f1(["a", "a"], ["b", "b"], ["a", "b"]) == 0.0
    assert recall_at_k([["u1", "u2"], ["u3"]], [frozenset({"u2"}), frozenset({"u9"})], k=2) == 0.5
    assert recall_at_k([["u1"]], [frozenset()], k=1) is None


def test_time_split_never_retrieves_the_test_fact_check(tmp_path):
    services = make_services(tmp_path)
    later = Article(url="https://example.org/fc/later", source="demo", title="Later check",
                    claim="Riverton bridge tolls will double next year.", rating="false", published="2025-06-01")
    article_id, _ = services.store.upsert_article(later)
    services.indexer.sync_article(article_id, later)
    services.indexer.embed_pending()

    cutoff = date(2025, 1, 1)
    examples = time_split_examples(services.store, cutoff)
    assert [e.claim for e in examples] == [later.claim]
    for e in services.retriever.search(later.claim, k=10, before=cutoff):
        assert e.published < cutoff and e.url != later.url


def test_evaluate_reports_coverage_accuracy_and_citations(tmp_path):
    services = make_services(tmp_path)
    examples = [
        Example("Maple Hollow cut its library budget by 40 percent this year", Label.MOSTLY_FALSE,
                frozenset({"https://example.org/fc/library"})),
        Example("Solar jobs in Westland doubled over the last five years", Label.TRUE,
                frozenset({"https://example.org/fc/solar"})),
        Example("Penguins can fly over the Sahara", Label.FALSE),
    ]
    report = evaluate(services.verifier, examples)
    assert report.n == 3 and report.coverage == 2 / 3
    assert report.accuracy_answered == 1.0 and report.coarse_macro_f1_answered == 1.0
    assert report.recall_at_k == 1.0 and report.citation_support == 1.0
    assert report.methods == {"matched_fact_check": 2, "abstained": 1}


def test_load_liar_tsv(tmp_path):
    path = tmp_path / "liar.tsv"
    path.write_text("1.json\tpants-fire\tA made-up statement.\ttopic\tsomeone\n"
                    "2.json\tbarely-true\tAnother made-up statement.\ttopic\tsomeone\n"
                    "bad row\n", encoding="utf-8")
    assert [e.gold for e in load_liar_tsv(path)] == [Label.PANTS_ON_FIRE, Label.MOSTLY_FALSE]


def test_cli_commands_match_the_readme():
    commands = set(build_parser()._subparsers._group_actions[0].choices)
    assert commands == {"ingest", "import", "index", "check", "eval", "stats", "demo", "ui"}


def test_cli_demo_check_and_eval(tmp_path, capsys):
    db = str(tmp_path / "demo.db")
    assert main(["--db", db, "demo", "The Riverton bridge will be closed for two years"]) == 0
    out = capsys.readouterr().out
    assert "verdict: False" in out and "matched_fact_check" in out

    assert main(["--db", db, "check", "--json", "Maple Hollow cut its library budget by 40 percent"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["label"] == "mostly_false" and result["citations"]

    assert main(["--db", db, "eval", "--cutoff", "2025-01-01"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["n"] == 4 and 0 <= report["coverage"] <= 1

    assert main(["--db", db, "index"]) == 0
    assert json.loads(capsys.readouterr().out)["chunks_changed"] == 0  # idempotent
