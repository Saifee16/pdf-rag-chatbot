from __future__ import annotations

from app.services.vector_store import VectorHit


def reciprocal_rank_fusion(
    dense_hits: list[VectorHit],
    lexical_hits: list[VectorHit],
    *,
    limit: int,
    rrf_k: int = 60,
) -> list[VectorHit]:
    """Fuse independently ranked candidates without comparing score scales."""
    candidates: dict[str, dict[str, object]] = {}
    for source, hits in (("dense", dense_hits), ("lexical", lexical_hits)):
        for rank, hit in enumerate(hits, start=1):
            entry = candidates.setdefault(
                hit.id,
                {
                    "hit": hit,
                    "fused": 0.0,
                    "dense_score": None,
                    "lexical_score": None,
                },
            )
            entry["fused"] = float(entry["fused"]) + 1.0 / (rrf_k + rank)
            entry[f"{source}_score"] = hit.score
            if source == "dense":
                entry["hit"] = hit
            elif entry["dense_score"] is None:
                entry["hit"] = hit

    ranked = sorted(
        candidates.values(),
        key=lambda item: (-float(item["fused"]), str(item["hit"].id)),
    )
    results: list[VectorHit] = []
    for entry in ranked[:limit]:
        hit = entry["hit"]
        payload = dict(hit.payload)
        payload["dense_score"] = entry["dense_score"]
        payload["lexical_score"] = entry["lexical_score"]
        payload["hybrid_score"] = float(entry["fused"])
        results.append(VectorHit(id=hit.id, score=float(entry["fused"]), payload=payload))
    return results
