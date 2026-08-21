from __future__ import annotations

from dataclasses import replace
from typing import Protocol

from app.services.lexical_retrieval import tokenize
from app.services.vector_store import VectorHit


class Reranker(Protocol):
    def rerank(self, query: str, hits: list[VectorHit], limit: int) -> list[VectorHit]: ...


class DeterministicReranker:
    """Offline reranker with stable token coverage and phrase matching.

    The provider boundary makes this replaceable with a hosted cross-encoder
    later without changing the retrieval service or API contract.
    """

    def rerank(self, query: str, hits: list[VectorHit], limit: int) -> list[VectorHit]:
        query_tokens = tokenize(query)
        query_set = set(query_tokens)
        if not query_set:
            return hits[:limit]
        ranked: list[tuple[float, str, VectorHit]] = []
        phrase = " ".join(query_tokens)
        for hit in hits:
            text_tokens = tokenize(str(hit.payload.get("text", "")))
            text_set = set(text_tokens)
            coverage = len(query_set & text_set) / len(query_set)
            phrase_bonus = 1.0 if phrase and phrase in " ".join(text_tokens) else 0.0
            # Keep a small fused-score contribution for stable semantic ties.
            score = (0.75 * coverage) + (0.2 * phrase_bonus) + (0.05 * hit.score)
            payload = dict(hit.payload)
            payload["hybrid_score"] = hit.score
            ranked.append((score, hit.id, replace(hit, score=score, payload=payload)))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        return [hit for _, _, hit in ranked[:limit]]


def build_reranker(provider: str) -> Reranker | None:
    if provider == "deterministic":
        return DeterministicReranker()
    return None
