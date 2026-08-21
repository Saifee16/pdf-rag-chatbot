from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Chunk, Document


class DocumentRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def add(self, document: Document) -> Document:
        self.db.add(document)
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self.db.refresh(document)
        return document

    def get(self, document_id: str) -> Document | None:
        return self.db.get(Document, document_id)

    def get_by_sha256(self, sha256: str) -> Document | None:
        return self.db.scalar(select(Document).where(Document.sha256 == sha256))

    def list(self) -> list[Document]:
        return list(self.db.scalars(select(Document).order_by(Document.created_at.desc())))

    def ready_for_fingerprint(self, fingerprint: str) -> list[Document]:
        statement = select(Document).where(
            Document.status == "ready", Document.index_fingerprint == fingerprint
        )
        return list(self.db.scalars(statement))

    def selected_ready(self, document_ids: list[str]) -> list[Document]:
        if not document_ids:
            return []
        statement = select(Document).where(
            Document.id.in_(document_ids), Document.status == "ready"
        )
        return list(self.db.scalars(statement))

    def replace_chunks(self, document_id: str, chunks: list[Chunk]) -> None:
        self.db.query(Chunk).filter(Chunk.document_id == document_id).delete(
            synchronize_session=False
        )
        self.db.add_all(chunks)
        self.db.commit()

    def mark_processing(self, document: Document) -> None:
        document.status = "processing"
        document.error_message = None
        self.db.commit()

    def mark_ready(
        self,
        document: Document,
        *,
        page_count: int,
        chunk_count: int,
        embedding_provider: str,
        embedding_model: str,
        index_fingerprint: str,
    ) -> None:
        document.status = "ready"
        document.page_count = page_count
        document.chunk_count = chunk_count
        document.embedding_provider = embedding_provider
        document.embedding_model = embedding_model
        document.index_fingerprint = index_fingerprint
        document.error_message = None
        self.db.commit()
        self.db.refresh(document)

    def mark_pending(self, document: Document) -> None:
        document.status = "pending"
        document.error_message = None
        self.db.commit()
        self.db.refresh(document)

    def mark_failed(self, document: Document, message: str) -> None:
        document.status = "failed"
        document.error_message = message[:4000]
        self.db.commit()

    def delete(self, document: Document) -> None:
        self.db.delete(document)
        self.db.commit()
