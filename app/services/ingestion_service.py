import hashlib
from uuid import UUID, uuid5

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError
from app.core.logging import get_logger
from app.db.models import Chunk
from app.providers.base import EmbeddingProvider
from app.repositories.document_repository import DocumentRepository
from app.services.chunking_service import ChunkDraft, TextChunker
from app.services.index_config import index_fingerprint
from app.services.pdf_service import PDFTextExtractor
from app.services.vector_store import QdrantVectorStore, VectorPoint

logger = get_logger(__name__)


class PermanentIngestionError(Exception):
    pass


class IngestionService:
    def __init__(
        self,
        *,
        db: Session,
        settings: Settings,
        embedding_provider: EmbeddingProvider,
        vector_store: QdrantVectorStore,
    ) -> None:
        self.db = db
        self.settings = settings
        self.embedding_provider = embedding_provider
        self.vector_store = vector_store
        self.documents = DocumentRepository(db)
        self.extractor = PDFTextExtractor(max_pages=settings.max_pdf_pages)
        self.chunker = TextChunker(
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
        )

    def ingest(self, document_id: str) -> None:
        document = self.documents.get(document_id)
        if document is None:
            raise PermanentIngestionError(f"Document {document_id} does not exist.")

        self.documents.mark_processing(document)
        try:
            pages = self.extractor.extract(document.stored_path)
        except AppError as exc:
            raise PermanentIngestionError(exc.message) from exc
        drafts = self.chunker.split(pages)
        if not drafts:
            raise PermanentIngestionError(
                "The PDF contains no extractable text. Scanned-image PDFs require an OCR extension."
            )

        vectors: list[list[float]] = []
        for start in range(0, len(drafts), self.settings.embedding_batch_size):
            batch = drafts[start : start + self.settings.embedding_batch_size]
            vectors.extend(self.embedding_provider.embed_documents([item.text for item in batch]))

        if len(vectors) != len(drafts):
            raise RuntimeError("Embedding provider returned an unexpected number of vectors.")
        if not vectors or not vectors[0]:
            raise RuntimeError("Embedding provider returned an empty vector.")

        dimensions = len(vectors[0])
        if any(len(vector) != dimensions for vector in vectors):
            raise RuntimeError("Embedding dimensions are inconsistent within the same batch.")

        chunks = [self._build_chunk(document.id, draft) for draft in drafts]
        points = [
            VectorPoint(
                id=chunk.id,
                vector=vector,
                payload={
                    "chunk_id": chunk.id,
                    "document_id": document.id,
                    "filename": document.original_filename,
                    "page_number": chunk.page_number,
                    "chunk_index": chunk.chunk_index,
                    "text": chunk.text,
                    "index_fingerprint": index_fingerprint(self.settings),
                },
            )
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        vectors_written = False
        try:
            self.vector_store.ensure_collection(dimensions)
            self.vector_store.delete_document(document.id)
            self.vector_store.upsert(points)
            vectors_written = True
            self.documents.replace_chunks(document.id, chunks)
            self.documents.mark_ready(
                document,
                page_count=len(pages),
                chunk_count=len(chunks),
                embedding_provider=self.settings.embedding_provider,
                embedding_model=self.settings.embedding_model,
                index_fingerprint=index_fingerprint(self.settings),
            )
        except Exception:
            if vectors_written:
                try:
                    self.vector_store.delete_document(document.id)
                except Exception:
                    logger.exception(
                        "Failed to remove partial vector state document=%s", document.id
                    )
            raise
        logger.info(
            "Indexed document=%s pages=%s chunks=%s dimensions=%s",
            document.id,
            len(pages),
            len(chunks),
            dimensions,
        )

    @staticmethod
    def _build_chunk(document_id: str, draft: ChunkDraft) -> Chunk:
        text_sha = hashlib.sha256(draft.text.encode("utf-8")).hexdigest()
        chunk_id = str(
            uuid5(
                UUID(document_id),
                f"{draft.page_number}:{draft.chunk_index}:{text_sha}",
            )
        )
        return Chunk(
            id=chunk_id,
            document_id=document_id,
            page_number=draft.page_number,
            chunk_index=draft.chunk_index,
            text=draft.text,
            text_sha256=text_sha,
        )
