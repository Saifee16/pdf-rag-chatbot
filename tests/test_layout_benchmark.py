import json
from pathlib import Path

from evaluation.run_layout_benchmark import check_regression, evaluate_fixture, validate_fixture


def test_layout_fixture_contains_required_safe_cases() -> None:
    fixture_path = Path(__file__).parents[1] / "evaluation" / "fixtures" / "layout_benchmark.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    validate_fixture(fixture)
    assert len(fixture["cases"]) == 10


def test_layout_benchmark_shows_structure_gain_without_retrieval_regression() -> None:
    fixture_path = Path(__file__).parents[1] / "evaluation" / "fixtures" / "layout_benchmark.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    report = evaluate_fixture(fixture)

    assert check_regression(report) == []
    by_kind = {scenario["kind"]: scenario for scenario in report["scenarios"]}
    assert (
        by_kind["two_column"]["layout_aware_extraction"]["structured_content_preservation"] == 1.0
    )
    assert by_kind["table"]["layout_aware_extraction"]["table_answer_retrieval_accuracy"] == 1.0
    assert by_kind["mixed"]["layout_aware_extraction"]["citation_page_accuracy"] == 1.0
