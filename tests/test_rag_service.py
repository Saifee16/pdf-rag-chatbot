from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Document
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.document_repository import DocumentRepository
from app.services.index_config import index_fingerprint
from app.services.rag_service import RAGService
from app.services.retrieval_service import RetrievalService
from app.services.vector_store import VectorPoint
from tests.fakes import FakeChatProvider, FakeEmbeddingProvider, FakeVectorStore, text_vector


def build_service(db_session: Session) -> tuple[RAGService, Document]:
    settings = get_settings()
    document = DocumentRepository(db_session).add(
        Document(
            original_filename="policy.pdf",
            stored_path="/policy.pdf",
            sha256="d" * 64,
            size_bytes=100,
            status="ready",
            page_count=1,
            chunk_count=1,
            embedding_provider="gemini",
            embedding_model="fake-embedding-v1",
            index_fingerprint=index_fingerprint(settings),
        )
    )
    store = FakeVectorStore()
    store.ensure_collection(12)
    store.upsert(
        [
            VectorPoint(
                id="chunk-policy",
                vector=text_vector("revenue policy response within two business days"),
                payload={
                    "document_id": document.id,
                    "filename": "policy.pdf",
                    "page_number": 1,
                    "chunk_index": 0,
                    "text": "Revenue policy requires response within two business days.",
                },
            )
        ]
    )
    retrieval = RetrievalService(
        db=db_session,
        settings=settings,
        embedding_provider=FakeEmbeddingProvider(),
        vector_store=store,
    )
    return (
        RAGService(
            db=db_session,
            settings=settings,
            chat_provider=FakeChatProvider(),
            retrieval_service=retrieval,
        ),
        document,
    )


def test_rag_service_returns_citations_and_persists_conversation(db_session: Session) -> None:
    service, document = build_service(db_session)

    result = service.ask(
        question="What is the revenue policy response time?",
        conversation_id=None,
        document_ids=[document.id],
        top_k=5,
        score_threshold=0.0,
    )

    assert result.citations[0].page_number == 1
    assert result.citations[0].filename == "policy.pdf"
    conversation = ConversationRepository(db_session).get(
        result.conversation_id, with_messages=True
    )
    assert conversation is not None
    assert len(conversation.messages) == 2


def test_rag_service_reuses_existing_conversation(db_session: Session) -> None:
    service, document = build_service(db_session)
    first = service.ask(
        question="What is the policy?",
        conversation_id=None,
        document_ids=[document.id],
        top_k=5,
        score_threshold=0.0,
    )
    second = service.ask(
        question="Repeat that briefly.",
        conversation_id=first.conversation_id,
        document_ids=[document.id],
        top_k=5,
        score_threshold=0.0,
    )
    assert second.conversation_id == first.conversation_id


def test_rag_service_drops_invalid_citation_numbers(db_session: Session) -> None:
    service, _ = build_service(db_session)
    citations = service._extract_citations("Answer [99] [1] [1].", [])
    assert citations == []
