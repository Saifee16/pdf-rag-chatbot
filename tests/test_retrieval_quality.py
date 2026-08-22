from app.core.config import get_settings
from app.db.models import Chunk
from app.services.hybrid_retrieval import reciprocal_rank_fusion
from app.services.index_config import index_fingerprint
from app.services.reranking_service import DeterministicReranker
from app.services.retrieval_service import RetrievalService
from app.services.vector_store import VectorHit, VectorPoint
from evaluation.evaluate_retrieval import ndcg_at_k, recall_at_k
from evaluation.run_retrieval_benchmark import evaluate_fixture
from tests.fakes import FakeEmbeddingProvider, FakeVectorStore, text_vector
from tests.test_retrieval import add_ready_document


def hit(identifier: str, text: str, score: float) -> VectorHit:
    return VectorHit(id=identifier, score=score, payload={"text": text})


def test_rrf_deduplicates_candidates_and_is_deterministic() -> None:
    dense = [hit("dense-first", "semantic", 0.9), hit("shared", "target", 0.8)]
    lexical = [hit("shared", "target", 1.0), hit("lexical-only", "keyword", 0.8)]
    fused = reciprocal_rank_fusion(dense, lexical, limit=3)
    assert [item.id for item in fused] == ["shared", "dense-first", "lexical-only"]
    assert fused[0].payload["dense_score"] == 0.8
    assert fused[0].payload["lexical_score"] == 1.0


def test_deterministic_reranker_prefers_query_phrase() -> None:
    reranker = DeterministicReranker()
    results = reranker.rerank(
        "retention policy",
        [
            hit("partial", "retention only", 0.9),
            hit("exact", "retention policy details", 0.4),
        ],
        2,
    )
    assert [item.id for item in results] == ["exact", "partial"]
    assert results[0].payload["hybrid_score"] == 0.4


def test_hybrid_service_uses_authorized_lexical_chunks(db_session) -> None:
    settings = get_settings().model_copy(
        update={"hybrid_dense_candidates": 5, "hybrid_lexical_candidates": 5}
    )
    document = add_ready_document(db_session, sha="q", fingerprint=index_fingerprint(settings))
    db_session.add(
        Chunk(
            id="lexical-chunk",
            document_id=document.id,
            page_number=2,
            chunk_index=0,
            text="retention policy keeps records ninety days",
            text_sha256="a" * 64,
        )
    )
    db_session.commit()
    store = FakeVectorStore()
    store.ensure_collection(12)
    store.upsert(
        [
            VectorPoint(
                id="dense-chunk",
                vector=text_vector("unrelated gardening guide"),
                payload={
                    "document_id": document.id,
                    "filename": document.original_filename,
                    "page_number": 1,
                    "chunk_index": 0,
                    "text": "unrelated gardening guide",
                },
            )
        ]
    )
    service = RetrievalService(
        db=db_session,
        settings=settings,
        embedding_provider=FakeEmbeddingProvider(),
        vector_store=store,
    )
    result = service.retrieve(
        query="retention policy",
        document_ids=[document.id],
        top_k=1,
        score_threshold=0.99,
        mode="hybrid",
    )
    assert result.mode == "hybrid"
    assert result.hits[0].id == "lexical-chunk"


def test_benchmark_reports_all_modes_and_quality_metrics() -> None:
    import json
    from pathlib import Path

    fixture = json.loads(
        (
                Path(__file__).parents[1] / "evaluation" / "fixtures" / "retrieval_benchmark_v2.json"
        ).read_text(encoding="utf-8")
    )
    result = evaluate_fixture(fixture, iterations=2)
    assert set(result) == {"dense", "hybrid", "hybrid_rerank"}
    assert result["hybrid"]["mrr"] > result["dense"]["mrr"]
    assert result["hybrid"]["ndcg_at_k"] > result["dense"]["ndcg_at_k"]
    assert recall_at_k(["a", "b"], {"b"}, 2) == 1.0
    assert ndcg_at_k(["b", "a"], {"b"}, 2) == 1.0
