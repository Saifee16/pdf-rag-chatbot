from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from app.services.hybrid_retrieval import reciprocal_rank_fusion
from app.services.lexical_retrieval import tokenize
from app.services.reranking_service import DeterministicReranker
from app.services.vector_store import VectorHit
from evaluation.evaluate_retrieval import ndcg_at_k, recall_at_k, reciprocal_rank


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
            id=chunk_id, score=1.0 - (rank * 0.01), payload={"text": chunks_by_id[chunk_id]["text"]}
        )
        for rank, chunk_id in enumerate(order)
    ]


def evaluate_fixture(
    fixture: dict[str, object], *, iterations: int = 20
) -> dict[str, dict[str, float]]:
    top_k = int(fixture["top_k"])
    chunks = list(fixture["chunks"])
    chunks_by_id = {chunk["id"]: chunk for chunk in chunks}
    cases = list(fixture["cases"])
    reranker = DeterministicReranker()
    totals = {
        mode: {"recall_at_k": 0.0, "mrr": 0.0, "ndcg_at_k": 0.0, "latency_ms": 0.0}
        for mode in ("dense", "hybrid", "hybrid_rerank")
    }
    for case in cases:
        question = str(case["question"])
        expected = set(case["relevant_ids"])
        dense = _dense_hits(list(case["dense_order"]), chunks_by_id)
        lexical = _lexical_hits(question, chunks)
        outputs = {
            "dense": dense[:top_k],
            "hybrid": reciprocal_rank_fusion(dense, lexical, limit=top_k),
        }
        fused = reciprocal_rank_fusion(dense, lexical, limit=min(len(dense), 20))
        outputs["hybrid_rerank"] = reranker.rerank(question, fused, top_k)
        for mode, output in outputs.items():
            returned = [hit.id for hit in output]
            totals[mode]["recall_at_k"] += recall_at_k(returned, expected, top_k)
            totals[mode]["mrr"] += reciprocal_rank(returned, expected)
            totals[mode]["ndcg_at_k"] += ndcg_at_k(returned, expected, top_k)
            started = time.perf_counter()
            for _ in range(iterations):
                if mode == "dense":
                    _dense_hits(list(case["dense_order"]), chunks_by_id)[:top_k]
                elif mode == "hybrid":
                    reciprocal_rank_fusion(dense, lexical, limit=top_k)
                else:
                    reranker.rerank(question, fused, top_k)
            totals[mode]["latency_ms"] += ((time.perf_counter() - started) * 1000) / iterations
    count = len(cases)
    if count == 0:
        raise ValueError("Benchmark fixture must contain at least one case")
    return {
        mode: {metric: round(value / count, 6) for metric, value in scores.items()}
        for mode, scores in totals.items()
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the deterministic retrieval quality benchmark."
    )
    parser.add_argument(
        "--fixture",
        type=Path,
        default=Path(__file__).parent / "fixtures" / "retrieval_benchmark.json",
    )
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.iterations < 1:
        parser.error("--iterations must be at least 1")
    fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
    result = {
        "fixture": str(args.fixture),
        "top_k": fixture["top_k"],
        "modes": evaluate_fixture(fixture, iterations=args.iterations),
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    if args.output:
        args.output.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
