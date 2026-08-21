from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Document
from app.repositories.document_repository import DocumentRepository
from app.services.index_config import index_fingerprint
from app.services.ingestion_service import IngestionService
from tests.fakes import FakeEmbeddingProvider, FakeVectorStore


def test_ingestion_extracts_chunks_embeds_and_marks_ready(
    tmp_path: Path,
    pdf_bytes: bytes,
    db_session: Session,
) -> None:
    pdf_path = tmp_path / "document.pdf"
    pdf_path.write_bytes(pdf_bytes)
    document = DocumentRepository(db_session).add(
        Document(
            original_filename="document.pdf",
            stored_path=str(pdf_path),
            sha256="a" * 64,
            size_bytes=len(pdf_bytes),
            status="pending",
        )
    )
    settings = get_settings().model_copy(update={"chunk_size": 300, "chunk_overlap": 50})
    vector_store = FakeVectorStore()
    service = IngestionService(
        db=db_session,
        settings=settings,
        embedding_provider=FakeEmbeddingProvider(),
        vector_store=vector_store,
    )

    service.ingest(document.id)

    refreshed = DocumentRepository(db_session).get(document.id)
    assert refreshed is not None
    assert refreshed.status == "ready"
    assert refreshed.page_count == 1
    assert refreshed.chunk_count >= 1
    assert refreshed.index_fingerprint == index_fingerprint(settings)
    assert len(vector_store.points) == refreshed.chunk_count


def test_ingestion_is_idempotent_for_vector_points(
    tmp_path: Path,
    pdf_bytes: bytes,
    db_session: Session,
) -> None:
    pdf_path = tmp_path / "document.pdf"
    pdf_path.write_bytes(pdf_bytes)
    document = DocumentRepository(db_session).add(
        Document(
            original_filename="document.pdf",
            stored_path=str(pdf_path),
            sha256="b" * 64,
            size_bytes=len(pdf_bytes),
            status="pending",
        )
    )
    settings = get_settings().model_copy(update={"chunk_size": 300, "chunk_overlap": 50})
    vector_store = FakeVectorStore()
    service = IngestionService(
        db=db_session,
        settings=settings,
        embedding_provider=FakeEmbeddingProvider(),
        vector_store=vector_store,
    )

    service.ingest(document.id)
    first_ids = set(vector_store.points)
    service.ingest(document.id)

    assert set(vector_store.points) == first_ids
