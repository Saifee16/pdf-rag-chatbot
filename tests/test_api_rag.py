import pytest
from httpx import AsyncClient
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Document
from app.repositories.document_repository import DocumentRepository
from app.services.index_config import index_fingerprint
from app.services.vector_store import VectorPoint
from tests.fakes import FakeVectorStore, text_vector


def seed_ready_document(db_session: Session, store: FakeVectorStore) -> Document:
    settings = get_settings()
    document = DocumentRepository(db_session).add(
        Document(
            original_filename="handbook.pdf",
            stored_path="/handbook.pdf",
            sha256="e" * 64,
            size_bytes=100,
            status="ready",
            page_count=1,
            chunk_count=1,
            embedding_provider="gemini",
            embedding_model="fake-embedding-v1",
            index_fingerprint=index_fingerprint(settings),
        )
    )
    store.ensure_collection(12)
    store.upsert(
        [
            VectorPoint(
                id="chunk-handbook",
                vector=text_vector("refund policy thirty days"),
                payload={
                    "document_id": document.id,
                    "filename": document.original_filename,
                    "page_number": 4,
                    "chunk_index": 0,
                    "text": "The refund policy allows requests within thirty days.",
                },
            )
        ]
    )
    return document


@pytest.mark.anyio
async def test_retrieval_and_chat_routes(
    client: AsyncClient,
    db_session: Session,
    fake_vector_store: FakeVectorStore,
) -> None:
    document = seed_ready_document(db_session, fake_vector_store)

    retrieval = await client.post(
        "/api/v1/retrieval/search",
        json={
            "query": "refund policy",
            "document_ids": [document.id],
            "score_threshold": 0.0,
        },
    )
    assert retrieval.status_code == 200
    assert retrieval.json()["data"]["hits"][0]["page_number"] == 4

    chat = await client.post(
        "/api/v1/chat",
        json={
            "question": "What is the refund policy?",
            "document_ids": [document.id],
            "score_threshold": 0.0,
        },
    )
    assert chat.status_code == 200
    body = chat.json()["data"]
    assert body["citations"][0]["filename"] == "handbook.pdf"
    assert body["provider"] == "fake-chat"

    conversation = await client.get(f"/api/v1/conversations/{body['conversation_id']}")
    assert conversation.status_code == 200
    assert len(conversation.json()["data"]["messages"]) == 2


@pytest.mark.anyio
async def test_conversation_list_and_delete(
    client: AsyncClient,
    db_session: Session,
    fake_vector_store: FakeVectorStore,
) -> None:
    document = seed_ready_document(db_session, fake_vector_store)
    chat = await client.post(
        "/api/v1/chat",
        json={
            "question": "What is the refund policy?",
            "document_ids": [document.id],
            "score_threshold": 0.0,
        },
    )
    conversation_id = chat.json()["data"]["conversation_id"]

    listing = await client.get("/api/v1/conversations")
    assert listing.status_code == 200
    assert listing.json()["data"]["count"] == 1

    deleted = await client.delete(f"/api/v1/conversations/{conversation_id}")
    assert deleted.status_code == 200

    missing = await client.get(f"/api/v1/conversations/{conversation_id}")
    assert missing.status_code == 404
