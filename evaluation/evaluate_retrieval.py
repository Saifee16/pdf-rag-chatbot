import argparse
import json
from pathlib import Path

import httpx


def reciprocal_rank(returned_ids: list[str], expected_ids: set[str]) -> float:
    for rank, document_id in enumerate(returned_ids, start=1):
        if document_id in expected_ids:
            return 1.0 / rank
    return 0.0


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate retrieval hit rate and MRR.")
    parser.add_argument("--golden", type=Path, required=True)
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
