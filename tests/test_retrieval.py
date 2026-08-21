from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Document
from app.repositories.document_repository import DocumentRepository
from app.services.index_config import index_fingerprint
from app.services.retrieval_service import RetrievalService
from app.services.vector_store import VectorPoint
from tests.fakes import FakeEmbeddingProvider, FakeVectorStore, text_vector


def add_ready_document(db: Session, *, sha: str, fingerprint: str) -> Document:
    return DocumentRepository(db).add(
        Document(
            original_filename=f"{sha}.pdf",
            stored_path=f"/{sha}.pdf",
            sha256=sha * 64,
            size_bytes=100,
            status="ready",
            page_count=1,
            chunk_count=1,
            embedding_provider="gemini",
            embedding_model="fake-embedding-v1",
            index_fingerprint=fingerprint,
        )
    )


def test_retrieval_filters_documents_and_persists_trace(db_session: Session) -> None:
    settings = get_settings()
    fingerprint = index_fingerprint(settings)
    first = add_ready_document(db_session, sha="a", fingerprint=fingerprint)
    second = add_ready_document(db_session, sha="b", fingerprint=fingerprint)
    store = FakeVectorStore()
    store.ensure_collection(12)
    store.upsert(
        [
            VectorPoint(
                id="chunk-a",
                vector=text_vector("revenue policy two days"),
                payload={
                    "document_id": first.id,
                    "filename": first.original_filename,
                    "page_number": 1,
                    "chunk_index": 0,
                    "text": "revenue policy two days",
                },
            ),
            VectorPoint(
                id="chunk-b",
                vector=text_vector("unrelated gardening guide"),
                payload={
                    "document_id": second.id,
                    "filename": second.original_filename,
                    "page_number": 1,
                    "chunk_index": 0,
                    "text": "unrelated gardening guide",
                },
            ),
        ]
    )
    service = RetrievalService(
        db=db_session,
        settings=settings,
        embedding_provider=FakeEmbeddingProvider(),
        vector_store=store,
    )

    result = service.retrieve(
        query="revenue policy",
        document_ids=[first.id],
        top_k=3,
        score_threshold=0.0,
    )

    assert len(result.hits) == 1
    assert result.hits[0].payload["document_id"] == first.id
    assert result.trace_id


def test_retrieval_rejects_stale_index_configuration(db_session: Session) -> None:
    settings = get_settings()
    document = add_ready_document(db_session, sha="c", fingerprint="stale")
    service = RetrievalService(
        db=db_session,
        settings=settings,
        embedding_provider=FakeEmbeddingProvider(),
        vector_store=FakeVectorStore(),
    )

    try:
        service.retrieve(
            query="question",
            document_ids=[document.id],
            top_k=5,
            score_threshold=0.0,
        )
    except Exception as exc:
        assert getattr(exc, "code", None) == "INDEX_CONFIGURATION_MISMATCH"
    else:
        raise AssertionError("Expected stale index rejection")


def test_retrieval_without_ready_documents_returns_empty_trace(db_session: Session) -> None:
    service = RetrievalService(
        db=db_session,
        settings=get_settings(),
        embedding_provider=FakeEmbeddingProvider(),
        vector_store=FakeVectorStore(),
    )
    result = service.retrieve(query="anything", document_ids=None, top_k=None, score_threshold=None)
    assert result.hits == []
    assert result.trace_id
