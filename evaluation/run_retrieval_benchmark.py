from __future__ import annotations

import argparse
import json
import statistics
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from app.services.hybrid_retrieval import reciprocal_rank_fusion
from app.services.lexical_retrieval import tokenize
from app.services.reranking_service import DeterministicReranker
from app.services.retrieval_confidence import RetrievalConfidenceService
from app.services.vector_store import VectorHit
from evaluation.evaluate_retrieval import (
    hit_rate_at_k,
    ndcg_at_k,
    no_answer_false_positive,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)

MODES = ("dense", "hybrid", "hybrid_rerank")
CATEGORIES = {
    "exact_lexical",
    "synonym_paraphrase",
    "semantic_low_keyword",
    "keyword_distractor",
    "semantic_distractor",
    "multiple_relevant",
    "split_answer",
    "repeated_terminology",
    "rare_entity",
    "numeric_date",
    "no_answer",
    "dense_wins",
    "lexical_wins",
    "hybrid_wins",
    "rerank_candidate",
}
METRICS = ("recall_at_k", "precision_at_k", "hit_rate_at_k", "mrr", "ndcg_at_k", "no_answer_fp")


def _lexical_hits(question: str, chunks: list[dict[str, str]]) -> list[VectorHit]:
    query = set(tokenize(question))
    scored: list[tuple[float, str, dict[str, str]]] = []
    for chunk in chunks:
        tokens = set(tokenize(chunk["text"]))
        overlap = len(query & tokens)
        if overlap:
            scored.append((overlap / max(len(query), 1), chunk["id"], chunk))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [
        VectorHit(id=chunk["id"], score=score, payload={"text": chunk["text"]})
        for score, _, chunk in scored
    ]


def _dense_hits(
    order: list[str],
    chunks_by_id: dict[str, dict[str, str]],
    scores: dict[str, float] | None = None,
) -> list[VectorHit]:
    return [
        VectorHit(
            id=chunk_id,
            score=(scores or {}).get(chunk_id, 1.0 - (rank * 0.01)),
            payload={"text": chunks_by_id[chunk_id]["text"]},
        )
        for rank, chunk_id in enumerate(order)
    ]


def validate_fixture(fixture: dict[str, Any]) -> None:
    """Validate the public, synthetic benchmark contract before evaluating it."""
    if fixture.get("version") != 2:
        raise ValueError("Benchmark fixture must declare version 2")
    top_k = int(fixture.get("top_k", 0))
    chunks = fixture.get("chunks")
    cases = fixture.get("cases")
    if top_k < 1 or not isinstance(chunks, list) or not chunks:
        raise ValueError("Benchmark fixture needs a positive top_k and chunks")
    if not isinstance(cases, list) or len(cases) < 25:
        raise ValueError("Benchmark fixture must contain at least 25 cases")
    chunk_ids = [str(chunk.get("id", "")) for chunk in chunks]
    if any(not item for item in chunk_ids) or len(chunk_ids) != len(set(chunk_ids)):
        raise ValueError("Benchmark chunk IDs must be non-empty and unique")
    chunk_id_set = set(chunk_ids)
    seen_categories: set[str] = set()
    for case in cases:
        category = str(case.get("category", ""))
        seen_categories.add(category)
        if category not in CATEGORIES:
            raise ValueError(f"Unknown benchmark category: {category}")
        relevant = set(case.get("relevant_ids", []))
        if not relevant.issubset(chunk_id_set):
            raise ValueError(f"Case {case.get('id')} references an unknown relevant chunk")
        order = list(case.get("dense_order", []))
        if set(order) != chunk_id_set or len(order) != len(chunk_ids):
            raise ValueError(f"Case {case.get('id')} must rank every chunk exactly once")
        if category == "no_answer" and (relevant or not case.get("expected_no_answer")):
            raise ValueError("No-answer cases must have no relevant IDs and be marked negative")
        scores = case.get("dense_scores")
        if scores is not None:
            if set(scores) != chunk_id_set or any(
                not 0 <= float(value) <= 1 for value in scores.values()
            ):
                raise ValueError(f"Case {case.get('id')} has invalid dense scores")
    if len(seen_categories) < 12:
        raise ValueError("Benchmark fixture must cover at least 12 categories")


def _split_for_case(case: dict[str, Any]) -> str:
    """Stable split independent of query text or observed scores."""
    digits = "".join(char for char in str(case["id"]) if char.isdigit())
    number = int(digits or 0)
    return "held_out" if number % 4 == 0 else "calibration"


def _outputs_for_case(
    case: dict[str, Any],
    chunks_by_id: dict[str, dict[str, str]],
    reranker: DeterministicReranker,
    top_k: int,
) -> dict[str, list[VectorHit]]:
    dense = _dense_hits(list(case["dense_order"]), chunks_by_id, case.get("dense_scores"))
    lexical = _lexical_hits(str(case["question"]), list(chunks_by_id.values()))
    fused = reciprocal_rank_fusion(dense, lexical, limit=min(len(dense), 20))
    return {
        "dense": dense[:top_k],
        "hybrid": reciprocal_rank_fusion(dense, lexical, limit=top_k),
        "hybrid_rerank": reranker.rerank(str(case["question"]), fused, top_k),
    }


def _empty_scores() -> dict[str, float]:
    return {metric: 0.0 for metric in METRICS}


def _score_case(
    returned: list[str], expected: set[str], expected_no_answer: bool, top_k: int
) -> dict[str, float]:
    return {
        "recall_at_k": recall_at_k(returned, expected, top_k),
        "precision_at_k": precision_at_k(returned, expected, top_k),
        "hit_rate_at_k": hit_rate_at_k(returned, expected, top_k),
        "mrr": reciprocal_rank(returned[:top_k], expected),
        "ndcg_at_k": ndcg_at_k(returned, expected, top_k),
        "no_answer_fp": no_answer_false_positive(returned[:top_k], expected, expected_no_answer),
    }


def _percentile(samples: list[float], percentile: float) -> float:
    if not samples:
        return 0.0
    if len(samples) == 1:
        return samples[0]
    return statistics.quantiles(samples, n=100, method="inclusive")[int(percentile) - 1]


def _average_scores(scores: list[dict[str, float]]) -> dict[str, float]:
    if not scores:
        return _empty_scores()
    return {
        metric: round(sum(item[metric] for item in scores) / len(scores), 6) for metric in METRICS
    }


def evaluate_fixture_report(fixture: dict[str, Any], *, iterations: int = 20) -> dict[str, Any]:
    """Evaluate all retrieval modes and return quality, category, and latency evidence."""
    validate_fixture(fixture)
    top_k = int(fixture["top_k"])
    chunks = list(fixture["chunks"])
    chunks_by_id = {chunk["id"]: chunk for chunk in chunks}
    reranker = DeterministicReranker()
    mode_scores: dict[str, list[dict[str, float]]] = defaultdict(list)
    category_scores: dict[str, dict[str, list[dict[str, float]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    latency: dict[str, list[float]] = defaultdict(list)
    query_results: list[dict[str, Any]] = []
    for case in fixture["cases"]:
        expected = set(case["relevant_ids"])
        expected_no_answer = bool(case.get("expected_no_answer", False))
        outputs = _outputs_for_case(case, chunks_by_id, reranker, top_k)
        query_record: dict[str, Any] = {
            "id": case["id"],
            "category": case["category"],
            "expected_no_answer": expected_no_answer,
            "returned": {},
        }
        for mode, output in outputs.items():
            returned = [hit.id for hit in output]
            scores = _score_case(returned, expected, expected_no_answer, top_k)
            mode_scores[mode].append(scores)
            category_scores[str(case["category"])][mode].append(scores)
            query_record["returned"][mode] = returned
            started = time.perf_counter()
            for _ in range(iterations):
                if mode == "dense":
                    _dense_hits(list(case["dense_order"]), chunks_by_id, case.get("dense_scores"))[
                        :top_k
                    ]
                elif mode == "hybrid":
                    _outputs_for_case(case, chunks_by_id, reranker, top_k)["hybrid"]
                else:
                    _outputs_for_case(case, chunks_by_id, reranker, top_k)["hybrid_rerank"]
            latency[mode].append((time.perf_counter() - started) * 1000 / iterations)
        query_results.append(query_record)
    modes = {}
    for mode in MODES:
        modes[mode] = _average_scores(mode_scores[mode])
        modes[mode]["latency_p50_ms"] = round(_percentile(latency[mode], 50), 6)
        modes[mode]["latency_p95_ms"] = round(_percentile(latency[mode], 95), 6)
    categories = {
        category: {mode: _average_scores(category_scores[category][mode]) for mode in MODES}
        for category in sorted(category_scores)
    }
    return {
        "fixture_version": fixture["version"],
        "query_count": len(fixture["cases"]),
        "chunk_count": len(chunks),
        "top_k": top_k,
        "modes": modes,
        "categories": categories,
        "queries": query_results,
    }


def _abstention_metrics(records: list[dict[str, Any]], top_k: int) -> dict[str, float]:
    if not records:
        return {
            "abstention_rate": 0.0,
            "specificity": 0.0,
            "negative_fp": 0.0,
            "positive_false_abstain": 0.0,
            "precision_accepted": 0.0,
            "recall_at_k": 0.0,
            "mrr": 0.0,
            "ndcg_at_k": 0.0,
        }
    negatives = [record for record in records if record["expected_no_answer"]]
    positives = [record for record in records if not record["expected_no_answer"]]
    quality: list[dict[str, float]] = []
    relevant_returned = 0
    returned_count = 0
    for record in positives:
        returned = record["returned"] if record["accepted"] else []
        expected = set(record["expected_ids"])
        quality.append(_score_case(returned, expected, False, top_k))
        relevant_returned += len(set(returned[:top_k]) & expected)
        returned_count += len(returned[:top_k])
    return {
        "abstention_rate": round(sum(not item["accepted"] for item in records) / len(records), 6),
        "specificity": round(sum(not item["accepted"] for item in negatives) / len(negatives), 6)
        if negatives
        else 0.0,
        "negative_fp": round(sum(item["accepted"] for item in negatives) / len(negatives), 6)
        if negatives
        else 0.0,
        "positive_false_abstain": round(
            sum(not item["accepted"] for item in positives) / len(positives), 6
        )
        if positives
        else 0.0,
        "precision_accepted": round(relevant_returned / returned_count, 6)
        if returned_count
        else 0.0,
        "recall_at_k": round(sum(item["recall_at_k"] for item in quality) / len(quality), 6)
        if quality
        else 0.0,
        "mrr": round(sum(item["mrr"] for item in quality) / len(quality), 6) if quality else 0.0,
        "ndcg_at_k": round(sum(item["ndcg_at_k"] for item in quality) / len(quality), 6)
        if quality
        else 0.0,
    }


def _evaluate_abstention_split(
    fixture: dict[str, Any], *, threshold: float, split: str, iterations: int = 1
) -> dict[str, Any]:
    top_k = int(fixture["top_k"])
    chunks_by_id = {chunk["id"]: chunk for chunk in fixture["chunks"]}
    reranker = DeterministicReranker()
    records: dict[str, list[dict[str, Any]]] = defaultdict(list)
    confidence = RetrievalConfidenceService(enabled=True, threshold=threshold)
    latency: dict[str, list[float]] = defaultdict(list)
    for case in fixture["cases"]:
        if _split_for_case(case) != split:
            continue
        outputs = _outputs_for_case(case, chunks_by_id, reranker, top_k)
        expected = set(case["relevant_ids"])
        for mode, hits in outputs.items():
            decision = confidence.decide(hits, mode=mode)
            returned = [hit.id for hit in hits]
            records[mode].append(
                {
                    "id": case["id"],
                    "expected_ids": list(expected),
                    "expected_no_answer": bool(case.get("expected_no_answer", False)),
                    "returned": returned,
                    "accepted": decision.accepted,
                    "confidence": decision.confidence,
                }
            )
            started = time.perf_counter()
            for _ in range(iterations):
                confidence.decide(hits, mode=mode)
            latency[mode].append((time.perf_counter() - started) * 1000 / iterations)
    return {
        mode: {
            **_abstention_metrics(records[mode], top_k),
            "latency_p50_ms": round(_percentile(latency[mode], 50), 6),
            "latency_p95_ms": round(_percentile(latency[mode], 95), 6),
            "query_count": len(records[mode]),
            "negative_count": sum(item["expected_no_answer"] for item in records[mode]),
        }
        for mode in MODES
    }


def _calibration_rows(fixture: dict[str, Any]) -> list[dict[str, float]]:
    rows = []
    for threshold in (0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.55):
        result = _evaluate_abstention_split(fixture, threshold=threshold, split="calibration")
        hybrid = result["hybrid"]
        rows.append(
            {
                "threshold": threshold,
                "negative_fp": hybrid["negative_fp"],
                "positive_false_abstain": hybrid["positive_false_abstain"],
                "recall_at_k": hybrid["recall_at_k"],
                "mrr": hybrid["mrr"],
                "ndcg_at_k": hybrid["ndcg_at_k"],
            }
        )
    return rows


def _choose_threshold(rows: list[dict[str, float]]) -> float:
    eligible = [row for row in rows if row["positive_false_abstain"] <= 0.10]
    pool = eligible or rows
    return min(
        pool,
        key=lambda row: (
            row["negative_fp"],
            -row["recall_at_k"],
            -row["mrr"],
            -row["ndcg_at_k"],
            abs(row["threshold"] - 0.50),
            row["threshold"],
        ),
    )["threshold"]


def evaluate_abstention_report(fixture: dict[str, Any], *, iterations: int = 20) -> dict[str, Any]:
    validate_fixture(fixture)
    calibration_rows = _calibration_rows(fixture)
    chosen_threshold = _choose_threshold(calibration_rows)
    calibration = _evaluate_abstention_split(
        fixture, threshold=chosen_threshold, split="calibration", iterations=iterations
    )
    held_out = _evaluate_abstention_split(
        fixture, threshold=chosen_threshold, split="held_out", iterations=iterations
    )
    return {
        "split_method": "case numeric suffix modulo 4; suffix divisible by 4 is held_out",
        "chosen_threshold": chosen_threshold,
        "calibration_candidates": calibration_rows,
        "calibration": calibration,
        "held_out": held_out,
        "held_out_without_abstention": _evaluate_abstention_split(
            fixture, threshold=0.0, split="held_out", iterations=iterations
        ),
    }


def evaluate_fixture(
    fixture: dict[str, object], *, iterations: int = 20
) -> dict[str, dict[str, float]]:
    """Cycle 1-compatible summary retained for callers that only need mode metrics."""
    return evaluate_fixture_report(fixture, iterations=iterations)["modes"]


def check_regression(report: dict[str, Any], baseline: dict[str, Any] | None = None) -> list[str]:
    """Return quality regressions; latency is reported but deliberately not gated."""
    abstention = report.get("abstention")
    if not abstention:
        return []
    errors: list[str] = []
    if abstention:
        held_out = abstention["held_out"]["hybrid"]
        if held_out["negative_fp"] > 0.20:
            errors.append(f"hybrid held-out negative_fp={held_out['negative_fp']:.4f} > 0.2000")
        if held_out["positive_false_abstain"] > 0.20:
            errors.append(
                "hybrid held-out positive_false_abstain="
                f"{held_out['positive_false_abstain']:.4f} > 0.2000"
            )
        baseline_held_out = abstention["held_out_without_abstention"]["hybrid"]
        for metric in ("recall_at_k", "mrr", "ndcg_at_k"):
            if held_out[metric] + 0.05 < baseline_held_out[metric]:
                errors.append(
                    f"hybrid held-out {metric} regressed by more than 0.05 "
                    f"({baseline_held_out[metric]:.4f} -> {held_out[metric]:.4f})"
                )
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the deterministic retrieval quality benchmark."
    )
    parser.add_argument(
        "--fixture",
        type=Path,
        default=Path(__file__).parent / "fixtures" / "retrieval_benchmark_v2.json",
    )
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--check-regression", action="store_true")
    args = parser.parse_args()
    if args.iterations < 1:
        parser.error("--iterations must be at least 1")
    fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
    baseline = json.loads(args.baseline.read_text(encoding="utf-8")) if args.baseline else None
    result = {
        "fixture": str(args.fixture),
        **evaluate_fixture_report(fixture, iterations=args.iterations),
    }
    result["abstention"] = evaluate_abstention_report(fixture, iterations=args.iterations)
    print(json.dumps(result, indent=2, sort_keys=True))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    if args.check_regression:
        failures = check_regression(result, baseline)
        if failures:
            raise SystemExit("Evaluation regression failed:\n" + "\n".join(failures))
        print("evaluation regression: PASS")


if __name__ == "__main__":
    main()
