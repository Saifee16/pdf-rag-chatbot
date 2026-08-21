import argparse
import json
import math
from pathlib import Path

import httpx


def reciprocal_rank(returned_ids: list[str], expected_ids: set[str]) -> float:
    for rank, document_id in enumerate(returned_ids, start=1):
        if document_id in expected_ids:
            return 1.0 / rank
    return 0.0


def recall_at_k(returned_ids: list[str], expected_ids: set[str], k: int) -> float:
    """Binary relevance recall, bounded to the first *k* results."""
    if not expected_ids or k <= 0:
        return 0.0
    return len(set(returned_ids[:k]) & expected_ids) / len(expected_ids)


def ndcg_at_k(returned_ids: list[str], expected_ids: set[str], k: int) -> float:
    """nDCG for binary relevance with deterministic ideal ranking."""
    if not expected_ids or k <= 0:
        return 0.0
    dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank, item in enumerate(returned_ids[:k], start=1)
        if item in expected_ids
    )
    ideal_hits = min(k, len(expected_ids))
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return dcg / idcg if idcg else 0.0


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate retrieval hit rate and MRR.")
    parser.add_argument("--golden", "--dataset", dest="golden", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()

    cases = json.loads(args.golden.read_text(encoding="utf-8"))
    headers = {"X-API-Key": args.api_key} if args.api_key else {}
    hit_count = 0
    rr_total = 0.0

    with httpx.Client(base_url=args.base_url, headers=headers, timeout=60) as client:
        for case in cases:
            response = client.post(
                "/api/v1/retrieval/search",
                json={"query": case["question"], "top_k": args.top_k},
            )
            response.raise_for_status()
            hits = response.json()["data"]["hits"]
            returned = [hit["document_id"] for hit in hits]
            expected = set(case["expected_document_ids"])
            matched = bool(expected.intersection(returned))
            hit_count += int(matched)
            rr_total += reciprocal_rank(returned, expected)
            print(f"{'HIT' if matched else 'MISS'} | {case['question']}")

    total = len(cases)
    if total == 0:
        raise SystemExit("Golden set is empty.")
    print(f"hit_rate@{args.top_k}: {hit_count / total:.4f}")
    print(f"mrr@{args.top_k}: {rr_total / total:.4f}")


if __name__ == "__main__":
    main()
