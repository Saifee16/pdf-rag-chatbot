import json
from pathlib import Path

from evaluation.evaluate_retrieval import (
    hit_rate_at_k,
    ndcg_at_k,
    no_answer_false_positive,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)
from evaluation.run_retrieval_benchmark import (
    check_regression,
    evaluate_fixture_report,
    validate_fixture,
)


def fixture() -> dict:
    return json.loads(
        (
            Path(__file__).parents[1] / "evaluation" / "fixtures" / "retrieval_benchmark_v2.json"
        ).read_text(encoding="utf-8")
    )


def test_reciprocal_rank_returns_first_expected_match() -> None:
    assert reciprocal_rank(["a", "b", "c"], {"b", "c"}) == 0.5


def test_reciprocal_rank_returns_zero_for_miss() -> None:
    assert reciprocal_rank(["a", "b"], {"z"}) == 0.0


def test_top_k_metrics_and_negative_queries() -> None:
    assert recall_at_k(["a", "b", "c"], {"b", "c"}, 2) == 0.5
    assert precision_at_k(["a", "b", "c"], {"b", "c"}, 2) == 0.5
    assert hit_rate_at_k(["a", "b"], {"b"}, 2) == 1.0
    assert hit_rate_at_k(["a", "b"], set(), 2) == 0.0
    assert no_answer_false_positive(["a"], set(), True) == 1.0
    assert no_answer_false_positive([], set(), True) == 0.0
    assert ndcg_at_k(["b", "a"], {"b"}, 2) == 1.0


def test_v2_fixture_integrity_and_category_coverage() -> None:
    data = fixture()
    validate_fixture(data)
    assert len(data["cases"]) == 34
    assert len({case["category"] for case in data["cases"]}) >= 12
    assert all("private" not in chunk["text"].lower() for chunk in data["chunks"])


def test_v2_report_is_reproducible_for_quality_metrics() -> None:
    first = evaluate_fixture_report(fixture(), iterations=1)
    second = evaluate_fixture_report(fixture(), iterations=1)
    for mode in ("dense", "hybrid", "hybrid_rerank"):
        for metric in (
            "recall_at_k",
            "precision_at_k",
            "hit_rate_at_k",
            "mrr",
            "ndcg_at_k",
            "no_answer_fp",
        ):
            assert first["modes"][mode][metric] == second["modes"][mode][metric]
    assert first["categories"] == second["categories"]


def test_regression_thresholds_capture_hybrid_quality() -> None:
    report = evaluate_fixture_report(fixture(), iterations=1)
    assert check_regression(report) == []
    degraded = json.loads(json.dumps(report))
    degraded["modes"]["hybrid"]["mrr"] = 0.1
    assert any("hybrid.mrr" in item for item in check_regression(degraded))
