from __future__ import annotations

from dataclasses import dataclass

from app.services.vector_store import VectorHit


@dataclass(frozen=True, slots=True)
class ConfidenceDecision:
    confidence: float
    accepted: bool
    reason: str | None
    features: dict[str, float]


class RetrievalConfidenceService:
    """Deterministic, evidence-based retrieval acceptance heuristic.

    Dense scores are cosine-like in [0, 1]. Hybrid scores retain the original
    dense and lexical evidence in their payload, so the heuristic never treats
    an RRF score as a probability. Agreement is a small, explicit bonus.
    """

    def __init__(self, *, enabled: bool, threshold: float) -> None:
        self.enabled = enabled
        self.threshold = threshold

    def decide(
        self,
        hits: list[VectorHit],
        *,
        mode: str,
    ) -> ConfidenceDecision:
        if not hits:
            return ConfidenceDecision(0.0, False, "no_retrieval_candidates", {})
        top = hits[0]
        payload = top.payload
        dense_raw = payload.get("dense_score")
        lexical_raw = payload.get("lexical_score")
        dense_score = self._bounded(dense_raw if dense_raw is not None else top.score)
        lexical_score = self._bounded(lexical_raw)
        agreement = float(dense_raw is not None and lexical_raw is not None)
        margin = 0.0
        if len(hits) > 1:
            margin = self._bounded(top.score - hits[1].score)
        if mode == "dense":
            confidence = dense_score
        elif dense_raw is None or lexical_raw is None:
            # A missing channel is common for a legitimate lexical-only or
            # dense-only candidate; preserve the evidence that is available.
            confidence = max(dense_score, lexical_score)
        else:
            agreement_strength = min(dense_score, lexical_score)
            confidence = (0.55 * dense_score) + (0.30 * lexical_score)
            confidence += 0.10 * agreement_strength
            confidence += 0.05 * margin
        confidence = round(self._bounded(confidence), 6)
        accepted = not self.enabled or confidence >= self.threshold
        reason = None if accepted else "retrieval_confidence_below_threshold"
        return ConfidenceDecision(
            confidence=confidence,
            accepted=accepted,
            reason=reason,
            features={
                "top_dense_score": round(dense_score, 6),
                "top_lexical_score": round(lexical_score, 6),
                "channel_agreement": agreement,
                "top_score_margin": round(margin, 6),
            },
        )

    @staticmethod
    def _bounded(value: object) -> float:
        if value is None:
            return 0.0
        try:
            number = float(value)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, number))
