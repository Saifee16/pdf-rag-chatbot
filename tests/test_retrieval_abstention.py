from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.services.rag_service import INSUFFICIENT_EVIDENCE_ANSWER, RAGService
from app.services.retrieval_confidence import RetrievalConfidenceService
from app.services.retrieval_service import RetrievalResult
from app.services.vector_store import VectorHit
from tests.fakes import FakeChatProvider


def hit(identifier: str, score: float, **payload: object) -> VectorHit:
    return VectorHit(id=identifier, score=score, payload={"text": "synthetic", **payload})


def test_confidence_accepts_strong_dense_evidence() -> None:
    service = RetrievalConfidenceService(enabled=True, threshold=0.5)
    decision = service.decide([hit("strong", 0.8), hit("next", 0.4)], mode="dense")
    assert decision.accepted is True
    assert decision.confidence == 0.8
    assert decision.reason is None


def test_confidence_abstains_at_boundary_below_threshold() -> None:
    service = RetrievalConfidenceService(enabled=True, threshold=0.5)
    decision = service.decide([hit("weak", 0.49)], mode="dense")
    assert decision.accepted is False
    assert decision.reason == "retrieval_confidence_below_threshold"


def test_hybrid_confidence_uses_channel_agreement() -> None:
    service = RetrievalConfidenceService(enabled=True, threshold=0.5)
    agreed = service.decide(
        [hit("agreed", 0.8, dense_score=0.8, lexical_score=0.8), hit("next", 0.1)],
        mode="hybrid",
    )
    distractor = service.decide(
        [hit("distractor", 0.9, dense_score=0.2, lexical_score=0.9), hit("next", 0.1)],
        mode="hybrid",
    )
    assert agreed.accepted is True
    assert agreed.features["channel_agreement"] == 1.0
    assert distractor.accepted is False


def test_confidence_disabled_preserves_candidates() -> None:
    decision = RetrievalConfidenceService(enabled=False, threshold=1.0).decide(
        [hit("candidate", 0.1)], mode="dense"
    )
    assert decision.accepted is True


def test_configuration_validates_confidence_threshold() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, RETRIEVAL_CONFIDENCE_THRESHOLD=1.1)


def test_rag_service_skips_provider_and_citations_on_abstention(db_session) -> None:
    settings = Settings(_env_file=None, RAG_SYSTEM_PROMPT_PATH="prompts/rag_system.txt")
    provider = FakeChatProvider()
    retrieval = SimpleNamespace(
        retrieve=lambda **_: RetrievalResult(
            trace_id="trace-abstained",
            hits=[],
            mode="hybrid",
            confidence=0.2,
            abstained=True,
            abstention_reason="retrieval_confidence_below_threshold",
        )
    )
    service = RAGService(
        db=db_session,
        settings=settings,
        chat_provider=provider,
        retrieval_service=retrieval,
    )
    result = service.ask(
        question="Unsupported synthetic question",
        conversation_id=None,
        document_ids=None,
        top_k=3,
        score_threshold=None,
    )
    assert provider.calls == 0
    assert result.answer == INSUFFICIENT_EVIDENCE_ANSWER
    assert result.citations == []
    assert result.abstained is True
    assert result.abstention_reason == "retrieval_confidence_below_threshold"
    assert result.provider == "abstention"
