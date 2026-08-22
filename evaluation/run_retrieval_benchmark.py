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


def _dense_hits(order: list[str], chunks_by_id: dict[str, dict[str, str]]) -> list[VectorHit]:
    return [
        VectorHit(
            id=chunk_id,
            score=1.0 - (rank * 0.01),
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
    if len(seen_categories) < 12:
        raise ValueError("Benchmark fixture must cover at least 12 categories")


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
        question = str(case["question"])
        expected = set(case["relevant_ids"])
        expected_no_answer = bool(case.get("expected_no_answer", False))
        dense = _dense_hits(list(case["dense_order"]), chunks_by_id)
        lexical = _lexical_hits(question, chunks)
        fused = reciprocal_rank_fusion(dense, lexical, limit=min(len(dense), 20))
        outputs = {
            "dense": dense[:top_k],
            "hybrid": reciprocal_rank_fusion(dense, lexical, limit=top_k),
            "hybrid_rerank": reranker.rerank(question, fused, top_k),
        }
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
                    _dense_hits(list(case["dense_order"]), chunks_by_id)[:top_k]
                elif mode == "hybrid":
                    reciprocal_rank_fusion(dense, lexical, limit=top_k)
                else:
                    reranker.rerank(question, fused, top_k)
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


def evaluate_fixture(
    fixture: dict[str, object], *, iterations: int = 20
) -> dict[str, dict[str, float]]:
    """Cycle 1-compatible summary retained for callers that only need mode metrics."""
    return evaluate_fixture_report(fixture, iterations=iterations)["modes"]


def check_regression(report: dict[str, Any], baseline: dict[str, Any] | None = None) -> list[str]:
    """Return quality regressions; latency is reported but deliberately not gated."""
    minimums = {
        "dense": {
            "recall_at_k": 0.75,
            "precision_at_k": 0.20,
            "hit_rate_at_k": 0.75,
            "mrr": 0.40,
            "ndcg_at_k": 0.50,
        },
        "hybrid": {
            "recall_at_k": 0.75,
            "precision_at_k": 0.20,
            "hit_rate_at_k": 0.75,
            "mrr": 0.60,
            "ndcg_at_k": 0.70,
        },
        "hybrid_rerank": {
            "recall_at_k": 0.60,
            "precision_at_k": 0.20,
            "hit_rate_at_k": 0.65,
            "mrr": 0.55,
            "ndcg_at_k": 0.60,
        },
    }
    errors: list[str] = []
    for mode, metrics in report["modes"].items():
        for metric, minimum in minimums[mode].items():
            if metrics[metric] < minimum:
                errors.append(f"{mode}.{metric}={metrics[metric]:.4f} < {minimum:.4f}")
    hybrid = report["modes"]["hybrid"]
    dense = report["modes"]["dense"]
    if hybrid["mrr"] <= dense["mrr"] or hybrid["ndcg_at_k"] <= dense["ndcg_at_k"]:
        errors.append("hybrid must materially improve MRR and nDCG over dense")
    if hybrid["no_answer_fp"] > 0.25 or report["modes"]["hybrid_rerank"]["no_answer_fp"] > 0.25:
        errors.append("no-answer false-positive rate exceeds 0.25")
    if baseline:
        for mode in MODES:
            for metric in ("recall_at_k", "precision_at_k", "hit_rate_at_k", "mrr", "ndcg_at_k"):
                old = float(baseline["modes"][mode][metric])
                new = float(report["modes"][mode][metric])
                if new + 0.05 < old:
                    errors.append(
                        f"{mode}.{metric} regressed by more than 0.05 ({old:.4f} -> {new:.4f})"
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
